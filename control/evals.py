#!/usr/bin/env python3
"""End-to-end benchmark: drive the agent through the scenario suite and score it.

This is the "proper eval" for a computer-use agent: instead of grading a single
action against a label (that's optimize.py's cheap proxy), each scenario is run
*to completion* on a live VM and scored by its own verifiable end state — a saved
draft, a downloaded+summed CSV, a created account, a flipped setting. The result
is a scorecard: pass-rate, score, steps, tokens, cost, and wall-time per scenario.

The same suite is also exposed as a `dspy.Evaluate` program (see `--dspy-evaluate`
and `ScenarioRunner`), so the end-to-end success rate is a first-class DSPy metric
you can point an optimizer at — not just the per-step proxy.

Prereqs: a booted/spawned VM reachable over SSH+QMP (same env vars as
agent_dspy.py) and provider keys in control/.env. Web scenarios start their mock
server on the host automatically; the guest reaches it at http://10.0.2.2:<port>.

Run (from the repo root or control/):
    # whole Ubuntu suite, compiled policy, against a spawned VM
    VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/x-qmp.sock \\
      control/.venv/bin/python control/evals.py --target ubuntu

    control/.venv/bin/python control/evals.py --target ubuntu --scenario webmail,signup
    control/.venv/bin/python control/evals.py --target ubuntu --tag web --no-optimized
    control/.venv/bin/python control/evals.py --target ubuntu --dspy-evaluate

    # k-sample pass-RATE: run each scenario 5x, report pass@5 + score mean/sd so
    # non-deterministic (vision-click) flakiness shows up instead of a noisy 0/1.
    control/.venv/bin/python control/evals.py --target ubuntu --samples 5
"""
import json
import os
import sys
import time

# Make the repo's `scenarios` package importable (control/ is the script dir, so
# `policy`, `runner`, etc. already resolve; the repo root gives us `scenarios`).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import dspy  # noqa: E402

from config import load_env  # noqa: E402
from policy import VM_CLASS, build_decider, make_lm  # noqa: E402
from runner import lm_usage, run_agent  # noqa: E402
from scenarios.framework import ScenarioContext  # noqa: E402
from scenarios import registry  # noqa: E402

REPORTS = os.path.join(_HERE, "optim", "reports")


def run_scenario(vm, target, decide, scenario, *, max_steps=None, trace_dir=None,
                 verbose=True, collect=False, a11y=False):
    """Run one scenario end to end on `vm` and return a result dict.

    collect=True attaches the live RunResult under the "_res" key (in-process only,
    not serialized) so the rollout harvester can read the step trace."""
    ctx = ScenarioContext(port=scenario.port,
                          workdir=os.path.join(trace_dir or "", scenario.name)
                          if trace_dir else "")
    started = lm_usage()  # (unused snapshot kept for symmetry/debug)
    del started
    err = None
    try:
        scenario.setup(ctx, vm)
        task = scenario.task_text(ctx)
        if verbose:
            print(f"\n=== {scenario.name} ===\n{task}\n")
        sdir = os.path.join(trace_dir, scenario.name) if trace_dir else None
        res = run_agent(vm, target, decide, task, a11y=a11y,
                        max_steps=max_steps or scenario.max_steps,
                        trace_dir=sdir, verbose=verbose)
        verdict = scenario.check(ctx, vm)
    except Exception as e:  # noqa: BLE001 - one scenario must not kill the suite
        err = f"{type(e).__name__}: {e}"
        from scenarios.framework import CheckResult
        verdict = CheckResult.fail(f"runner error: {err}")
        res = None
    finally:
        if scenario.teardown:
            try:
                scenario.teardown(ctx, vm)
            except Exception:  # noqa: BLE001
                pass
        ctx.stop()

    usage = res.usage() if res else {}
    out = {"_res": res} if collect else {}
    out.update({
        "scenario": scenario.name,
        "tags": list(scenario.tags),
        "passed": verdict.passed,
        "score": round(verdict.score, 3),
        "detail": verdict.detail,
        "steps": res.n_steps if res else 0,
        "agent_done": res.done if res else False,
        "stuck": res.stuck if res else False,
        "final_note": res.final_note if res else "",
        "wall_s": round(res.wall_s, 1) if res else 0.0,
        "llm_s": round(res.llm_s, 1) if res else 0.0,
        "tokens": usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        "cost": round(usage.get("cost", 0.0), 4),
        "error": err,
    })
    return out


def _aggregate(runs) -> dict:
    """Collapse K per-run result dicts for one scenario into a pass-RATE record.

    Vision clicks are non-deterministic run-to-run, so a single pass/fail is noisy.
    Running each scenario K times and reporting pass@K + score mean/sd surfaces
    *flaky* scenarios (some passes, some fails) that a single run would mislabel.
    The K raw per-run dicts are kept under "runs" so the JSON report is auditable.
    """
    k = len(runs)
    passes = sum(r["passed"] for r in runs)
    scores = [r["score"] for r in runs]
    mean = sum(scores) / k
    sd = (sum((s - mean) ** 2 for s in scores) / k) ** 0.5  # population sd
    flake = 0 < passes < k
    if passes == k:
        detail = f"all {k} passed"
    elif passes == 0:
        # Surface a representative failure reason rather than a bare 0/K.
        detail = next((r["detail"] for r in runs if r["detail"]), "all failed")
    else:
        detail = f"FLAKY {passes}/{k} passed; scores " + ",".join(
            f"{s:.1f}" for s in scores)
    return {
        "scenario": runs[0]["scenario"],
        "tags": runs[0]["tags"],
        "samples": k,
        "passes": passes,
        "pass_rate": round(passes / k, 3),
        "flake": flake,
        # Back-compatible scalars so scorecard()/report keep working: `passed`
        # means "passed every sample", `score` is the mean score.
        "passed": passes == k,
        "score": round(mean, 3),
        "score_mean": round(mean, 3),
        "score_sd": round(sd, 3),
        "steps": round(sum(r["steps"] for r in runs) / k, 1),
        "wall_s": round(sum(r["wall_s"] for r in runs) / k, 1),
        "llm_s": round(sum(r["llm_s"] for r in runs) / k, 1),
        "tokens": sum(r["tokens"] for r in runs),         # total spent over K runs
        "cost": round(sum(r["cost"] for r in runs), 4),
        "detail": detail,
        "error": next((r["error"] for r in runs if r["error"]), None),
        "runs": [{kk: vv for kk, vv in r.items() if not kk.startswith("_")}
                 for r in runs],
    }


def scorecard(results) -> str:
    """Format the results as a fixed-width table + summary line.

    Switches to a pass-RATE layout when any scenario was sampled more than once."""
    if results and any(r.get("samples", 1) > 1 for r in results):
        return _scorecard_k(results)
    cols = [("scenario", 11), ("result", 7), ("score", 6), ("steps", 6),
            ("wall", 7), ("tokens", 8), ("cost", 8), ("detail", 44)]
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [head, "-" * len(head)]
    for r in results:
        cells = [
            r["scenario"][:11].ljust(11),
            ("PASS" if r["passed"] else "FAIL").ljust(7),
            f"{r['score']:.2f}".ljust(6),
            str(r["steps"]).ljust(6),
            f"{r['wall_s']:.0f}s".ljust(7),
            str(r["tokens"]).ljust(8),
            (f"${r['cost']:.4f}" if r["cost"] else "-").ljust(8),
            (r["detail"] or "")[:44],
        ]
        lines.append("  ".join(cells))
    n = len(results)
    passed = sum(r["passed"] for r in results)
    mean = sum(r["score"] for r in results) / n if n else 0.0
    cost = sum(r["cost"] for r in results)
    lines.append("-" * len(head))
    lines.append(f"{passed}/{n} passed | mean score {mean:.2f} | "
                 f"total cost ${cost:.4f}")
    return "\n".join(lines)


def _scorecard_k(results) -> str:
    """Pass-rate scorecard for k-sample runs: pass@K, score mean±sd, flake flag."""
    k = max(r.get("samples", 1) for r in results)
    cols = [("scenario", 11), (f"pass@{k}", 7), ("score(mean±sd)", 15),
            ("steps", 6), ("flake", 6), ("cost", 9), ("detail", 34)]
    head = "  ".join(name.ljust(w) for name, w in cols)
    lines = [head, "-" * len(head)]
    for r in results:
        cells = [
            r["scenario"][:11].ljust(11),
            f"{r['passes']}/{r['samples']}".ljust(7),
            f"{r['score_mean']:.2f}±{r['score_sd']:.2f}".ljust(15),
            f"{r['steps']:.0f}".ljust(6),
            ("FLAKY" if r["flake"] else "-").ljust(6),
            (f"${r['cost']:.4f}" if r["cost"] else "-").ljust(9),
            (r["detail"] or "")[:34],
        ]
        lines.append("  ".join(cells))
    n = len(results)
    mean_pr = sum(r["pass_rate"] for r in results) / n if n else 0.0
    mean_sc = sum(r["score_mean"] for r in results) / n if n else 0.0
    flaky = sum(r["flake"] for r in results)
    cost = sum(r["cost"] for r in results)
    lines.append("-" * len(head))
    lines.append(f"mean pass-rate {mean_pr:.0%} | mean score {mean_sc:.2f} | "
                 f"{flaky} flaky | total cost ${cost:.4f}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# DSPy-native view: the suite as a dspy.Evaluate program.
# --------------------------------------------------------------------------- #
class ScenarioRunner(dspy.Module):
    """A DSPy program whose `forward(scenario_name)` runs a scenario end to end on
    a VM and returns a Prediction carrying the verifiable score. Pair it with
    `scenario_metric` and a devset of scenario names to get a `dspy.Evaluate`
    over true task success — the end-to-end counterpart to optimize.py's proxy."""

    def __init__(self, vm, target, decide, max_steps=None, trace_dir=None, a11y=False):
        super().__init__()
        self.vm, self.target, self.decide = vm, target, decide
        self.max_steps, self.trace_dir, self.a11y = max_steps, trace_dir, a11y

    def forward(self, scenario_name):
        sc = registry.get(scenario_name)
        r = run_scenario(self.vm, self.target, self.decide, sc,
                         max_steps=self.max_steps, trace_dir=self.trace_dir,
                         verbose=False, a11y=self.a11y)
        return dspy.Prediction(score=r["score"], passed=r["passed"],
                               detail=r["detail"], result=r)


def scenario_metric(example, pred, trace=None):
    """End-to-end metric: the scenario's own 0..1 verifiable score."""
    return float(getattr(pred, "score", 0.0))


def _connect_vm(target):
    vm = VM_CLASS[target]()
    vm._resolution()  # noqa: SLF001 - fail fast if QMP/screenshot is unreachable
    return vm


def _parse_argv(argv):
    opts = {
        "provider": os.getenv("AGENT_PROVIDER", "anthropic"),
        "target": os.getenv("AGENT_TARGET", "ubuntu"),
        "scenarios": None, "tags": None, "optimized": True, "a11y": False,
        "max_steps": None, "dspy_evaluate": False, "trace": False,
        "samples": int(os.getenv("AGENT_SAMPLES", "1")),
        "report_path": None,
    }
    while argv:
        a = argv.pop(0)
        if a == "--provider":
            opts["provider"] = argv.pop(0)
        elif a == "--target":
            opts["target"] = argv.pop(0)
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
        elif a == "--report-path":
            opts["report_path"] = argv.pop(0)
        elif a == "--dspy-evaluate":
            opts["dspy_evaluate"] = True
        elif a == "--trace":
            opts["trace"] = True
        else:
            raise SystemExit(f"unknown arg {a!r}")
    return opts


def main():
    load_env()
    opts = _parse_argv(sys.argv[1:])
    target = opts["target"]
    if target not in VM_CLASS:
        raise SystemExit(f"unknown --target {target!r} (use win11 or ubuntu)")

    samples = opts["samples"]
    if samples < 1:
        raise SystemExit("--samples must be >= 1")

    scenarios = registry.select(names=opts["scenarios"], target=target, tags=opts["tags"])
    if not scenarios:
        raise SystemExit("no scenarios match the given --scenario/--tag/--target")

    dspy.configure(lm=make_lm(opts["provider"]))
    decide, label = build_decider(target, a11y=opts["a11y"], optimized=opts["optimized"])
    runtag = time.strftime("%Y%m%d-%H%M%S")
    trace_dir = os.path.join(REPORTS, f"trace-{runtag}") if opts["trace"] else None

    print(f"[evals | {opts['provider']} | {target} | policy: {label}"
          f"{f' | samples: {samples}' if samples > 1 else ''}]")
    print(f"running {len(scenarios)} scenario(s): {', '.join(s.name for s in scenarios)}")

    vm = _connect_vm(target)

    if opts["dspy_evaluate"]:
        if samples > 1:
            print("[note] --samples is ignored under --dspy-evaluate (single pass)")
        return _run_dspy_evaluate(vm, target, decide, scenarios, opts, runtag)

    results = []
    for sc in scenarios:
        runs = []
        for i in range(samples):
            # Trace dir is per-sample so repeated runs don't overwrite each other.
            sample_trace = (os.path.join(trace_dir, f"s{i + 1}")
                            if trace_dir and samples > 1 else trace_dir)
            r = run_scenario(vm, target, decide, sc, a11y=opts["a11y"],
                             max_steps=opts["max_steps"], trace_dir=sample_trace)
            runs.append(r)
            tag = f" [{i + 1}/{samples}]" if samples > 1 else ""
            print(f"--> {sc.name}{tag}: {'PASS' if r['passed'] else 'FAIL'} "
                  f"(score {r['score']:.2f}) — {r['detail']}")
        results.append(runs[0] if samples == 1 else _aggregate(runs))
    vm.close()

    print("\n" + scorecard(results))
    _write_report(results, opts, label, runtag)


def _run_dspy_evaluate(vm, target, decide, scenarios, opts, runtag):
    """Score the suite through dspy.Evaluate (single-threaded: one shared VM)."""
    devset = [dspy.Example(scenario_name=s.name).with_inputs("scenario_name")
              for s in scenarios]
    program = ScenarioRunner(vm, target, decide, max_steps=opts["max_steps"],
                             a11y=opts["a11y"])
    evaluate = dspy.Evaluate(devset=devset, metric=scenario_metric,
                             num_threads=1, display_progress=True,
                             return_outputs=True)
    score, outputs = evaluate(program)
    vm.close()
    results = [o[1].result for o in outputs if hasattr(o[1], "result")]
    print(f"\n[dspy.Evaluate] mean end-to-end score: {score}")
    print("\n" + scorecard(results))
    _write_report(results, opts, "dspy.Evaluate", runtag)


def _write_report(results, opts, label, runtag):
    path = opts.get("report_path") or os.path.join(REPORTS, f"eval-{runtag}.json")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    samples = opts.get("samples", 1)
    payload = {
        "runtag": runtag, "provider": opts["provider"], "target": opts["target"],
        "policy": label, "n": len(results), "samples": samples,
        "passed": sum(r["passed"] for r in results),
        "mean_score": round(sum(r["score"] for r in results) / len(results), 3)
        if results else 0.0,
        "total_cost": round(sum(r["cost"] for r in results), 4),
        "results": results,
    }
    if samples > 1:
        payload["mean_pass_rate"] = round(
            sum(r.get("pass_rate", float(r["passed"])) for r in results) / len(results), 3
        ) if results else 0.0
        payload["n_flaky"] = sum(r.get("flake", False) for r in results)
    json.dump(payload, open(path, "w"), indent=2)
    print(f"\n[report] {os.path.relpath(path, _ROOT)}")


if __name__ == "__main__":
    main()
