"""Portable tool-calling loop.

Works against any provider that exposes tools (Ollama, Anthropic, OpenAI). Used
verbatim on cloud providers, where models pick tools reliably. On local 7B
models the router short-circuits most turns before this runs — see router.py
for why.

Capped at MAX_STEPS. A loop that can't finish in three tool calls is either
stuck or being driven by a model that doesn't understand the tools, and in both
cases another lap makes it worse, not better.
"""

from __future__ import annotations

import json

from ..llm.base import LLMProvider, LLMResult
from ..logging_setup import get_logger
from .tools import TOOL_SPECS, ToolContext, run_search

log = get_logger(__name__)

MAX_STEPS = 3


async def run_loop(
    messages: list[dict],
    system: str,
    provider: LLMProvider,
    ctx: ToolContext,
    tool_names: tuple[str, ...] = ("search_transcripts",),
) -> LLMResult:
    specs = [t for t in TOOL_SPECS if t["function"]["name"] in tool_names]
    convo = list(messages)
    last: LLMResult | None = None

    for step in range(MAX_STEPS):
        res = await provider.complete(convo, system=system, tools=specs, max_tokens=2048)
        last = res
        if not res.tool_calls:
            return res

        for call in res.tool_calls:
            log.info("agent.tool", step=step, tool=call.name, args=call.arguments)
            if call.name == "search_transcripts":
                observation = await run_search(call.arguments, ctx)
            else:
                # The loop only carries search; essay/artifact are routed, not
                # called mid-conversation, so a model asking for them here is
                # confused and should be told so plainly.
                observation = f"Tool '{call.name}' is not available in this context."
            convo.append({"role": "assistant", "content": res.text or f"[calling {call.name}]"})
            convo.append({"role": "user", "content": f"Tool result:\n{observation}"})

    log.warning("agent.loop_exhausted", steps=MAX_STEPS)
    return last or LLMResult("", provider.model, provider.name)


def tool_specs_json() -> str:
    return json.dumps(TOOL_SPECS, indent=2)
