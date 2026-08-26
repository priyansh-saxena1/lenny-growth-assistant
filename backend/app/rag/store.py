"""Two stores behind one interface.

`pgvector` is the deployment target. `memory` exists so the test suite and the
eval harness run with no database at all — that's the difference between eval
numbers an evaluator can reproduce in 30 seconds and eval numbers they have to
take on faith. Both are exercised by tests/test_retrieval.py.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..config import get_settings


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    text: str
    guest: str
    title: str
    start_ts: str
    end_ts: str
    youtube_url: str | None
    score: float
    arm: str = ""  # "dense" | "lexical" | "fused" — useful when debugging recall


@dataclass
class StoredChunk:
    id: str
    document_id: str
    ordinal: int
    text: str
    speakers: list[str]
    start_ts: str
    end_ts: str
    guest: str
    title: str
    youtube_url: str | None


class VectorStore(Protocol):
    async def upsert(self, chunks: list[StoredChunk], vectors: np.ndarray) -> None: ...
    async def dense(self, qvec: np.ndarray, k: int, guests: list[str] | None) -> list[Hit]: ...
    async def lexical(self, query: str, k: int, guests: list[str] | None) -> list[Hit]: ...
    async def count(self) -> int: ...
    async def get(self, chunk_id: str) -> StoredChunk | None: ...
    async def neighbours(self, chunk_id: str, radius: int) -> list[StoredChunk]: ...
    async def all_chunks(self) -> list[StoredChunk]:
        """Every stored chunk. Only the eval harness calls this — it needs the
        full corpus text to check which golden questions are answerable from
        the current index, and doing that with per-question retrieval calls
        would be both slower and a worse test (it'd measure retrieval twice)."""
        ...


class MemoryStore:
    """Everything in RAM, optionally persisted to a pickle so `make eval` doesn't
    re-embed 22k chunks on every run."""

    def __init__(self, cache_path: Path | None = None):
        self.chunks: dict[str, StoredChunk] = {}
        self.order: list[str] = []
        self.vecs: np.ndarray | None = None
        self._bm25 = None
        self._bm25_ids: list[str] = []
        self.cache_path = cache_path

    # --- persistence ------------------------------------------------------
    def save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("wb") as fh:
            pickle.dump({"chunks": self.chunks, "order": self.order, "vecs": self.vecs}, fh)

    def load(self) -> bool:
        if not self.cache_path or not self.cache_path.exists():
            return False
        with self.cache_path.open("rb") as fh:
            d = pickle.load(fh)
        self.chunks, self.order, self.vecs = d["chunks"], d["order"], d["vecs"]
        return True

    # --- writes -----------------------------------------------------------
    async def upsert(self, chunks: list[StoredChunk], vectors: np.ndarray) -> None:
        new_rows = []
        for c, v in zip(chunks, vectors, strict=True):
            if c.id not in self.chunks:
                self.order.append(c.id)
                new_rows.append(v)
            self.chunks[c.id] = c
        if new_rows:
            block = np.asarray(new_rows, dtype=np.float32)
            self.vecs = block if self.vecs is None else np.vstack([self.vecs, block])
        self._bm25 = None

    # --- reads ------------------------------------------------------------
    async def dense(self, qvec, k, guests=None):
        if self.vecs is None or not self.order:
            return []
        sims = self.vecs @ np.asarray(qvec, dtype=np.float32)
        idx = np.argsort(-sims)
        out = []
        for i in idx:
            cid = self.order[int(i)]
            c = self.chunks[cid]
            if guests and not _guest_match(c, guests):
                continue
            out.append(_hit(c, float(sims[int(i)]), "dense"))
            if len(out) >= k:
                break
        return out

    async def lexical(self, query, k, guests=None):
        if not self.order:
            return []
        if self._bm25 is None:
            from rank_bm25 import BM25Okapi

            self._bm25_ids = list(self.order)
            corpus = [self.chunks[c].text.lower().split() for c in self._bm25_ids]
            self._bm25 = BM25Okapi(corpus)
        scores = self._bm25.get_scores(query.lower().split())
        idx = np.argsort(-scores)
        out = []
        for i in idx:
            cid = self._bm25_ids[int(i)]
            c = self.chunks[cid]
            if guests and not _guest_match(c, guests):
                continue
            out.append(_hit(c, float(scores[int(i)]), "lexical"))
            if len(out) >= k:
                break
        return out

    async def count(self):
        return len(self.chunks)

    async def all_chunks(self):
        return list(self.chunks.values())

    async def get(self, chunk_id):
        return self.chunks.get(chunk_id)

    async def neighbours(self, chunk_id, radius=1):
        c = self.chunks.get(chunk_id)
        if not c:
            return []
        want = range(c.ordinal - radius, c.ordinal + radius + 1)
        return sorted(
            (x for x in self.chunks.values() if x.document_id == c.document_id and x.ordinal in want),
            key=lambda x: x.ordinal,
        )


def _guest_match(c: StoredChunk, guests: list[str]) -> bool:
    g = c.guest.lower()
    return any(q.lower() in g for q in guests)


def _hit(c: StoredChunk, score: float, arm: str) -> Hit:
    return Hit(
        chunk_id=c.id,
        document_id=c.document_id,
        text=c.text,
        guest=c.guest,
        title=c.title,
        start_ts=c.start_ts,
        end_ts=c.end_ts,
        youtube_url=c.youtube_url,
        score=score,
        arm=arm,
    )


_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        s = get_settings()
        if s.vector_backend == "memory":
            from .cache import default_cache_path

            _store = MemoryStore(cache_path=default_cache_path())
            _store.load()
        else:
            from .store_pg import PgVectorStore

            _store = PgVectorStore()
    return _store


def set_store(store: VectorStore) -> None:
    """Test hook."""
    global _store
    _store = store
