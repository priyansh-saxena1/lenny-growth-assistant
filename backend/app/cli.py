"""Small CLI so operational tasks don't require an HTTP call.

    python -m app.cli ingest [--limit N] [--force]
    python -m app.cli status
    python -m app.cli ask "question"     # retrieval only, no model
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import get_settings
from .logging_setup import configure_logging


async def cmd_ingest(args) -> int:
    from .db import init_models
    from .rag.ingest import ingest

    s = get_settings()
    if s.vector_backend == "pgvector":
        await init_models()
    stats = await ingest(limit=args.limit, force=args.force,
                         track_in_db=(s.vector_backend == "pgvector"))
    d = stats.as_dict()
    print(f"\nepisodes: {d['episodes_ingested']} ingested, "
          f"{d['episodes_skipped']} unchanged, {d['episodes_failed']} failed")
    print(f"chunks:   {d['chunks_written']} written in {d['took_s']}s")
    for f in d["failures"]:
        print(f"  ! {f}", file=sys.stderr)
    return 0 if d["episodes_ingested"] or d["episodes_skipped"] else 1


async def cmd_status(_args) -> int:
    from .rag.store import get_store

    s = get_settings()
    store = get_store()
    n = await store.count()
    docs = len({c.document_id for c in getattr(store, "chunks", {}).values()}) or "?"
    print(f"vector backend : {s.vector_backend}")
    print(f"embed model    : {s.embed_model}")
    print(f"chunks indexed : {n}")
    print(f"episodes       : {docs}")
    print(f"provider       : {s.llm_provider}")
    return 0 if n else 1


async def cmd_ask(args) -> int:
    """Retrieval only. Useful for answering 'is the model wrong or is retrieval
    wrong?' without a model in the way."""
    from .rag.retriever import retrieve

    res = await retrieve(args.question)
    if not res.hits:
        print("no hits")
        return 1
    print(f"{len(res.hits)} hits in {res.took_ms}ms "
          f"(dense {res.dense_n}, lexical {res.lexical_n}, "
          f"guest filter: {res.guests_filter or 'none'})\n")
    for i, h in enumerate(res.hits, 1):
        print(f"[{i}] {h.guest} — {h.title} ({h.start_ts}) score={h.score:.4f}")
        print(f"    {h.text[:180].strip()}…\n")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="index transcripts")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true", help="re-embed unchanged episodes")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("status", help="index and config summary")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("ask", help="retrieval only, no generation")
    p.add_argument("question")
    p.set_defaults(fn=cmd_ask)

    args = ap.parse_args()
    s = get_settings()
    configure_logging(s.log_level, as_json=False)
    raise SystemExit(asyncio.run(args.fn(args)))


if __name__ == "__main__":
    main()
