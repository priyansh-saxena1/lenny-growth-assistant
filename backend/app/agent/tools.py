"""Tool surface exposed to the model.

Three tools, deliberately. Every extra tool is another thing a 7B local model
can pick wrong, and the demo has to run on a 7B local model. Each maps to one
skill with a hard boundary: search returns evidence and never prose, the essay
skill never retrieves on its own, the artifact skill never invents facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rag.retriever import retrieve
from ..rag.store import Hit


@dataclass
class ToolContext:
    """Carried across a turn so tools can share retrieved evidence.

    The essay and artifact skills need the same sources the answer used;
    re-retrieving would produce a subtly different set and break citations.
    """

    hits: list[Hit] = field(default_factory=list)
    session_id: str | None = None
    provider_name: str = ""

    def merge_hits(self, new: list[Hit]) -> None:
        seen = {h.chunk_id for h in self.hits}
        self.hits.extend(h for h in new if h.chunk_id not in seen)


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_transcripts",
            "description": (
                "Search Lenny's Podcast transcripts for evidence. Call this before "
                "answering any question about product, growth, hiring or strategy. "
                "Returns numbered sources you must cite as [1], [2]."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A focused search query. Rewrite follow-ups to be self-contained.",
                    },
                    "guest": {
                        "type": "string",
                        "description": "Optional guest name to restrict the search to.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_ship30_essay",
            "description": (
                "Write a ~1250 word Ship 30 for 30 style essay grounded in the "
                "transcripts. Use only when the user asks for an essay, article, "
                "post or long-form write-up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "What the essay is about."},
                    "angle": {
                        "type": "string",
                        "description": "Optional specific argument or point of view to take.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_artifact",
            "description": (
                "Render a standalone Markdown document or HTML/CSS page from the "
                "current conversation, shown in the side-by-side viewer. Use when "
                "the user asks for a doc, one-pager, checklist, table, or web page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["markdown", "html"]},
                    "title": {"type": "string"},
                    "brief": {
                        "type": "string",
                        "description": "What the artifact should contain.",
                    },
                },
                "required": ["kind", "title", "brief"],
            },
        },
    },
]


def format_sources(hits: list[Hit]) -> str:
    """Numbered evidence block. The numbers here are the [n] the model must cite."""
    out = []
    for i, h in enumerate(hits, start=1):
        out.append(
            f"[{i}] {h.guest} — \"{h.title}\" ({h.start_ts}–{h.end_ts})\n{h.text.strip()}"
        )
    return "\n\n".join(out)


async def run_search(args: dict[str, Any], ctx: ToolContext) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "search_transcripts requires a non-empty query."
    if args.get("guest"):
        query = f"{args['guest']} {query}"
    res = await retrieve(query)
    if not res.hits:
        return (
            "No transcript passages matched. Tell the user the archive doesn't "
            "cover this rather than answering from general knowledge."
        )
    ctx.merge_hits(res.hits)
    return format_sources(ctx.hits)
