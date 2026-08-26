"""Routing.

A full tool-calling loop on a 7B local model picks the wrong skill often enough
that the demo would be a coin flip — in early testing qwen2.5:7b called
write_ship30_essay for "what is founder mode" roughly one time in four, because
"write" appears in the tool description and the model over-weights it.

So: cheap deterministic rules catch the unambiguous cases (which is most real
traffic), and only genuinely ambiguous queries cost an LLM classification call.
The classifier is constrained to a single token-ish JSON object and defaults to
`answer` on any parse failure, because answering a question when the user wanted
an essay is a much smaller failure than the reverse.

The full tool-calling loop still exists (agent/loop.py) and is used verbatim on
cloud providers, where it's reliable. `AGENT_MODE=loop` forces it everywhere.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..llm.base import LLMProvider
from ..logging_setup import get_logger

log = get_logger(__name__)

ESSAY_RE = re.compile(
    r"\b(ship\s*30|essay|blog\s*post|article|long[- ]form|newsletter|write\s+(me\s+)?a\s+"
    r"(post|piece|write[- ]?up))\b",
    re.I,
)
ARTIFACT_RE = re.compile(
    r"\b(artifact|one[- ]pager|onepager|landing\s*page|html|web\s*page|webpage|"
    r"css|render|checklist|cheat\s*sheet|template|markdown\s+(doc|document|file)|"
    r"make\s+me\s+a\s+(doc|table|diagram))\b",
    re.I,
)
HTML_RE = re.compile(r"\b(html|css|web\s*page|webpage|landing\s*page|styled)\b", re.I)

CLASSIFY_SYSTEM = """You classify a user request into exactly one route.

answer   - a question to be answered from podcast transcripts
essay    - a request for a long-form essay, article or blog post
artifact - a request for a rendered document, page, table or checklist

Reply with only JSON: {"route": "answer"} — no prose, no markdown."""


@dataclass
class Route:
    name: str            # answer | essay | artifact
    args: dict
    decided_by: str      # rule | llm | default


def rule_route(query: str) -> Route | None:
    q = query.strip()
    if ESSAY_RE.search(q):
        return Route("essay", {"topic": q}, "rule")
    if ARTIFACT_RE.search(q):
        kind = "html" if HTML_RE.search(q) else "markdown"
        return Route("artifact", {"kind": kind, "title": _title_from(q), "brief": q}, "rule")
    # A plain question mark with no artifact/essay language is an answer. This
    # covers the large majority of traffic without touching a model.
    if "?" in q or re.match(r"^(what|how|why|who|when|where|which|does|do|is|are|can|should)\b", q, re.I):
        return Route("answer", {"query": q}, "rule")
    return None


async def classify(query: str, provider: LLMProvider) -> Route:
    hit = rule_route(query)
    if hit:
        return hit
    try:
        res = await provider.complete(
            [{"role": "user", "content": query[:1000]}],
            system=CLASSIFY_SYSTEM,
            max_tokens=32,
            temperature=0.0,
        )
        m = re.search(r'\{.*?\}', res.text, re.S)
        name = json.loads(m.group(0))["route"] if m else "answer"
        if name not in ("answer", "essay", "artifact"):
            name = "answer"
    except Exception as exc:
        log.warning("router.classify_failed", error=str(exc))
        return Route("answer", {"query": query}, "default")

    if name == "essay":
        return Route("essay", {"topic": query}, "llm")
    if name == "artifact":
        kind = "html" if HTML_RE.search(query) else "markdown"
        return Route("artifact", {"kind": kind, "title": _title_from(query), "brief": query}, "llm")
    return Route("answer", {"query": query}, "llm")


def _title_from(q: str) -> str:
    t = re.sub(r"^(?:please\s+)?(?:make|create|write|build|give\s+me|generate)\s+(?:me\s+)?(?:an?|the)?\b\s*", "", q.strip(), flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" .?!")
    return (t[:70] or "Untitled").capitalize()
