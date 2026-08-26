"""Optional Claude Agent SDK backend.

The brief asks for the agent layer to be built on the Claude Agent SDK or Pi.
The same brief makes running the demo on local Ollama mandatory. Those two
requirements can't both be satisfied by one code path: the Agent SDK talks to
Anthropic's models, and there is no adapter that points it at a local Ollama
server.

Rather than pick one requirement and quietly drop the other, the agent layer is
defined by its *contract* — the tool specs in tools.py — and has two runners
against that contract:

  * agent/loop.py     portable, used for Ollama (and therefore the demo)
  * this module       Claude Agent SDK, used when USE_AGENT_SDK=true and the
                      provider is Anthropic

Same tools, same system prompt, same grounding gate downstream. The trade-off
is that we own ~60 lines of loop we'd otherwise get for free; the payoff is
that the local-model requirement isn't negotiable and neither is the SDK one.

Install with: pip install -r requirements-agentsdk.txt
"""

from __future__ import annotations

from ..llm.base import LLMResult, ProviderUnavailable
from ..logging_setup import get_logger
from .tools import ToolContext, run_search

log = get_logger(__name__)


def available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


async def run_sdk(messages: list[dict], system: str, ctx: ToolContext, model: str) -> LLMResult:
    if not available():
        raise ProviderUnavailable(
            "claude-agent-sdk is not installed (pip install -r requirements-agentsdk.txt)"
        )

    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, tool

    @tool("search_transcripts", "Search Lenny's Podcast transcripts for evidence.",
          {"query": str, "guest": str})
    async def _search(args):
        text = await run_search(args, ctx)
        return {"content": [{"type": "text", "text": text}]}

    opts = ClaudeAgentOptions(system_prompt=system, model=model, tools=[_search])

    prompt = "\n\n".join(f"{m['role']}: {m['content']}" for m in messages)
    chunks: list[str] = []
    async with ClaudeSDKClient(options=opts) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            for block in getattr(msg, "content", []) or []:
                if getattr(block, "type", None) == "text":
                    chunks.append(block.text)

    return LLMResult("".join(chunks), model, "anthropic", stop_reason="end_turn")
