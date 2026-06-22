#!/usr/bin/env python3
"""LangGraph version of the computer-use agent.

Same tools and WinVM execution as agent.py, but the agent loop is an explicit
LangGraph StateGraph:

    START -> llm -> (tool calls?) -> act -> llm -> ... -> END

  * llm node  — calls the model (bound to the tools) and appends its reply.
  * act node  — runs each tool call against the VM via run_tool(); screenshots
                are fed back as image messages so the model can see the result.
  * conditional edge — loop back to llm while the model keeps calling tools,
                else finish.

Provider-agnostic through LangChain's init_chat_model (Anthropic / OpenAI / any
OpenAI-compatible endpoint). Configure via control/.env (same vars as agent.py).

    pip install -r requirements.txt        # installs langgraph + langchain
    .venv/bin/python agent_graph.py "Open Notepad and write a haiku"
    .venv/bin/python agent_graph.py --provider openai "..."
"""
import base64
import os
import sys
from typing import Annotated, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent import TOOLS, run_tool          # reuse the shared tool schemas + executor
from backends import ToolCall
from config import load_env
from winvm import WinVM


class State(TypedDict):
    messages: Annotated[list, add_messages]


def _data_uri(path: str) -> str:
    return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()


def _text(content) -> str:
    """Flatten LangChain message content (str or content-block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    return str(content)


def build_app(vm, provider, model_name, **model_kwargs):
    model = init_chat_model(model_name, model_provider=provider, **model_kwargs)
    oai_tools = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": t["parameters"]}} for t in TOOLS]
    llm = model.bind_tools(oai_tools)

    def llm_node(state: State):
        return {"messages": [llm.invoke(state["messages"])]}

    def act_node(state: State):
        out = []
        for tc in state["messages"][-1].tool_calls:   # {name, args, id}
            obs = run_tool(vm, ToolCall(tc["id"], tc["name"], tc["args"]))
            out.append(ToolMessage(content=obs.text or "done", tool_call_id=tc["id"]))
            if obs.image_path:  # both providers accept images in a human turn
                out.append(HumanMessage(content=[
                    {"type": "text", "text": "Current screen:"},
                    {"type": "image_url", "image_url": {"url": _data_uri(obs.image_path)}},
                ]))
        return {"messages": out}

    def should_continue(state: State):
        return "act" if state["messages"][-1].tool_calls else END

    g = StateGraph(State)
    g.add_node("llm", llm_node)
    g.add_node("act", act_node)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", should_continue, {"act": "act", END: END})
    g.add_edge("act", "llm")
    return g.compile()


def main():
    load_env()
    argv = sys.argv[1:]
    provider = os.getenv("AGENT_PROVIDER", "anthropic")
    if argv and argv[0] == "--provider":
        provider, argv = argv[1], argv[2:]
    task = argv[0] if argv else "Take a screenshot and describe what's on screen."

    model_name = (os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
                  if provider == "anthropic"
                  else os.getenv("OPENAI_MODEL", "gpt-4o"))
    model_kwargs = {}
    if provider == "openai" and os.getenv("OPENAI_BASE_URL"):
        model_kwargs["base_url"] = os.getenv("OPENAI_BASE_URL")

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

    app = build_app(vm, provider, model_name, **model_kwargs)
    print(f"[langgraph | {provider}:{model_name}]  {task}\n")
    init = {"messages": [SystemMessage(content=system), HumanMessage(content=task)]}
    for event in app.stream(init, {"recursion_limit": 100}, stream_mode="updates"):
        for node, update in event.items():
            for msg in update.get("messages", []):
                if node == "llm":
                    txt = _text(msg.content)
                    if txt:
                        print(f"\nLLM: {txt}")
                    for tc in getattr(msg, "tool_calls", None) or []:
                        print(f"  -> {tc['name']}({tc['args']})")
    vm.close()


if __name__ == "__main__":
    main()
