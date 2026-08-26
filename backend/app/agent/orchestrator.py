"""One turn, end to end.

Everything the API layer needs is here: route the request, get evidence,
generate, score the grounding, sanitise any artifact, persist, and write a
trace row. The API routes stay thin so this is the only place turn logic lives.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from ..config import get_settings
from ..grounding.faithfulness import GroundingReport, check
from ..llm.base import LLMProvider, ProviderUnavailable
from ..llm.registry import get_fallback, get_provider
from ..logging_setup import get_logger, trace_id_var
from ..models import Artifact, Citation, Message, RequestTrace, Session
from ..rag.retriever import retrieve
from ..rag.store import Hit
from ..skills.artifact import create_artifact
from ..skills.ship30 import write_essay
from .router import classify
from .tools import ToolContext, format_sources

log = get_logger(__name__)

ANSWER_SYSTEM = """You answer questions about product management and growth using ONLY
the numbered transcript passages provided.

- Cite every factual claim with the matching [n] marker. A sentence with a
  number, a name or a framework in it needs a citation.
- One claim per sentence, closely paraphrasing the passage you cite for it.
  Don't fuse two passages into one sentence — if [2] and [5] both matter, that's
  two sentences, each citing the one it actually paraphrases. A sentence that
  blends several sources reads well but can't be checked against any single one.
- If the passages don't answer the question, say so plainly and name what the
  archive does cover nearby. Do not fall back on general knowledge.
- Be direct and concrete. Prefer what a guest actually did over abstractions.
  Never state a specific number, date or duration unless it appears in the
  cited passage — round or vague language beats an invented precise figure.
- Answer in prose with short paragraphs. No preamble like "Based on the passages".
- Keep it under 350 words unless the question genuinely needs more."""

# Local 7B models produce noticeably better citations with fewer, shorter
# passages; cloud models handle the full top-k. Measured on the golden set.
LOCAL_CONTEXT_BUDGET = 5


@dataclass
class TurnResult:
    text: str
    route: str
    decided_by: str
    hits: list[Hit]
    grounding: GroundingReport | None
    provider: str
    model: str
    used_fallback: bool
    scorecard: dict | None = None
    artifact: dict | None = None
    timings: dict[str, int] = field(default_factory=dict)
    message_id: str | None = None

    def citations(self) -> list[dict]:
        return [
            {"marker": i, "chunk_id": h.chunk_id, "episode_slug": h.document_id,
             "guest": h.guest, "title": h.title, "start_ts": h.start_ts,
             "end_ts": h.end_ts, "youtube_url": _yt(h), "score": round(h.score, 4),
             "excerpt": h.text[:400]}
            for i, h in enumerate(self.hits, start=1)
        ]


def _yt(h: Hit) -> str | None:
    """Deep-link the citation to the second it was said."""
    if not h.youtube_url:
        return None
    try:
        hh, mm, ss = (int(x) for x in h.start_ts.split(":"))
    except ValueError:
        return h.youtube_url
    sep = "&" if "?" in h.youtube_url else "?"
    return f"{h.youtube_url}{sep}t={hh * 3600 + mm * 60 + ss}"


async def _with_fallback(fn, provider: LLMProvider):
    """Run fn(provider); on ProviderUnavailable retry once on the fallback.

    Only ProviderUnavailable triggers this. A model that returned a bad answer
    will usually return a bad answer on the other model too, just slower.
    """
    try:
        return await fn(provider), provider, False
    except ProviderUnavailable as exc:
        fb = get_fallback()
        if fb is None:
            raise
        log.warning("provider.fallback", frm=provider.name, to=fb.name, error=str(exc))
        return await fn(fb), fb, True


def _budget(hits: list[Hit], provider: LLMProvider) -> list[Hit]:
    return hits[:LOCAL_CONTEXT_BUDGET] if provider.name == "ollama" else hits


async def run_turn(
    query: str,
    session_id: str,
    db,
    provider_name: str | None = None,
    history: list[dict] | None = None,
) -> TurnResult:
    s = get_settings()
    provider = get_provider(provider_name)
    ctx = ToolContext(session_id=session_id, provider_name=provider.name)
    history = history or []
    t_start = time.perf_counter()
    timings: dict[str, int] = {}

    route = await classify(query, provider)
    log.info("turn.route", route=route.name, by=route.decided_by)

    # --- evidence ---------------------------------------------------------
    t0 = time.perf_counter()
    search_query = _standalone(query, history)
    res = await retrieve(search_query)
    ctx.merge_hits(res.hits)
    timings["retrieval_ms"] = int((time.perf_counter() - t0) * 1000)

    hits = ctx.hits
    scorecard = artifact_payload = None
    grounding: GroundingReport | None = None

    # --- generation -------------------------------------------------------
    t0 = time.perf_counter()

    if route.name == "essay":
        async def _go(p):
            return await write_essay(route.args["topic"], _budget(hits, p), p,
                                     route.args.get("angle"))
        (text, card), provider, used_fb = await _with_fallback(_go, provider)
        scorecard = card.as_dict()

    elif route.name == "artifact":
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])

        async def _go(p):
            return await create_artifact(route.args["kind"], route.args["title"],
                                         route.args["brief"], _budget(hits, p), p, convo)
        art, provider, used_fb = await _with_fallback(_go, provider)
        artifact_payload = {
            "kind": art.kind, "title": art.title, "content": art.content,
            "sanitizer_report": art.report.as_dict(),
        }
        blocked = art.report.blocked
        text = (
            f"I've put **{art.title}** in the viewer."
            + (f" The sanitiser blocked {len(blocked)} thing(s) — "
               f"{', '.join(sorted({b['rule'] for b in blocked}))}."
               if blocked else "")
        )

    else:
        if not hits:
            text, used_fb = (
                "I don't have transcript material covering that. The archive is "
                "Lenny's Podcast — product, growth, hiring and company building — "
                "so try rephrasing toward one of those.",
                False,
            )
        else:
            budgeted = _budget(hits, provider)
            prompt = (
                f"Question: {query}\n\nNumbered transcript passages:\n\n"
                f"{format_sources(budgeted)}"
            )
            msgs = [*_recent(history), {"role": "user", "content": prompt}]

            async def _go(p):
                return await p.complete(msgs, system=ANSWER_SYSTEM, max_tokens=1024)
            r, provider, used_fb = await _with_fallback(_go, provider)
            text = r.text.strip()
            hits = budgeted

    timings["generation_ms"] = int((time.perf_counter() - t0) * 1000)

    # --- grounding gate ---------------------------------------------------
    if s.faithfulness_enabled and route.name != "artifact" and hits:
        t0 = time.perf_counter()
        grounding = check(text, hits)
        timings["grounding_ms"] = int((time.perf_counter() - t0) * 1000)

    timings["total_ms"] = int((time.perf_counter() - t_start) * 1000)

    result = TurnResult(
        text=text, route=route.name, decided_by=route.decided_by, hits=hits,
        grounding=grounding, provider=provider.name, model=provider.model,
        used_fallback=used_fb, scorecard=scorecard, artifact=artifact_payload,
        timings=timings,
    )
    await _persist(db, session_id, query, result)
    return result


def _recent(history: list[dict], n: int = 4) -> list[dict]:
    """Last few turns, trimmed. Full history blows the context on a 7B model and
    the retrieved passages carry most of the signal anyway."""
    out = []
    for m in history[-n:]:
        out.append({"role": m["role"], "content": m["content"][:1200]})
    return out


def _standalone(query: str, history: list[dict]) -> str:
    """Make a follow-up retrievable on its own.

    "What about for B2B?" embeds to nothing useful. Prepending the last user
    turn is crude but costs no model call and fixed most follow-up misses on
    the golden set; a rewrite model is the upgrade path.
    """
    if len(query.split()) > 8 or not history:
        return query
    prev = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    return f"{prev} {query}".strip() if prev else query


async def _persist(db, session_id: str, query: str, r: TurnResult) -> None:
    db.add(Message(session_id=session_id, role="user", content=query))
    msg = Message(
        session_id=session_id, role="assistant", content=r.text, skill=r.route,
        provider=r.provider, model=r.model, latency_ms=r.timings.get("total_ms"),
        grounding=r.grounding.as_dict() if r.grounding else None,
    )
    db.add(msg)
    await db.flush()
    r.message_id = msg.id

    for c in r.citations():
        db.add(Citation(message_id=msg.id, marker=c["marker"], chunk_id=c["chunk_id"],
                        episode_slug=c["episode_slug"], guest=c["guest"],
                        title=c["title"], start_ts=c["start_ts"],
                        youtube_url=c["youtube_url"], score=c["score"]))

    if r.artifact:
        art = Artifact(session_id=session_id, message_id=msg.id, kind=r.artifact["kind"],
                       title=r.artifact["title"], content=r.artifact["content"],
                       sanitizer_report=r.artifact["sanitizer_report"])
        db.add(art)
        await db.flush()
        r.artifact["id"] = art.id

    db.add(RequestTrace(
        trace_id=trace_id_var.get(), session_id=session_id, route=r.route,
        provider=r.provider, model=r.model, used_fallback=int(r.used_fallback),
        retrieved_n=len(r.hits),
        grounding_score=r.grounding.score if r.grounding else None,
        total_ms=r.timings.get("total_ms", 0),
        retrieval_ms=r.timings.get("retrieval_ms", 0),
        generation_ms=r.timings.get("generation_ms", 0),
        grounding_ms=r.timings.get("grounding_ms", 0),
    ))

    sess = await db.get(Session, session_id)
    if sess and sess.title == "New chat":
        sess.title = query[:70] + ("…" if len(query) > 70 else "")
    await db.commit()


async def load_history(db, session_id: str) -> list[dict]:
    rows = await db.execute(
        select(Message.role, Message.content)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    return [{"role": r[0], "content": r[1]} for r in rows if r[0] in ("user", "assistant")]


def turn_payload(r: TurnResult) -> dict[str, Any]:
    return {
        "message_id": r.message_id,
        "text": r.text,
        "route": r.route,
        "decided_by": r.decided_by,
        "provider": r.provider,
        "model": r.model,
        "used_fallback": r.used_fallback,
        "citations": r.citations(),
        "grounding": r.grounding.as_dict() if r.grounding else None,
        "scorecard": r.scorecard,
        "artifact": r.artifact,
        "timings": r.timings,
    }
