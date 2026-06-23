#!/usr/bin/env python3
"""DSPy optimizer pass for the computer-use agent's NextAction policy.

The agent's decision is a `dspy.Predict(NextAction)` (see agent_dspy.py). Because
it's a DSPy program, it can be *compiled*: given a labeled set of real
screenshots -> the correct action for common tasks, and an args-level metric, an
optimizer tunes the program to pick better actions.

Two optimizers (pick with --method):
  * bootstrap : dspy.BootstrapFewShot — selects few-shot demos. Effective but the
    demos embed screenshots, so each agent call then carries extra images.
  * mipro     : dspy.MIPROv2 with max_*_demos=0 — optimizes only the *instruction*
    (the prompt). No demo images => no per-call overhead. Best fit for a vision
    agent. (Default.)

Dataset: control/optim/screens/*.png (real captures) labeled below. The metric
checks the chosen *tool* AND, for keyboard/shell actions, the args (which key /
that a script is present) — so it rewards the reliable method (e.g. ctrl-l to
focus the address bar, super to open an app) over brittle coordinate clicks,
which is exactly where the un-tuned policy slips.

Run:
    cd control
    .venv/bin/python optimize.py                  # MIPROv2 (instruction-only)
    .venv/bin/python optimize.py --method bootstrap
    .venv/bin/python optimize.py --provider openai --method mipro
"""
import json
import os
import sys

import dspy

from agent_dspy import NextAction, make_lm, to_qcodes
from config import load_env
from os_context import guidance

HERE = os.path.dirname(os.path.abspath(__file__))
SCREENS = os.path.join(HERE, "optim", "screens")

# Captured screens are 1280x800; guidance reports that resolution to the model.
W, H = 1280, 800
G = {"ubuntu": guidance("ubuntu", W, H), "win11": guidance("win11", W, H)}


def ex(screen, target, task, acceptable, gold_key=None):
    """One labeled decision: (guidance, task, history, screenshot) -> action.
    `target` is kept as metadata so the dataset can be split per-OS."""
    e = dspy.Example(
        guidance=G[target], task=task, history="(none yet)",
        screenshot=dspy.Image(os.path.join(SCREENS, screen)),
        acceptable=acceptable, gold_key=gold_key, target=target,
    )
    return e.with_inputs("guidance", "task", "history", "screenshot")


# ---- Labeled dataset: common tasks across real screens ----------------------
# Reliability rules we want the policy to learn:
#   * scriptable work          -> the shell tool (run_bash / run_powershell)
#   * open an app on the desktop-> press 'super' (GNOME) / 'win-r' (Windows)
#   * browser navigation/tabs  -> keyboard shortcuts, not coordinate clicks
#   * login screens            -> click the user / type the password
DATA = [
    # Ubuntu desktop — scriptable common tasks -> run_bash
    ex("ubuntu_desktop.png", "ubuntu", "Report the installed Node.js version.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Install the ripgrep package.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Create ~/Desktop/notes.txt with the date.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Show the current disk usage.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "List the running processes.", ["run_bash"]),
    # Ubuntu desktop — open an app -> press super (Activities)
    ex("ubuntu_desktop.png", "ubuntu", "Open Google Chrome.", ["key"], "super"),
    ex("ubuntu_desktop.png", "ubuntu", "Open the Files file manager.", ["key"], "super"),
    # Ubuntu Chrome — browser tasks -> keyboard shortcuts
    ex("chrome_page.png", "ubuntu", "Navigate to https://example.com.", ["key"], "ctrl-l"),
    ex("chrome_page.png", "ubuntu", "Open a new browser tab.", ["key"], "ctrl-t"),
    ex("chrome_page.png", "ubuntu", "Find the word 'kernel' on this page.", ["key"], "ctrl-f"),
    # Windows desktop (PowerShell) — scriptable common tasks -> run_powershell
    ex("windows_desktop.png", "win11", "Report the installed Node.js version.", ["run_powershell"]),
    ex("windows_desktop.png", "win11", "Create a Desktop file with the date.", ["run_powershell"]),
    ex("windows_desktop.png", "win11", "List the installed programs.", ["run_powershell"]),
    # Windows Chrome — browser tasks -> keyboard shortcuts
    ex("chrome_win.png", "win11", "Navigate to https://wikipedia.org.", ["key"], "ctrl-l"),
    ex("chrome_win.png", "win11", "Open a new browser tab.", ["key"], "ctrl-t"),
    # Complex / multi-step tasks — the right *first* action is still the shell
    # (write+run, install+verify, etc.) or a keyboard shortcut.
    ex("ubuntu_desktop.png", "ubuntu", "Write and run a Node Fibonacci script.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Install git if it is missing.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Update all system packages.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Make a Python venv and install requests.", ["run_bash"]),
    ex("ubuntu_desktop.png", "ubuntu", "Fetch a YouTube video's auto-subtitles.", ["run_bash"]),
    ex("chrome_page.png", "ubuntu", "Bookmark this page.", ["key"], "ctrl-d"),
    ex("chrome_page.png", "ubuntu", "Open the browser dev tools.", ["key"], "f12"),
    ex("windows_desktop.png", "win11", "Write and run a Node script.", ["run_powershell"]),
    ex("windows_desktop.png", "win11", "Report free space on the C: drive.", ["run_powershell"]),
    ex("windows_desktop.png", "win11", "List largest files in the profile.", ["run_powershell"]),
    ex("chrome_win.png", "win11", "Bookmark this page.", ["key"], "ctrl-d"),
    ex("chrome_win.png", "win11", "Open the browser dev tools.", ["key"], "f12"),
    # Login screens -> click the user / type the password
    ex("ubuntu_login.png", "ubuntu", "Log in to the machine.", ["left_click", "type_text"]),
    ex("windows_login.png", "win11", "Sign in to Windows.", ["left_click", "type_text"]),
]


def split(data):
    """Interleaved 1/3 dev split (keeps task-type variety in both)."""
    dev = data[::3]
    return [e for e in data if e not in dev], dev


def metric(example, pred, trace=None):
    """1.0 if the action is right: correct tool, and for shell/key the args too
    (script present; the pressed key matches the gold shortcut)."""
    tool = (getattr(pred, "tool", "") or "").strip()
    if tool not in example.acceptable:
        return False
    if tool in ("run_bash", "run_powershell"):
        try:
            return bool(json.loads(pred.args or "{}").get("script", "").strip())
        except (json.JSONDecodeError, TypeError):
            return False
    if tool == "key" and example.gold_key:
        try:
            keys = json.loads(pred.args or "{}").get("keys", "")
        except (json.JSONDecodeError, TypeError):
            return False
        return frozenset(to_qcodes(keys)) == frozenset(to_qcodes(example.gold_key))
    return True


def run_one(target, method, eval_only):
    """Optimize (or just evaluate) the policy for ONE OS, saving a per-OS artifact
    so Windows and Ubuntu get independently-tuned programs."""
    data = [e for e in DATA if e.target == target]
    train, dev = split(data)
    evaluate = dspy.Evaluate(devset=dev, metric=metric,
                             num_threads=1, display_progress=False)
    base = dspy.Predict(NextAction)
    print(f"\n[{target}] train={len(train)} dev={len(dev)}  baseline dev:",
          evaluate(base))
    if eval_only:
        return

    if method == "bootstrap":
        opt = dspy.BootstrapFewShot(metric=metric, max_bootstrapped_demos=2,
                                    max_labeled_demos=2)
        tuned = opt.compile(student=dspy.Predict(NextAction), trainset=train)
    else:  # mipro — instruction-only (max_*_demos=0): no demo images per call
        opt = dspy.MIPROv2(metric=metric, auto="light", num_threads=1)
        tuned = opt.compile(student=dspy.Predict(NextAction),
                            trainset=train, valset=dev,
                            max_bootstrapped_demos=0, max_labeled_demos=0,
                            requires_permission_to_run=False)
    print(f"[{target}] optimized dev:", evaluate(tuned))
    path = os.path.join(HERE, f"optimized_{target}.json")
    tuned.save(path)
    print(f"[{target}] saved -> {os.path.basename(path)}")


def main():
    load_env()
    argv = sys.argv[1:]
    provider = os.getenv("AGENT_PROVIDER", "anthropic")
    method, target, eval_only = "mipro", "all", False
    while argv:
        if argv[0] == "--provider":
            provider, argv = argv[1], argv[2:]
        elif argv[0] == "--method":
            method, argv = argv[1], argv[2:]
        elif argv[0] == "--target":
            target, argv = argv[1], argv[2:]
        elif argv[0] == "--eval-only":
            eval_only, argv = True, argv[1:]
        else:
            argv = argv[1:]
    dspy.configure(lm=make_lm(provider))

    # Per-OS: optimize Windows and Ubuntu independently (own dataset + artifact).
    targets = [target] if target in ("win11", "ubuntu") else ["ubuntu", "win11"]
    print(f"[optimize | {provider} | {method}]  targets={targets}")
    for t in targets:
        run_one(t, method, eval_only)


if __name__ == "__main__":
    main()
