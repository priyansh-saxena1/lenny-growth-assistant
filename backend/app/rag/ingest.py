"""Ingestion.

Idempotent by content hash: re-running `make ingest` on an unchanged corpus
re-embeds nothing. That matters because the client will wire this to a cron
against a repo that adds one episode a week, and re-embedding 22k chunks
weekly to pick up one new file is silly.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings
from ..logging_setup import get_logger
from ..models import Document
from .chunker import chunk_turns, iter_transcript_files, load_episode
from .embedder import embed_texts
from .store import StoredChunk, get_store

log = get_logger(__name__)


@dataclass
class IngestStats:
    episodes_seen: int = 0
    episodes_ingested: int = 0
    episodes_skipped: int = 0
    episodes_failed: int = 0
    chunks_written: int = 0
    took_s: float = 0.0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "episodes_seen": self.episodes_seen,
            "episodes_ingested": self.episodes_ingested,
            "episodes_skipped": self.episodes_skipped,
            "episodes_failed": self.episodes_failed,
            "chunks_written": self.chunks_written,
            "took_s": round(self.took_s, 1),
            "failures": self.failures[:10],
        }


_state: dict = {"running": False, "last": None, "started_at": None}


def ingest_state() -> dict:
    return dict(_state)


def _docs_in_store(store) -> set[str]:
    """Document ids already embedded, for the no-database path.

    Without this a re-run of `make eval` re-embeds the whole corpus, which on a
    laptop is the difference between 20 seconds and 20 minutes.
    """
    if hasattr(store, "chunks"):
        return {c.document_id for c in store.chunks.values()}
    return set()


async def _known_hashes(track_in_db: bool) -> dict[str, str]:
    if not track_in_db:
        return {}
    from ..db import sessionmaker

    async with sessionmaker()() as s:
        rows = await s.execute(select(Document.id, Document.content_hash))
        return {r[0]: r[1] for r in rows}


async def ingest(
    root: Path | None = None,
    limit: int | None = None,
    force: bool = False,
    track_in_db: bool = True,
) -> IngestStats:
    s = get_settings()
    root = root or s.transcripts_dir
    store = get_store()
    if hasattr(store, "ensure_schema"):
        await store.ensure_schema()

    stats = IngestStats()
    t0 = time.perf_counter()
    _state.update(running=True, started_at=time.time())

    try:
        known = {} if force else await _known_hashes(track_in_db)
        already = set() if force else _docs_in_store(store)
        files = list(iter_transcript_files(root))[: limit or None]

        if hasattr(store, "drop_index"):
            await store.drop_index()

        for path in files:
            stats.episodes_seen += 1
            try:
                meta, turns = load_episode(path)
            except Exception as exc:  # a malformed file shouldn't abort the run
                stats.episodes_failed += 1
                stats.failures.append(f"{path.name}: {exc}")
                continue

            if not turns:
                stats.episodes_failed += 1
                stats.failures.append(f"{meta.slug}: no speaker turns parsed")
                continue

            if known.get(meta.slug) == meta.content_hash or meta.slug in already:
                stats.episodes_skipped += 1
                continue

            chunks = chunk_turns(meta, turns, s.chunk_target_chars, s.chunk_overlap_turns)
            vecs = await asyncio.to_thread(embed_texts, [c.text for c in chunks])
            stored = [
                StoredChunk(
                    id=c.id,
                    document_id=c.document_id,
                    ordinal=c.ordinal,
                    text=c.text,
                    speakers=c.speakers,
                    start_ts=c.start_ts,
                    end_ts=c.end_ts,
                    guest=meta.guest,
                    title=meta.title,
                    youtube_url=meta.youtube_url,
                )
                for c in chunks
            ]
            await store.upsert(stored, vecs)

            if track_in_db:
                await _record_document(meta, len(chunks))

            stats.episodes_ingested += 1
            stats.chunks_written += len(chunks)
            if stats.episodes_ingested % 25 == 0:
                log.info("ingest.progress", done=stats.episodes_ingested, chunks=stats.chunks_written)

        if hasattr(store, "save"):
            store.save()

        if hasattr(store, "rebuild_index"):
            await store.rebuild_index()
    finally:
        stats.took_s = time.perf_counter() - t0
        _state.update(running=False, last=stats.as_dict())

    log.info("ingest.done", **stats.as_dict())
    return stats


async def _record_document(meta, n_chunks: int) -> None:
    from ..db import sessionmaker

    async with sessionmaker()() as s:
        doc = await s.get(Document, meta.slug)
        if doc is None:
            doc = Document(id=meta.slug)
            s.add(doc)
        doc.guest = meta.guest
        doc.title = meta.title
        doc.youtube_url = meta.youtube_url
        doc.publish_date = meta.publish_date
        doc.keywords = meta.keywords
        doc.content_hash = meta.content_hash
        doc.n_chunks = n_chunks
        await s.commit()
