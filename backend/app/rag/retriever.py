from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..config import get_settings
from ..logging_setup import get_logger
from .embedder import embed_query
from .store import Hit, get_store

log = get_logger(__name__)

# Rank-fusion constant from the original RRF paper. Left at 60; sweeping it
# between 20 and 100 moved recall@8 on the golden set by <1pt.
RRF_K = 60


@dataclass
class RetrievalResult:
    hits: list[Hit]
    guests_filter: list[str]
    took_ms: int
    dense_n: int
    lexical_n: int


_GUEST_CACHE: dict[str, list[str]] | None = None


async def _guest_index() -> dict[str, list[str]]:
    """surname/first-name -> full guest names, built once from the corpus.

    A learned query planner would be nicer but it's an LLM call on every turn
    for something a dictionary lookup gets right. Revisit if guests start
    getting referred to by company instead of name.
    """
    global _GUEST_CACHE
    if _GUEST_CACHE is not None:
        return _GUEST_CACHE
    store = get_store()
    idx: dict[str, list[str]] = {}
    names = set()
    if hasattr(store, "chunks"):
        names = {c.guest for c in store.chunks.values()}
    else:
        from sqlalchemy import text as sqltext

        from ..db import sessionmaker

        async with sessionmaker()() as s:
            r = await s.execute(sqltext("SELECT DISTINCT guest FROM chunk_vectors"))
            names = {row[0] for row in r}
    for full in names:
        for part in re.split(r"[\s&,]+", full):
            if len(part) > 2:
                idx.setdefault(part.lower(), []).append(full)
    _GUEST_CACHE = idx
    return idx


async def plan_guests(query: str) -> list[str]:
    idx = await _guest_index()
    toks = re.findall(r"[A-Za-z][A-Za-z'-]+", query)
    found: list[str] = []
    for t in toks:
        # Only trust capitalised tokens — "does chesky" is a name, "does the
        # design work" shouldn't filter to a guest called Design.
        if t[0].isupper() and t.lower() in idx:
            found.extend(idx[t.lower()])
    return sorted(set(found))


def rrf_fuse(arms: list[list[Hit]], k: int) -> list[Hit]:
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for arm in arms:
        for rank, h in enumerate(arm, start=1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            # Keep whichever arm's copy we saw first; the text is identical.
            best.setdefault(h.chunk_id, h)
    out = []
    for cid, sc in sorted(scores.items(), key=lambda kv: -kv[1])[:k]:
        h = best[cid]
        out.append(
            Hit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                text=h.text,
                guest=h.guest,
                title=h.title,
                start_ts=h.start_ts,
                end_ts=h.end_ts,
                youtube_url=h.youtube_url,
                score=sc,
                arm="fused",
            )
        )
    return out


async def retrieve(query: str, k: int | None = None, use_planner: bool = True) -> RetrievalResult:
    s = get_settings()
    k = k or s.retrieval_top_k
    t0 = time.perf_counter()
    store = get_store()

    guests = await plan_guests(query) if use_planner else []
    qvec = embed_query(query)

    dense = await store.dense(qvec, s.retrieval_candidates, guests or None)
    lexical = await store.lexical(query, s.retrieval_candidates, guests or None)

    # If the guest filter starved retrieval the name probably wasn't a guest
    # (e.g. someone the guest mentions). Drop the filter rather than return junk.
    if guests and len(dense) + len(lexical) < k:
        log.info("retrieval.planner_backoff", guests=guests)
        guests = []
        dense = await store.dense(qvec, s.retrieval_candidates, None)
        lexical = await store.lexical(query, s.retrieval_candidates, None)

    fused = rrf_fuse([dense, lexical], k)
    return RetrievalResult(
        hits=fused,
        guests_filter=guests,
        took_ms=int((time.perf_counter() - t0) * 1000),
        dense_n=len(dense),
        lexical_n=len(lexical),
    )
