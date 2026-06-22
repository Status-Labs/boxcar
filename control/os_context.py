"""Shared OS context for the agents and the optimizer.

The per-OS "user guide" (control/guides/<os>.md) is the agent's domain knowledge:
how to log in, open apps reliably, run a shell, browse, where files live. Editing
those markdown files changes agent behavior — no code change needed. Both agents
(agent.py, agent_dspy.py) and the optimizer (optimize.py) build their OS guidance
from here, so there's a single source of truth per OS.
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_GUIDES = os.path.join(_HERE, "guides")
_FILE = {"win11": "windows.md", "ubuntu": "ubuntu.md"}


def load_guide(target: str) -> str:
    with open(os.path.join(_GUIDES, _FILE[target]), encoding="utf-8") as f:
        return f.read().strip()


def guidance(target: str, w: int, h: int) -> str:
    """The full OS-specific context string given to the model each step."""
    return (f"The screen is {w}x{h} pixels; coordinates are pixels from the "
            f"top-left. Base every action on the current screenshot.\n\n"
            f"{load_guide(target)}")
