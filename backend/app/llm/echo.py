"""Deterministic stub provider.

Not a real model. It exists so `pytest` and `make eval` run on a laptop with no
Ollama, no keys and no network — the retrieval, routing, grounding and artifact
layers are all testable without a language model in the loop. The UI shows a
warning badge when this is selected so nobody mistakes it for a demo.
"""

from __future__ import annotations

import hashlib
import json
import re

from .base import LLMResult, ProviderHealth, ToolCall


class EchoProvider:
    name = "echo"
    model = "echo-deterministic"
    supports_tools = True

    def __init__(self, scripted: list[LLMResult] | None = None):
        # Tests inject a script; otherwise we synthesise a grounded-looking answer
        # from whatever context was passed so the grounding gate has something real
        # to score.
        self.scripted = list(scripted or [])

    async def complete(self, messages, system=None, max_tokens=2048, temperature=0.2, tools=None):
        if self.scripted:
            return self.scripted.pop(0)

        ctx = "\n".join(m["content"] for m in messages if m.get("role") == "user")
        # Pull the first two [n] source blocks out of the prompt and quote a line
        # from each. Deterministic given the same context.
        blocks = re.findall(r"\[(\d+)\]\s*(.+?)(?=\n\[\d+\]|\Z)", ctx, flags=re.S)
        if not blocks:
            return LLMResult("I don't have transcript material covering that.", self.model, self.name)
        parts = []
        for n, body in blocks[:2]:
            sent = next((s.strip() for s in re.split(r"(?<=[.!?])\s", body) if len(s.strip()) > 40), body[:160])
            parts.append(f"{sent} [{n}]")
        return LLMResult(" ".join(parts), self.model, self.name, prompt_tokens=len(ctx) // 4)

    async def health(self):
        return ProviderHealth(self.name, True, self.model, "stub provider — not a real model", 0)

    @staticmethod
    def tool_call(name: str, **args) -> LLMResult:
        h = hashlib.md5(json.dumps(args, sort_keys=True).encode()).hexdigest()[:8]
        return LLMResult("", "echo-deterministic", "echo",
                         tool_calls=[ToolCall(id=h, name=name, arguments=args)],
                         stop_reason="tool_use")
