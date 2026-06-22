#!/usr/bin/env python3
"""Drive the Windows 11 VM with an LLM (provider-agnostic computer-use loop).

The LLM gets tools that wrap WinVM — see the screen (screenshot), move/click the
mouse, type, press keys, and run PowerShell in the guest. It loops: look at a
screenshot -> act -> look again, until the task is done. Works with Anthropic,
OpenAI, or any OpenAI-compatible endpoint.

Setup:
    cd control
    python3 -m venv --without-pip .venv
    .venv/bin/python <(curl -sS https://bootstrap.pypa.io/get-pip.py)
    .venv/bin/python -m pip install -r requirements.txt

Run (VM must be booted — ./win11.sh):
    # Anthropic (default)
    export ANTHROPIC_API_KEY=sk-ant-...
    .venv/bin/python agent.py "Open Notepad and write a haiku, save to Desktop"

    # OpenAI
    export OPENAI_API_KEY=sk-...
    .venv/bin/python agent.py --provider openai "..."

    # Any OpenAI-compatible endpoint (e.g. local Ollama with a vision model)
    OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_MODEL=llama3.2-vision \\
      .venv/bin/python agent.py --provider openai "..."

Model overrides: ANTHROPIC_MODEL (default claude-opus-4-8), OPENAI_MODEL (default gpt-4o).
"""
import os
import sys

from backends import ToolObservation, make_backend
from config import load_env
from winvm import WinVM

# Friendly key names -> QEMU qcodes (for the `key` tool).
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


# Neutral tool definitions: {name, description, parameters (JSON Schema)}.
TOOLS = [
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
                     "'enter', 'ctrl-c', 'alt-tab', 'win-r'."),
     "parameters": {"type": "object", "properties": {
         "keys": {"type": "string"}}, "required": ["keys"]}},
    {"name": "run_powershell",
     "description": ("Run a PowerShell script inside Windows over SSH and return "
                     "its output. Prefer this for file ops, installing software, "
                     "or anything scriptable — faster than driving the GUI."),
     "parameters": {"type": "object", "properties": {
         "script": {"type": "string"}}, "required": ["script"]}},
]

SHOT = "/tmp/agent_shot.png"


def run_tool(vm: WinVM, call) -> ToolObservation:
    """Execute one tool call; return what the model should observe."""
    name, args = call.name, call.args
    if name == "screenshot":
        vm.screenshot(SHOT)
        return ToolObservation(call.call_id, "Here is the screen:", SHOT)
    if name == "run_powershell":
        try:
            out = vm.powershell(args["script"])  # raises on non-zero exit
            return ToolObservation(call.call_id, out or "(no output)")
        except Exception as e:  # noqa: BLE001 - surface the error to the model
            return ToolObservation(call.call_id, f"ERROR: {e}")
    # GUI action tools
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
    load_env()  # pull control/.env into the environment
    argv = sys.argv[1:]
    provider = os.getenv("AGENT_PROVIDER", "anthropic")
    if argv and argv[0] == "--provider":
        provider, argv = argv[1], argv[2:]
    task = argv[0] if argv else "Take a screenshot and describe what's on screen."

    vm = WinVM()
    w, h = vm._resolution()  # noqa: SLF001 - prime + report screen size to the model
    system = (
        "You are operating a Windows 11 virtual machine through tools. "
        f"The screen is {w}x{h} pixels; coordinates are pixels from the top-left. "
        "ALWAYS call the screenshot tool first to see the current screen, and "
        "again after each GUI action to confirm the result — never act blindly. "
        "If you see a lock or sign-in screen, click it, type the password 'user' "
        "and press enter. "
        "Prefer run_powershell for file operations, installing software, or "
        "anything scriptable; use the mouse/keyboard tools only for GUI-only "
        "steps. Installed CLI tools you can call via run_powershell: node, npm, "
        "git, choco (install more), and yt-dlp (download video info and "
        "subtitles/transcripts). For a YouTube transcript, use yt-dlp (e.g. "
        "`yt-dlp --skip-download --write-auto-subs --sub-langs en --sub-format "
        "vtt -o <path> <url>`) rather than scraping the page. The .vtt holds "
        "timestamps and inline <...> tags — for clean text, drop lines "
        "containing '-->', strip <...> tags, and dedup repeated lines. "
        "NOTE: programs launched via run_powershell run in a background "
        "session and their WINDOWS DO NOT APPEAR on the desktop — to open a "
        "visible window (File Explorer, an app), use the GUI tools (e.g. win-r "
        "then type the path/command, or win-e), not run_powershell. "
        "When browsing in Chrome, press ctrl-l to focus the address bar before "
        "typing a URL (more reliable than clicking it), then type the full URL "
        "and press enter. "
        "The logged-in user 'user' is an administrator. When the task is "
        "complete, stop and briefly report what you did."
    )

    print(f"[provider: {provider}]  task: {task}\n")
    backend = make_backend(provider, system, TOOLS, task)

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
