#!/usr/bin/env python3
"""Drive a Windows 11 or Ubuntu VM with an LLM (provider-agnostic loop).

The LLM gets tools that wrap the VM — see the screen (screenshot), move/click the
mouse, type, press keys, and run a shell (PowerShell on Windows, bash on Ubuntu).
It loops: look at a screenshot -> act -> look again, until the task is done.

Run (VM must be booted / spawned):
    # Windows (default)
    .venv/bin/python agent.py "Open Notepad and write a haiku, save to Desktop"
    # Ubuntu
    .venv/bin/python agent.py --target ubuntu "Open Chrome and go to wikipedia.org"

Point at a specific spawned instance via its printed env, e.g.:
    VM_SSH_PORT=2222 VM_QMP_SOCK=vms/ubuntu/clones/x-qmp.sock \\
      .venv/bin/python agent.py --target ubuntu "..."

Provider: --provider anthropic|openai (or AGENT_PROVIDER in .env).
"""
import os
import sys

from backends import ToolObservation, make_backend
from config import load_env
from os_context import guidance
from winvm import LinuxVM, WinVM

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


# Shared GUI tools (QMP) — identical on both OSes.
GUI_TOOLS = [
    {"name": "screenshot",
     "description": "Capture the current screen and return it as an image.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "left_click",
     "description": "Move the mouse to (x, y) in screen pixels and left-click.",
     "parameters": {"type": "object", "properties": {
         "x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},
    {"name": "double_click",
     "description": "Double-click at (x, y) in screen pixels.",
     "parameters": {"type": "object", "properties": {
         "x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},
    {"name": "type_text",
     "description": "Type a string at the current focus.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string"}}, "required": ["text"]}},
    {"name": "key",
     "description": ("Press a key or chord. Join modifiers with '-', e.g. "
                     "'enter', 'ctrl-c', 'alt-tab', 'super'."),
     "parameters": {"type": "object", "properties": {
         "keys": {"type": "string"}}, "required": ["keys"]}},
]

# ============================================================================
# OS-specific configuration — the ONLY Windows-vs-Ubuntu differences:
#   VM class, the shell tool (PowerShell vs bash), and the system prompt below.
# ============================================================================
VM_CLASS = {"win11": WinVM, "ubuntu": LinuxVM}

RUN_TOOL = {
    "win11": {"name": "run_powershell",
              "description": "Run a PowerShell script inside Windows over SSH and "
                             "return its output."},
    "ubuntu": {"name": "run_bash",
               "description": "Run a bash command inside Ubuntu over SSH and return "
                              "its output. For root, prefix: echo user | sudo -S ..."},
}

SHOT = "/tmp/agent_shot.png"


def system_prompt(target, w, h):
    # OS knowledge comes from the shared guide (control/guides/<os>.md); here we
    # add only the loop discipline specific to this tool-calling agent.
    return (
        f"You are operating a {'Windows 11' if target == 'win11' else 'Ubuntu'} "
        "VM through tools. ALWAYS call screenshot first to see the current "
        "screen, and again after each GUI action to confirm the result — never "
        "act blindly. When the task is complete, stop and briefly report what "
        "you did.\n\n" + guidance(target, w, h))


def run_tool(vm, call) -> ToolObservation:
    name, args = call.name, call.args
    if name == "screenshot":
        vm.screenshot(SHOT)
        return ToolObservation(call.call_id, "Here is the screen:", SHOT)
    if name in ("run_powershell", "run_bash"):
        try:
            if name == "run_powershell":
                out = vm.powershell(args["script"])
            else:
                rc, o, e = vm.run(args["script"])
                out = (o + e).strip() or "(no output)"
            return ToolObservation(call.call_id, out or "(no output)")
        except Exception as e:  # noqa: BLE001 - surface to the model
            return ToolObservation(call.call_id, f"ERROR: {e}")
    if name == "left_click":
        vm.click(args["x"], args["y"])
    elif name == "double_click":
        vm.click(args["x"], args["y"], double=True)
    elif name == "type_text":
        vm.type(args["text"])
    elif name == "key":
        vm.key(*to_qcodes(args["keys"]))
    else:
        return ToolObservation(call.call_id, f"unknown tool: {name}")
    vm.sleep(0.6)
    vm.screenshot(SHOT)
    return ToolObservation(call.call_id, "Done. Screen now:", SHOT)


def main():
    load_env()
    argv = sys.argv[1:]
    provider = os.getenv("AGENT_PROVIDER", "anthropic")
    target = os.getenv("AGENT_TARGET", "win11")
    while argv and argv[0] in ("--provider", "--target"):
        if argv[0] == "--provider":
            provider, argv = argv[1], argv[2:]
        else:
            target, argv = argv[1], argv[2:]
    if target not in VM_CLASS:
        raise SystemExit(f"unknown --target {target!r} (use win11 or ubuntu)")
    task = argv[0] if argv else "Take a screenshot and describe what's on screen."

    vm = VM_CLASS[target]()
    w, h = vm._resolution()  # noqa: SLF001 - prime + report screen size to the model
    tools = GUI_TOOLS + [{
        "name": RUN_TOOL[target]["name"],
        "description": RUN_TOOL[target]["description"],
        "parameters": {"type": "object", "properties": {
            "script": {"type": "string"}}, "required": ["script"]}}]

    print(f"[provider: {provider} | target: {target}]  task: {task}\n")
    backend = make_backend(provider, system_prompt(target, w, h), tools, task)

    observations = None
    while True:
        text, calls, done = backend.step(observations)
        if text:
            print(f"\nLLM: {text}")
        for c in calls:
            print(f"  -> {c.name}({c.args})")
        if done or not calls:
            break
        observations = [run_tool(vm, c) for c in calls]

    vm.close()


if __name__ == "__main__":
    main()
