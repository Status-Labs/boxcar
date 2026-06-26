#!/usr/bin/env python3
"""The look -> act -> look agent loop, factored out so every caller shares it.

`agent_dspy.py` (the CLI) and `evals.py` (the end-to-end benchmark) both drive an
agent the same way: screenshot the VM, ask the DSPy decider for ONE action,
execute it, repeat until `done` or a step cap. That loop lives here as
`run_agent(...)`, and it returns a `RunResult` carrying everything a caller might
want — the step trace (for the rollout optimizer), timing, and token usage (for
the scorecard).
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field

import dspy

from policy import SHOT, _downscale, execute, fmt_tree, parse_args


@dataclass
class Step:
    """One decision in a rollout: the screen the model saw, what it chose, and
    the observation that came back. `shot` is a saved copy of the pre-action
    screenshot when trace capture is on (used by bootstrap_rollouts.py)."""
    i: int
    tool: str
    args: str
    note: str
    done: bool
    obs: str = ""
    shot: str | None = None
    ui_tree: str | None = None
    llm_s: float = 0.0


@dataclass
class RunResult:
    task: str
    target: str
    steps: list[Step] = field(default_factory=list)
    done: bool = False
    stuck: bool = False           # aborted early: repeated the same no-op action
    final_note: str = ""
    wall_s: float = 0.0
    llm_s: float = 0.0
    vm_s: float = 0.0

    @property
    def n_steps(self) -> int:
        return len(self.steps)

    usage_since: int = 0          # index into lm.history when this run started

    def usage(self) -> dict:
        """Sum tokens + cost from the DSPy LM history for this run (best-effort)."""
        return lm_usage(self.usage_since)


def run_agent(vm, target, decide, task, *, a11y=False, max_steps=40,
              hist_n=8, shot_maxw=0, trace_dir=None, verbose=True,
              stall_warn=3, stall_abort=8):
    """Drive `vm` toward `task` using the DSPy `decide` program.

    trace_dir: if given, each step's pre-action screenshot is copied there as
               step_NN.png and recorded on the Step (enables demo harvesting).
    stall_warn/stall_abort: a vision agent with a weak driver can repeat the exact
               same no-op action forever (e.g. pressing ctrl-l 25x). After
               `stall_warn` identical (tool,args) in a row we inject an escalating
               corrective hint into the history; after `stall_abort` we give up
               early (saving steps/tokens) and mark the run `stuck`. Defaults can
               be overridden via AGENT_STALL_WARN / AGENT_STALL_ABORT.
    Returns a RunResult.
    """
    from os_context import guidance

    stall_warn = int(os.getenv("AGENT_STALL_WARN", stall_warn))
    stall_abort = int(os.getenv("AGENT_STALL_ABORT", stall_abort))

    w, h = vm._resolution()  # noqa: SLF001 - prime + report screen size
    rules = guidance(target, w, h)
    if a11y:
        vm.ensure_a11y()
    if trace_dir:
        os.makedirs(trace_dir, exist_ok=True)

    res = RunResult(task=task, target=target, usage_since=_lm_history_len())
    history_lines: list[str] = []
    prev_sig, repeats, clicks_no_type = None, 0, 0
    t_start = time.perf_counter()
    for i in range(max_steps):
        c0 = time.perf_counter()
        vm.screenshot(SHOT)
        if shot_maxw:
            _downscale(SHOT, shot_maxw)
        hist = "\n".join(history_lines[-hist_n:]) or "(none yet)"
        kw = dict(guidance=rules, task=task, history=hist, screenshot=dspy.Image(SHOT))
        tree_str = None
        if a11y:
            tree_str = fmt_tree(vm.ui_tree())
            kw["ui_tree"] = tree_str
        shot_copy = None
        if trace_dir:
            shot_copy = os.path.join(trace_dir, f"step_{i:02d}.png")
            shutil.copyfile(SHOT, shot_copy)
        c1 = time.perf_counter()
        pred = decide(**kw)
        c2 = time.perf_counter()

        done = str(getattr(pred, "done", "")).lower() == "true"
        step = Step(i=i, tool=(pred.tool or "").strip(), args=pred.args or "",
                    note=pred.note or "", done=done, shot=shot_copy,
                    ui_tree=tree_str, llm_s=c2 - c1)
        res.llm_s += c2 - c1
        res.vm_s += c1 - c0
        if verbose:
            print(f"[{i}] {step.tool} {step.args}  (llm {step.llm_s:.1f}s) — {step.note}")
        if done:
            step.obs = "(done)"
            res.steps.append(step)
            res.done = True
            res.final_note = step.note
            break
        # Stall detection, two signals:
        #  (1) the same (tool,args) chosen repeatedly — a hard no-op loop;
        #  (2) consecutive coordinate-clicks with no typing in between — the
        #      "field-focus thrash" failure (re-clicking a form field at slightly
        #      different coords forever), which (1) misses because the args vary.
        sig = (step.tool, step.args)
        repeats = repeats + 1 if sig == prev_sig else 1
        prev_sig = sig
        if step.tool in ("left_click", "double_click"):
            clicks_no_type += 1
        elif step.tool in ("type_text", "key", "run_bash", "run_powershell"):
            clicks_no_type = 0

        a0 = time.perf_counter()
        step.obs = execute(vm, target, step.tool, parse_args(step.args))
        res.vm_s += time.perf_counter() - a0

        if repeats >= stall_abort or clicks_no_type >= stall_abort:
            res.stuck = True
            why = (f"repeated `{step.tool} {step.args}` {repeats}x" if repeats >= stall_abort
                   else f"clicked {clicks_no_type}x without typing")
            res.final_note = f"aborted (stuck): {why} with no progress"
            if verbose:
                print(f"[stall] {res.final_note} — giving up early")
            res.steps.append(step)
            break
        if repeats >= stall_warn:
            step.obs += (f"  ⚠ STALL: you have chosen this exact action {repeats}x in "
                         "a row and it is NOT working. Do NOT repeat it — switch "
                         "methods (e.g. if a page won't load, use run_bash/curl or the "
                         "shell; otherwise try a different element or action).")
        elif clicks_no_type >= stall_warn:
            step.obs += (f"  ⚠ You have clicked {clicks_no_type}x without typing. After "
                         "clicking a field ONCE, your next action should be type_text. "
                         "The first form field is usually already focused — just type. "
                         "If a click isn't landing, press Tab to move between fields "
                         "instead of re-clicking.")
        res.steps.append(step)
        history_lines.append(f"{i}. {step.tool} {step.args} -> {step.obs[:300]}")

    res.wall_s = time.perf_counter() - t_start
    res.final_note = res.final_note or (res.steps[-1].note if res.steps else "")
    return res


def _lm_history_len() -> int:
    try:
        return len(dspy.settings.lm.history)
    except Exception:  # noqa: BLE001
        return 0


def lm_usage(since: int = 0) -> dict:
    """Tokens + cost from the configured DSPy LM's call history (best-effort).
    `since` slices the history (pass a prior len() to get a per-scenario delta).
    Returns {calls, prompt_tokens, completion_tokens, reasoning_tokens, cost}."""
    try:
        hist = dspy.settings.lm.history[since:]
    except Exception:  # noqa: BLE001
        return {}

    def _usage(h):
        u = h.get("usage") or {}
        return u if isinstance(u, dict) else getattr(u, "__dict__", {})

    def _reasoning(h):
        d = _usage(h).get("completion_tokens_details")
        if d is None:
            return 0
        return (d.get("reasoning_tokens", 0) if isinstance(d, dict)
                else getattr(d, "reasoning_tokens", 0)) or 0

    return {
        "calls": len(hist),
        "prompt_tokens": sum(_usage(h).get("prompt_tokens", 0) or 0 for h in hist),
        "completion_tokens": sum(_usage(h).get("completion_tokens", 0) or 0 for h in hist),
        "reasoning_tokens": sum(_reasoning(h) for h in hist),
        "cost": sum((h.get("cost") or 0) for h in hist),
    }


def print_usage(u: dict | None = None):
    u = u if u is not None else lm_usage()
    if not u:
        return
    rstr = f" ({u['reasoning_tokens']} reasoning)" if u.get("reasoning_tokens") else ""
    cost_str = f" | est cost ${u['cost']:.4f}" if u.get("cost") else ""
    print(f"[tokens] {u['calls']} LLM calls, {u['prompt_tokens']} in + "
          f"{u['completion_tokens']} out{rstr}{cost_str}")
