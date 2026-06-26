#!/usr/bin/env python3
"""DSPy version of the computer-use agent (replaces the LangGraph one).

Instead of an explicit tool-call graph, the decision is a DSPy Signature: given
the OS guidance, the task, the history so far, and the *current screenshot*, the
model picks ONE next action. We execute it, take a fresh screenshot, and loop —
a clean "look -> act -> look" agent built from DSPy primitives.

The reusable pieces live in two modules so the CLI, the optimizer, and the
end-to-end benchmark all share them:
  * policy.py  — the Signatures, action execution, LM + decider construction.
  * runner.py  — the look->act loop (`run_agent`) returning a `RunResult`.
This file is the thin command-line front end.

DSPy talks to any provider through LiteLLM, so the model string is
"<provider>/<model>" (e.g. "openai/gpt-5", "anthropic/claude-opus-4-8").

Run (VM booted / spawned):
    # Ubuntu, pointed at a spawned instance
    VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/x-qmp.sock \\
      .venv/bin/python agent_dspy.py --target ubuntu "Create ~/Desktop/x.txt with the date"
    # Windows (default target)
    .venv/bin/python agent_dspy.py "Open Notepad, write a haiku, save to the Desktop"

Provider via --provider or AGENT_PROVIDER; models via OPENAI_MODEL / ANTHROPIC_MODEL.
"""
import os
import sys

import dspy

from config import load_env
# Re-exported for backward compatibility (optimize.py and others import these
# from agent_dspy). The canonical home is now policy.py.
from policy import (  # noqa: F401
    KEY_ALIASES, NextAction, NextActionA11y, RUN_TOOL, SHOT, VM_CLASS,
    build_decider, execute, fmt_tree, make_lm, to_qcodes,
)
from runner import print_usage, run_agent


def main():
    load_env()
    argv = sys.argv[1:]
    provider = os.getenv("AGENT_PROVIDER", "anthropic")
    target = os.getenv("AGENT_TARGET", "win11")
    a11y = False
    while argv and argv[0] in ("--provider", "--target", "--a11y"):
        if argv[0] == "--provider":
            provider, argv = argv[1], argv[2:]
        elif argv[0] == "--a11y":  # Ubuntu only: add the AT-SPI accessibility tree
            a11y, argv = True, argv[1:]
        else:
            target, argv = argv[1], argv[2:]
    if target not in VM_CLASS:
        raise SystemExit(f"unknown --target {target!r} (use win11 or ubuntu)")
    task = argv[0] if argv else "Take a screenshot and describe what's on screen."

    dspy.configure(lm=make_lm(provider))
    decide, label = build_decider(target, a11y=a11y)
    if a11y:
        kind = "UIA" if target == "win11" else "AT-SPI"
        print(f"[a11y] enabling accessibility tree in guest ({kind})...")
    elif "compiled" in label:
        print(f"[loaded optimized policy: {label.split(': ', 1)[-1]}]")

    vm = VM_CLASS[target]()

    # Input trimming to cut per-step tokens/cost:
    #   AGENT_HISTORY_STEPS — keep only the last N actions in history (default 8)
    #   AGENT_SHOT_MAXW     — downscale screenshots to this width (0 = off; opt-in,
    #                         since downscaling can hurt click grounding)
    hist_n = int(os.getenv("AGENT_HISTORY_STEPS", "8"))
    shot_maxw = int(os.getenv("AGENT_SHOT_MAXW", "0"))

    print(f"[dspy | {provider} | {target}{' | a11y' if a11y else ''}]  task: {task}\n")
    res = run_agent(vm, target, decide, task, a11y=a11y, max_steps=40,
                    hist_n=hist_n, shot_maxw=shot_maxw)
    print(f"\n[timing] {res.n_steps} steps in {res.wall_s:.1f}s "
          f"(avg {res.wall_s / max(res.n_steps, 1):.1f}s/step) | "
          f"model {res.llm_s:.1f}s | vm {res.vm_s:.1f}s")
    print_usage(res.usage())
    vm.close()


if __name__ == "__main__":
    main()
