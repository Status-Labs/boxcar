"""Pluggable LLM backends for the computer-use agent.

A backend hides each provider's wire format behind one method, `step()`, which
takes the observations from the previous tool calls and returns the model's next
turn (text + tool calls + done flag). The agent loop in agent.py is identical
regardless of provider.

Supported out of the box:
  * anthropic  — Anthropic Messages API (default model claude-opus-4-8)
  * openai     — OpenAI Chat Completions API, and ANY OpenAI-compatible endpoint
                 (Ollama, Groq, Together, OpenRouter, vLLM, LM Studio, ...) via
                 OPENAI_BASE_URL + OPENAI_MODEL.

Tools are defined once in a neutral shape: {name, description, parameters}
where `parameters` is a JSON Schema object. Each backend translates that to its
own tool format.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass


@dataclass
class ToolCall:
    call_id: str
    name: str
    args: dict


@dataclass
class ToolObservation:
    """Result of running one tool, fed back to the model."""
    call_id: str
    text: str | None = None
    image_path: str | None = None


def _data_uri(path: str) -> str:
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return f"data:image/png;base64,{b64}"


# ============================================================= Anthropic
class AnthropicBackend:
    def __init__(self, system, tools, task, model):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.system = system
        self.tools = [{"name": t["name"], "description": t["description"],
                       "input_schema": t["parameters"]} for t in tools]
        self.messages = [{"role": "user", "content": task}]

    def step(self, observations):
        if observations is not None:
            blocks = []
            for obs in observations:
                content = []
                if obs.text:
                    content.append({"type": "text", "text": obs.text})
                if obs.image_path:
                    content.append({"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": base64.b64encode(open(obs.image_path, "rb").read()).decode()}})
                blocks.append({"type": "tool_result", "tool_use_id": obs.call_id,
                               "content": content or [{"type": "text", "text": "done"}]})
            self.messages.append({"role": "user", "content": blocks})

        resp = self.client.messages.create(
            model=self.model, max_tokens=8192,
            thinking={"type": "adaptive"},
            system=self.system, tools=self.tools, messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, b.input)
                 for b in resp.content if b.type == "tool_use"]
        return text, calls, resp.stop_reason != "tool_use"


# ============================================================= OpenAI / compatible
class OpenAIBackend:
    def __init__(self, system, tools, task, model, base_url=None):
        import openai
        self.client = openai.OpenAI(base_url=base_url) if base_url else openai.OpenAI()
        self.model = model
        self.tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["parameters"]}} for t in tools]
        self.messages = [{"role": "system", "content": system},
                         {"role": "user", "content": task}]

    def step(self, observations):
        if observations is not None:
            images = []
            for obs in observations:
                self.messages.append({"role": "tool", "tool_call_id": obs.call_id,
                                      "content": obs.text or "done"})
                if obs.image_path:
                    images.append(obs.image_path)
            if images:  # tool messages can't carry images; send them in a user turn
                parts = [{"type": "text", "text": "Current screen:"}]
                for p in images:
                    parts.append({"type": "image_url", "image_url": {"url": _data_uri(p)}})
                self.messages.append({"role": "user", "content": parts})

        resp = self.client.chat.completions.create(
            model=self.model, messages=self.messages,
            tools=self.tools, tool_choice="auto",
        )
        msg = resp.choices[0].message
        assistant = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant["tool_calls"] = [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            } for tc in msg.tool_calls]
        self.messages.append(assistant)

        calls = [ToolCall(tc.id, tc.function.name,
                          json.loads(tc.function.arguments or "{}"))
                 for tc in (msg.tool_calls or [])]
        return msg.content or "", calls, not calls


def make_backend(provider, system, tools, task):
    if provider == "anthropic":
        return AnthropicBackend(system, tools, task,
                                os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8"))
    if provider == "openai":
        return OpenAIBackend(system, tools, task,
                             os.getenv("OPENAI_MODEL", "gpt-4o"),
                             os.getenv("OPENAI_BASE_URL"))
    raise SystemExit(f"unknown provider: {provider!r} (use 'anthropic' or 'openai')")
