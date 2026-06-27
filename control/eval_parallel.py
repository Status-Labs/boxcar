#!/usr/bin/env python3
"""Shard the scenario suite across several running clones, in parallel.

`evals.py` drives one VM sequentially; with `--samples K` a full suite is K times
as long, which gets expensive. This orchestrator fans the work out over N
*disposable clones* you've already spawned (`make up NAME=a`, `NAME=b`, …): it
splits the scenarios across the clones, runs one `evals.py` **worker subprocess**
per clone (each pinned to that clone's SSH port + QMP socket), then merges the
per-clone JSON reports into one combined scorecard + report.

Subprocess isolation is deliberate: every worker is the already-proven single-VM
`evals.py` path with its own VM connection and its own dspy/LM state, so there is
no cross-clone shared state or thread-safety to reason about — only the split and
the merge, which are pure and unit-tested (`scenarios/test_scenarios.py`).

Whole scenarios are assigned to clones (round-robin), so a scenario's K samples
always run on one clone and its aggregate comes back whole — the merge is just a
concatenation. This balances well when #scenarios >= #clones (the common case:
9 scenarios over 2-4 clones); with more clones than scenarios the extras idle
(sample-level splitting is a future refinement).

Run (from the repo root or control/):
    # spawn a few clones first, log each into the desktop, then:
    make up NAME=a; make up NAME=b; make up NAME=c
    control/.venv/bin/python control/eval_parallel.py --target ubuntu --samples 5
    # or pick specific clones:
    control/.venv/bin/python control/eval_parallel.py --target ubuntu --names a,b,c
"""
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import evals  # noqa: E402  (reuse scorecard / report writer / select)
from scenarios import registry  # noqa: E402

REPORTS = evals.REPORTS


# --------------------------------------------------------------------------- #
# Pure helpers (host-testable — no VM, no subprocess).
# --------------------------------------------------------------------------- #
def parse_clones(ps_output: str, target: str) -> dict:
    """Map clone name -> (ssh_port, qmp_sock) from `ps` output of qemu cmdlines.

    Mirrors the Makefile: a clone is `-name <target>-<name>` and its forwarded
    SSH port is the `hostfwd=tcp:127.0.0.1:<port>` on the same cmdline. The QMP
    socket path follows the project layout (`vms/<target>/clones/<name>-qmp.sock`).
    """
    import re
    out: dict = {}
    name_re = re.compile(rf"-name\s+{re.escape(target)}-(\S+)")
    port_re = re.compile(r"hostfwd=tcp:127\.0\.0\.1:(\d+)-")
    for line in ps_output.splitlines():
        nm = name_re.search(line)
        pt = port_re.search(line)
        if not nm or not pt:
            continue
        name = nm.group(1)
        sock = os.path.join(_ROOT, "vms", target, "clones", f"{name}-qmp.sock")
        out[name] = (int(pt.group(1)), sock)
    return out


def split_round_robin(items: list, n: int) -> list:
    """Deal `items` into `n` buckets round-robin; drop empty trailing buckets."""
    buckets: list = [[] for _ in range(n)]
    for i, it in enumerate(items):
        buckets[i % n].append(it)
    return [b for b in buckets if b]


def merge_results(shard_results: list, scenario_order: list) -> list:
    """Flatten per-shard `results` lists back into the original scenario order.

    `shard_results` is a list of (per-shard) results-lists; any scenario missing
    from all shards (e.g. a worker that crashed before writing it) is left out by
    the caller, which synthesizes an error record for it instead."""
    by_name = {}
    for results in shard_results:
        for r in results:
            by_name[r["scenario"]] = r
    return [by_name[name] for name in scenario_order if name in by_name]


def _error_record(name: str, detail: str, samples: int = 1) -> dict:
    """A FAIL placeholder for a scenario whose worker shard never reported it.

    When samples>1 it must carry the same pass-rate keys an aggregated record
    has, so the k-sample scorecard/report don't KeyError on a dead shard."""
    rec = {"scenario": name, "tags": [], "passed": False, "score": 0.0,
           "steps": 0, "wall_s": 0.0, "llm_s": 0.0, "tokens": 0, "cost": 0.0,
           "detail": detail, "error": detail}
    if samples > 1:
        rec.update(samples=samples, passes=0, pass_rate=0.0, score_mean=0.0,
                   score_sd=0.0, flake=False, runs=[])
    return rec


# --------------------------------------------------------------------------- #
# Orchestration.
# --------------------------------------------------------------------------- #
def _running_clones(target: str) -> dict:
    try:
        out = subprocess.run(["ps", "-ww", "-o", "args=", "-C",
                              "qemu-system-x86_64"],
                             capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        return {}
    return parse_clones(out, target)


def _worker_cmd(opts, scenarios, report_path):
    cmd = [sys.executable, os.path.join(_HERE, "evals.py"),
           "--target", opts["target"],
           "--scenario", ",".join(s.name for s in scenarios),
           "--samples", str(opts["samples"]),
           "--report-path", report_path]
    if opts["provider"]:
        cmd += ["--provider", opts["provider"]]
    if opts["a11y"]:
        cmd += ["--a11y"]
    if not opts["optimized"]:
        cmd += ["--no-optimized"]
    if opts["max_steps"]:
        cmd += ["--max-steps", str(opts["max_steps"])]
    return cmd


def _parse_argv(argv):
    opts = {
        "provider": os.getenv("AGENT_PROVIDER", ""),
        "target": os.getenv("AGENT_TARGET", "ubuntu"),
        "names": None, "scenarios": None, "tags": None,
        "optimized": True, "a11y": False, "max_steps": None,
        "samples": int(os.getenv("AGENT_SAMPLES", "1")),
    }
    while argv:
        a = argv.pop(0)
        if a == "--provider":
            opts["provider"] = argv.pop(0)
        elif a == "--target":
            opts["target"] = argv.pop(0)
        elif a == "--names":
            opts["names"] = [s.strip() for s in argv.pop(0).split(",") if s.strip()]
        elif a == "--scenario":
            opts["scenarios"] = [s.strip() for s in argv.pop(0).split(",") if s.strip()]
        elif a == "--tag":
            opts["tags"] = [t.strip() for t in argv.pop(0).split(",") if t.strip()]
        elif a == "--no-optimized":
            opts["optimized"] = False
        elif a == "--a11y":
            opts["a11y"] = True
        elif a == "--max-steps":
            opts["max_steps"] = int(argv.pop(0))
        elif a == "--samples":
            opts["samples"] = int(argv.pop(0))
        else:
            raise SystemExit(f"unknown arg {a!r}")
    return opts


def main():
    from config import load_env
    load_env()
    opts = _parse_argv(sys.argv[1:])
    target = opts["target"]

    clones = _running_clones(target)
    if opts["names"]:
        missing = [n for n in opts["names"] if n not in clones]
        if missing:
            raise SystemExit(f"clones not running: {', '.join(missing)} "
                             f"(have: {', '.join(clones) or 'none'})")
        clones = {n: clones[n] for n in opts["names"]}
    if not clones:
        raise SystemExit(f"no running {target} clones found — spawn some first "
                         f"(e.g. `make up NAME=a`)")

    scenarios = registry.select(names=opts["scenarios"], target=target,
                                tags=opts["tags"])
    if not scenarios:
        raise SystemExit("no scenarios match the given --scenario/--tag/--target")

    names = sorted(clones)
    groups = split_round_robin(scenarios, len(names))
    runtag = time.strftime("%Y%m%d-%H%M%S")
    os.makedirs(REPORTS, exist_ok=True)

    print(f"[eval-parallel | {target} | samples: {opts['samples']}]")
    print(f"{len(scenarios)} scenario(s) over {len(groups)} clone(s):")
    procs = []
    for name, group in zip(names, groups):
        port, sock = clones[name]
        report_path = os.path.join(REPORTS, f"parallel-{runtag}-{name}.json")
        env = dict(os.environ, VM_SSH_PORT=str(port), VM_QMP_SOCK=sock)
        print(f"  {name} (ssh:{port}) <- {', '.join(s.name for s in group)}")
        log = open(os.path.join(REPORTS, f"parallel-{runtag}-{name}.log"), "w")
        p = subprocess.Popen(_worker_cmd(opts, group, report_path),
                             env=env, stdout=log, stderr=subprocess.STDOUT)
        procs.append((name, group, report_path, p, log))

    shard_results, errors = [], []
    for name, group, report_path, p, log in procs:
        rc = p.wait()
        log.close()
        if rc == 0 and os.path.exists(report_path):
            shard_results.append(json.load(open(report_path))["results"])
        else:
            why = f"worker for clone {name!r} failed (rc={rc}); see its .log"
            print(f"  ! {why}")
            errors += [_error_record(s.name, why, opts["samples"]) for s in group]

    order = [s.name for s in scenarios]
    results = merge_results(shard_results, order)
    results += [e for e in errors if e["scenario"] not in {r["scenario"] for r in results}]
    results.sort(key=lambda r: order.index(r["scenario"]))

    print("\n" + evals.scorecard(results))
    evals._write_report(results, dict(opts, report_path=None), "parallel", runtag)


if __name__ == "__main__":
    main()
