"""Artifact skill.

Generates a Markdown doc or a self-contained HTML page from the current turn's
evidence, then hands the raw output to the sanitiser before it is ever stored
or returned. Generation and sanitisation are separate on purpose: the model
output is logged pre-sanitisation (at DEBUG) so that when someone reports "the
artifact lost my chart", you can tell whether the model failed to write it or
the sanitiser stripped it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..llm.base import LLMProvider
from ..logging_setup import get_logger
from ..rag.store import Hit
from ..security.sanitize import SanitizerReport, sanitize

log = get_logger(__name__)

MD_SYSTEM = """You produce a standalone Markdown document.

Rules:
- Output Markdown only. No preamble, no "here is your document", no code fences
  around the whole thing.
- Start with a single '# ' title.
- Use headings, tables and bullets — this is a document, not a chat reply.
- Ground every factual claim in the numbered passages and mark it [n].
- If the passages don't cover something the user asked for, leave it out and
  add a short "Not covered by the archive" note at the end."""

HTML_SYSTEM = """You produce ONE complete, self-contained HTML page.

Hard constraints (the renderer enforces these; violating them means your output
is silently stripped):
- Everything inline. No external stylesheets, fonts, scripts or images.
- No network calls of any kind — fetch, XHR and WebSocket are blocked.
- No <form>, <iframe>, <object> or <embed>.
- Inline <script> and <style> are allowed and encouraged for interactivity.
- Use system fonts (-apple-system, Segoe UI, sans-serif) and CSS you write yourself.

Design it properly: real spacing, hierarchy and colour. Output HTML only, no
markdown fences, no commentary. Ground factual content in the numbered passages."""


@dataclass
class ArtifactResult:
    kind: str
    title: str
    content: str          # sanitised
    report: SanitizerReport
    raw_length: int


async def create_artifact(
    kind: str,
    title: str,
    brief: str,
    hits: list[Hit],
    provider: LLMProvider,
    conversation: str = "",
) -> ArtifactResult:
    from ..agent.tools import format_sources

    kind = "html" if kind == "html" else "markdown"
    parts = [f"Title: {title}", f"What to produce: {brief}"]
    if conversation:
        parts.append(f"Relevant conversation so far:\n{conversation[-3000:]}")
    if hits:
        parts.append(f"Transcript passages:\n\n{format_sources(hits)}")

    res = await provider.complete(
        [{"role": "user", "content": "\n\n".join(parts)}],
        system=HTML_SYSTEM if kind == "html" else MD_SYSTEM,
        max_tokens=4096,
        temperature=0.4,
    )
    raw = _strip_fences(res.text, kind)
    clean, report = sanitize(kind, raw)

    if report.blocked:
        log.info("artifact.sanitized", kind=kind, blocked=len(report.blocked),
                 rules=sorted({b["rule"] for b in report.blocked}))
    log.debug("artifact.raw", kind=kind, raw=raw[:4000])

    return ArtifactResult(kind, title, clean, report, len(raw))


def _strip_fences(text: str, kind: str) -> str:
    t = text.strip()
    m = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```\s*$", t, re.S)
    if m:
        t = m.group(1).strip()
    if kind == "html":
        # Models sometimes prepend a sentence before the doctype. Drop anything
        # before the first tag rather than letting it render as body text.
        i = t.lower().find("<!doctype")
        if i == -1:
            i = t.lower().find("<html")
        if i == -1:
            i = t.find("<")
        if i > 0:
            t = t[i:]
    return t
