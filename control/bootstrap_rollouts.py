#!/usr/bin/env python3
"""Learn from successful rollouts: harvest demos from passing scenario runs.

optimize.py tunes the policy against a *static* labeled set (one screenshot -> the
right first action). This module closes the loop with the end-to-end benchmark:
run the scenario suite, and for every scenario that **passes**, keep each step it
took — the screen it saw, the running history, and the action that (in a winning
trajectory) turned out to be right — as a labeled demo.

Those demos are written under control/optim/rollouts/<target>/ (a demos.jsonl plus
the per-step PNGs) and folded back into optimize.py's trainset via
`load_rollout_demos(target)`. So the optimizer is no longer limited to the
hand-labeled screens; it also learns from real, verified successful behavior.

Run (needs a VM, same as evals.py):
    control/.venv/bin/python control/bootstrap_rollouts.py --target ubuntu
    control/.venv/bin/python control/bootstrap_rollouts.py --target ubuntu --scenario webmail
then recompile so the demos take effect:
    control/.venv/bin/python control/optimize.py --target ubuntu --method bootstrap
"""
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

ROLLOUTS = os.path.join(_HERE, "optim", "rollouts")

# Actions worth keeping as demos. Coordinate clicks carry their (x,y) in the
# demo, which is useful few-shot signal even though the dev metric only tool-matches.
HARVEST_TOOLS = {"key", "run_bash", "run_powershell", "click_element",
                 "left_click", "double_click", "type_text"}


def _reconstruct_history(steps, upto):
    """The history string the agent saw entering step `upto` (mirrors runner.py)."""
    lines = [f"{s.i}. {s.tool} {s.args} -> {(s.obs or '')[:300]}"
             for s in steps[:upto]]
    return "\n".join(lines[-8:]) or "(none yet)"


def harvest(result, target, *, min_score=1.0) -> list[dict]:
    """Turn one passing RunResult (in result['_res']) into labeled-demo records."""
    if not result or result.get("score", 0) < min_score:
        return []
    res = result.get("_res")
    if res is None:
        return []
    scenario = result["scenario"]
    out_dir = os.path.join(ROLLOUTS, target, scenario)
    os.makedirs(out_dir, exist_ok=True)
    demos = []
    for s in res.steps:
        if s.done or s.tool not in HARVEST_TOOLS or not s.shot:
            continue
        png = os.path.join(out_dir, f"step_{s.i:02d}.png")
        try:
            shutil.copyfile(s.shot, png)
        except OSError:
            continue
        gold_key = None
        if s.tool == "key":
            try:
                gold_key = json.loads(s.args or "{}").get("keys")
            except (json.JSONDecodeError, TypeError):
                gold_key = None
        demos.append({
            "scenario": scenario, "target": target, "task": res.task,
            "history": _reconstruct_history(res.steps, s.i),
            "screenshot": os.path.relpath(png, _HERE),
            "tool": s.tool, "args": s.args, "gold_key": gold_key,
        })
    return demos


def _demos_path(target):
    return os.path.join(ROLLOUTS, target, "demos.jsonl")


def save_demos(target, demos, *, append=True):
    path = _demos_path(target)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "a" if append and os.path.exists(path) else "w"
    with open(path, mode) as f:
        for d in demos:
            f.write(json.dumps(d) + "\n")
    return path


def load_rollout_demos(target):
    """Read harvested demos for `target` as dspy.Examples for optimize.py's trainset.
    Returns [] if none have been harvested yet (so optimize.py works without a VM)."""
    path = _demos_path(target)
    if not os.path.exists(path):
        return []
    import dspy

    from os_context import guidance
    g = guidance(target, 1280, 800)
    out = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        shot = os.path.join(_HERE, d["screenshot"])
        if not os.path.exists(shot):
            continue
        e = dspy.Example(
            guidance=g, task=d["task"], history=d.get("history", "(none yet)"),
            screenshot=dspy.Image(shot), acceptable=[d["tool"]],
            gold_key=d.get("gold_key"), target=target,
        )
        out.append(e.with_inputs("guidance", "task", "history", "screenshot"))
    return out


def main():
    from config import load_env
    import dspy
    from evals import run_scenario
    from policy import VM_CLASS, build_decider, make_lm
    from scenarios import registry

    load_env()
    argv = sys.argv[1:]
    provider = os.getenv("AGENT_PROVIDER", "anthropic")
    target = os.getenv("AGENT_TARGET", "ubuntu")
    names = None
    while argv:
        a = argv.pop(0)
        if a == "--provider":
            provider = argv.pop(0)
        elif a == "--target":
            target = argv.pop(0)
        elif a == "--scenario":
            names = [s.strip() for s in argv.pop(0).split(",") if s.strip()]
        else:
            raise SystemExit(f"unknown arg {a!r}")
    if target not in VM_CLASS:
        raise SystemExit(f"unknown --target {target!r}")

    scenarios = registry.select(names=names, target=target)
    dspy.configure(lm=make_lm(provider))
    decide, label = build_decider(target, optimized=True)
    print(f"[bootstrap | {provider} | {target} | policy: {label}]  "
          f"running {len(scenarios)} scenario(s) to harvest demos from passes")

    vm = VM_CLASS[target]()
    trace_dir = os.path.join(_HERE, "optim", "rollouts", "_traces")
    total = 0
    for sc in scenarios:
        r = run_scenario(vm, target, decide, sc, trace_dir=trace_dir, collect=True)
        tag = "PASS" if r["passed"] else "fail"
        demos = harvest(r, target)
        if demos:
            save_demos(target, demos)
            total += len(demos)
        print(f"  {tag}  {sc.name:10} score={r['score']:.2f}  harvested {len(demos)} demos")
    vm.close()
    print(f"\nharvested {total} demos -> {os.path.relpath(_demos_path(target), _ROOT)}")
    print("recompile to use them:  control/.venv/bin/python control/optimize.py "
          f"--target {target} --method bootstrap")


if __name__ == "__main__":
    main()
