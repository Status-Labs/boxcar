#!/usr/bin/env python3
"""The computer-use *policy*: the DSPy primitives shared by every caller.

This is the OS-agnostic core that `agent_dspy.py` (the CLI), `runner.py` (the
look->act loop), `optimize.py` (the compile-time optimizer), and `evals.py` (the
end-to-end benchmark) all build on. Keeping it in one module means there is a
single definition of:

  * the decision Signatures (`NextAction`, `NextActionA11y`),
  * how a chosen action is executed against a VM (`execute`),
  * how the LM is constructed per provider (`make_lm`),
  * how the (optionally optimized) decider is built (`build_decider`).

DSPy talks to any provider through LiteLLM, so the model string is
"<provider>/<model>" (e.g. "openai/gpt-5", "anthropic/claude-opus-4-8").
"""
import json
import os

import dspy
import litellm

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

SHOT = "/tmp/agent_shot.png"


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


def _downscale(path, maxw):
    """Shrink the screenshot to <= maxw px wide (fewer image tokens). Best-effort."""
    try:
        from PIL import Image
        img = Image.open(path)
        if img.width > maxw:
            h = round(img.height * maxw / img.width)
            img.resize((maxw, h)).save(path)
    except Exception:  # noqa: BLE001
        pass


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


def _is_reasoning(model: str) -> bool:
    """GPT-5 family and o-series are reasoning models (different API rules)."""
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


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
    if _is_reasoning(model):
        # Reasoning models: temperature must be 1.0, and the token budget must be
        # large (reasoning tokens count toward it). reasoning_effort tunes depth
        # vs. speed/cost (minimal | low | medium | high).
        kw["temperature"] = 1.0
        kw["max_tokens"] = max(16000, int(os.getenv("OPENAI_MAX_TOKENS", "16000")))
        kw["reasoning_effort"] = os.getenv("OPENAI_REASONING_EFFORT", "low")
    return dspy.LM(f"openai/{model}", **kw)


def build_decider(target: str, a11y: bool = False, optimized: bool = True):
    """Construct the per-step decider (`dspy.Predict`), loading a compiled policy
    if one exists. Returns (decide, label) where label notes what was loaded.

    The a11y variant has no optimized artifact (it uses a different Signature);
    for the vision policy we prefer a per-OS artifact (optimized_<target>.json)
    and fall back to a shared one (optimized_agent.json)."""
    if a11y:
        return dspy.Predict(NextActionA11y), "a11y (uncompiled)"
    decide = dspy.Predict(NextAction)
    if not optimized:
        return decide, "uncompiled"
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (f"optimized_{target}.json", "optimized_agent.json"):
        path = os.path.join(here, cand)
        if os.path.exists(path):
            decide.load(path)
            return decide, f"compiled: {cand}"
    return decide, "uncompiled (no optimized_*.json)"


def parse_args(raw: str) -> dict:
    """Best-effort parse of the model's JSON args field (never raises)."""
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
