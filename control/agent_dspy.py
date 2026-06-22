#!/usr/bin/env python3
"""DSPy version of the computer-use agent (replaces the LangGraph one).

Instead of an explicit tool-call graph, the decision is a DSPy Signature: given
the OS guidance, the task, the history so far, and the *current screenshot*, the
model picks ONE next action. We execute it, take a fresh screenshot, and loop —
a clean "look -> act -> look" agent built from DSPy primitives.

DSPy talks to any provider through LiteLLM, so the model string is
"<provider>/<model>" (e.g. "openai/gpt-4o", "anthropic/claude-opus-4-8").

Run (VM booted / spawned):
    # Ubuntu, pointed at a spawned instance
    VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/x-qmp.sock \\
      .venv/bin/python agent_dspy.py --target ubuntu "Create ~/Desktop/x.txt with the date"
    # Windows (default target)
    .venv/bin/python agent_dspy.py "Open Notepad, write a haiku, save to the Desktop"

Provider via --provider or AGENT_PROVIDER; models via OPENAI_MODEL / ANTHROPIC_MODEL.
"""
import json
import os
import sys

import dspy
import litellm

from config import load_env
from os_context import guidance
from winvm import LinuxVM, WinVM

# LiteLLM drops request params a given model doesn't accept (e.g. newer Anthropic
# models reject `temperature`) instead of erroring.
litellm.drop_params = True

# ============================================================================
# OS-specific configuration — the ONLY differences between Windows and Ubuntu:
#   the VM class, the shell tool name, and the per-OS guide (os_context.guidance,
#   sourced from control/guides/<os>.md).
# ============================================================================
VM_CLASS = {"win11": WinVM, "ubuntu": LinuxVM}
RUN_TOOL = {"win11": "run_powershell", "ubuntu": "run_bash"}


# ============================================================================
# Shared (OS-agnostic) input handling
# ============================================================================
KEY_ALIASES = {
    "enter": "ret", "return": "ret", "esc": "esc", "escape": "esc",
    "space": "spc", "tab": "tab", "backspace": "backspace",
    "del": "delete", "delete": "delete", "win": "meta_l", "super": "meta_l",
    "cmd": "meta_l", "meta": "meta_l", "up": "up", "down": "down",
    "left": "left", "right": "right", "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "shift": "shift", "home": "home", "end": "end",
    "pgup": "pgup", "pgdn": "pgdn",
}


def to_qcodes(combo: str):
    return [KEY_ALIASES.get(p.lower().strip(), p.lower().strip())
            for p in combo.split("-")]


SHOT = "/tmp/agent_shot.png"


class NextAction(dspy.Signature):
    """Drive a computer toward the task. Look at the screenshot and history,
    then choose exactly ONE next action. Take a screenshot is automatic each
    step, so just pick the action. Set done=true only when the task is fully
    complete (then `note` is your final report)."""

    guidance: str = dspy.InputField(desc="rules for operating this machine")
    task: str = dspy.InputField(desc="the goal to accomplish")
    history: str = dspy.InputField(desc="prior actions and their results")
    screenshot: dspy.Image = dspy.InputField(desc="the current screen")

    done: bool = dspy.OutputField(desc="true only if the task is fully complete")
    tool: str = dspy.OutputField(
        desc="left_click | double_click | type_text | key | run_powershell | run_bash")
    args: str = dspy.OutputField(
        desc='JSON args: {"x":N,"y":N} / {"text":"..."} / {"keys":"ctrl-l"} / {"script":"..."}')
    note: str = dspy.OutputField(desc="one short sentence: what you're doing, or the final report")


class NextActionA11y(dspy.Signature):
    """Drive a computer toward the task. In addition to the screenshot you get an
    accessibility tree: the on-screen elements with names and (sometimes) rects.
    Prefer `click_element` (by name) over guessing pixel coordinates. BUT if
    click_element reports it failed, or an element shows "no reliable position",
    FALL BACK: use left_click on the screenshot, or run_bash / keyboard. Do not
    repeat a failed click_element — switch methods. Choose exactly ONE next
    action; set done=true only when the task is complete (then `note` is the
    final report)."""

    guidance: str = dspy.InputField(desc="rules for operating this machine")
    task: str = dspy.InputField(desc="the goal to accomplish")
    history: str = dspy.InputField(desc="prior actions and their results")
    ui_tree: str = dspy.InputField(
        desc='actionable UI elements, one per line: index: "name" [role] rect=[x,y,w,h]')
    screenshot: dspy.Image = dspy.InputField(desc="the current screen")

    done: bool = dspy.OutputField(desc="true only if the task is fully complete")
    tool: str = dspy.OutputField(
        desc="click_element | left_click | double_click | type_text | key | "
             "run_bash | run_powershell")
    args: str = dspy.OutputField(
        desc='JSON: {"name":"Files"} (click_element) / {"text":".."} / {"keys":"ctrl-l"} '
             '/ {"script":".."} / {"x":N,"y":N}')
    note: str = dspy.OutputField(desc="one short sentence: what you're doing, or the final report")


def fmt_tree(els):
    if not els:
        return "(accessibility tree empty or unavailable)"
    lines = []
    for i, e in enumerate(els):
        pos = (f'rect={e["rect"]}' if e.get("clickable")
               else "(no reliable position — try click_element by name, else use "
                    "the screenshot with left_click)")
        lines.append(f'{i}: "{e["name"]}" [{e["role"]}] {pos}')
    return "\n".join(lines)


def execute(vm, target, tool, args):
    """Run one action against the VM; return a text observation."""
    if tool in ("run_powershell", "run_bash"):
        try:
            if target == "win11":
                return vm.powershell(args["script"]) or "(no output)"
            rc, out, err = vm.run(args["script"])
            return (out + err).strip() or "(no output)"
        except Exception as e:  # noqa: BLE001 - surface to the model
            return f"ERROR: {e}"
    try:
        if tool == "click_element":  # AT-SPI: click by element name (precise)
            ok, how = vm.click_element(name=args.get("name"), index=args.get("index"))
            vm.sleep(0.6)
            if ok:
                return f"clicked (via {how})"
            if how == "bogus":
                return ("could not click via accessibility (no usable action and a "
                        "bogus position) — FALL BACK: take the screenshot and use "
                        "left_click on the element, or use run_bash / keyboard")
            return ("no such element in the accessibility tree — FALL BACK to the "
                    "screenshot (left_click) or run_bash")
        if tool == "left_click":
            vm.click(int(args["x"]), int(args["y"]))
        elif tool == "double_click":
            vm.click(int(args["x"]), int(args["y"]), double=True)
        elif tool == "type_text":
            vm.type(args["text"])
        elif tool == "key":
            vm.key(*to_qcodes(args["keys"]))
        else:
            return f"unknown tool: {tool}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"
    vm.sleep(0.6)
    return "done (result visible in next screenshot)"


def make_lm(provider: str):
    """Build the DSPy LM (LiteLLM model string). Keys read from env."""
    if provider == "anthropic":
        model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
        return dspy.LM(f"anthropic/{model}",
                       api_key=os.getenv("ANTHROPIC_API_KEY"), max_tokens=4096)
    model = os.getenv("OPENAI_MODEL", "gpt-4o")   # openai or OpenAI-compatible
    kw = {"api_key": os.getenv("OPENAI_API_KEY"), "max_tokens": 4096}
    if os.getenv("OPENAI_BASE_URL"):
        kw["api_base"] = os.getenv("OPENAI_BASE_URL")
    return dspy.LM(f"openai/{model}", **kw)


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
    vm = VM_CLASS[target]()
    w, h = vm._resolution()  # noqa: SLF001 - prime + report screen size
    rules = guidance(target, w, h)

    if a11y:
        kind = "UIA" if target == "win11" else "AT-SPI"
        print(f"[a11y] enabling accessibility tree in guest ({kind})...")
        vm.ensure_a11y()
        decide = dspy.Predict(NextActionA11y)
    else:
        # Use the DSPy-optimized policy if one has been compiled (optimize.py).
        # Prefer a per-OS artifact (optimized_<target>.json); else a shared one.
        decide = dspy.Predict(NextAction)
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (f"optimized_{target}.json", "optimized_agent.json"):
            path = os.path.join(here, cand)
            if os.path.exists(path):
                decide.load(path)
                print(f"[loaded optimized policy: {cand}]")
                break

    print(f"[dspy | {provider} | {target}{' | a11y' if a11y else ''}]  task: {task}\n")
    history = "(none yet)"
    for step in range(40):
        vm.screenshot(SHOT)
        kw = dict(guidance=rules, task=task, history=history,
                  screenshot=dspy.Image(SHOT))
        if a11y:
            kw["ui_tree"] = fmt_tree(vm.ui_tree())
        pred = decide(**kw)
        print(f"[{step}] {pred.tool} {pred.args}  — {pred.note}")
        if str(pred.done).lower() == "true":
            break
        try:
            args = json.loads(pred.args or "{}")
        except json.JSONDecodeError:
            args = {}
        obs = execute(vm, target, pred.tool, args)
        history += f"\n{step}. {pred.tool} {pred.args} -> {obs[:300]}"
    vm.close()


if __name__ == "__main__":
    main()
