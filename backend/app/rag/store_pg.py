"""pgvector-backed store.

Lexical search is Postgres full-text (`ts_rank_cd`) rather than a second service.
One database for rows, vectors and BM25-ish scoring keeps the deployment to two
containers; architecture.md covers when that stops being the right call.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import text

from ..config import get_settings
from ..db import sessionmaker
from .store import Hit, StoredChunk

DDL = """
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id     TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL,
    ordinal      INT  NOT NULL,
    text         TEXT NOT NULL,
    speakers     JSONB NOT NULL DEFAULT '[]',
    start_ts     TEXT NOT NULL,
    end_ts       TEXT NOT NULL,
    guest        TEXT NOT NULL,
    title        TEXT NOT NULL,
    youtube_url  TEXT,
    embedding    vector(%(dim)s) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX IF NOT EXISTS ix_cv_tsv  ON chunk_vectors USING GIN (tsv);
CREATE INDEX IF NOT EXISTS ix_cv_doc  ON chunk_vectors (document_id, ordinal);
CREATE INDEX IF NOT EXISTS ix_cv_vec  ON chunk_vectors
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
"""


def _row_to_hit(r, arm: str) -> Hit:
    return Hit(
        chunk_id=r.chunk_id,
        document_id=r.document_id,
        text=r.text,
        guest=r.guest,
        title=r.title,
        start_ts=r.start_ts,
        end_ts=r.end_ts,
        youtube_url=r.youtube_url,
        score=float(r.score),
        arm=arm,
    )


class PgVectorStore:
    async def ensure_schema(self) -> None:
        dim = get_settings().embed_dim
        async with sessionmaker()() as s:
            await s.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            for stmt in (DDL % {"dim": dim}).strip().split(";\n"):
                if stmt.strip():
                    await s.execute(text(stmt))
            await s.commit()

    async def drop_index(self) -> None:
        async with sessionmaker()() as s:
            await s.execute(text("DROP INDEX IF EXISTS ix_cv_vec"))
            await s.commit()

    async def rebuild_index(self) -> None:
        dim = get_settings().embed_dim
        async with sessionmaker()() as s:
            await s.execute(text(
                f"CREATE INDEX ix_cv_vec ON chunk_vectors "
                f"USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
            ))
            await s.commit()

    async def upsert(self, chunks: list[StoredChunk], vectors: np.ndarray) -> None:
        import json

        rows = [
            {
                "chunk_id": c.id,
                "document_id": c.document_id,
                "ordinal": c.ordinal,
                "text": c.text,
                "speakers": json.dumps(c.speakers),
                "start_ts": c.start_ts,
                "end_ts": c.end_ts,
                "guest": c.guest,
                "title": c.title,
                "youtube_url": c.youtube_url,
                "embedding": "[" + ",".join(f"{x:.6f}" for x in v) + "]",
            }
            for c, v in zip(chunks, vectors, strict=True)
        ]
        sql = text(
            """
            INSERT INTO chunk_vectors
              (chunk_id, document_id, ordinal, text, speakers, start_ts, end_ts,
               guest, title, youtube_url, embedding)
            VALUES
              (:chunk_id, :document_id, :ordinal, :text, CAST(:speakers AS jsonb),
               :start_ts, :end_ts, :guest, :title, :youtube_url,
               CAST(:embedding AS vector))
            ON CONFLICT (chunk_id) DO UPDATE SET
              text = EXCLUDED.text, embedding = EXCLUDED.embedding,
              start_ts = EXCLUDED.start_ts, end_ts = EXCLUDED.end_ts
            """
        )
        async with sessionmaker()() as s:
            await s.execute(sql, rows)
            await s.commit()

    async def dense(self, qvec, k, guests=None):
        vec = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
        where = "WHERE guest ILIKE ANY(:guests)" if guests else ""
        sql = text(
            f"""
            SELECT chunk_id, document_id, text, guest, title, start_ts, end_ts,
                   youtube_url, 1 - (embedding <=> CAST(:v AS vector)) AS score
            FROM chunk_vectors {where}
            ORDER BY embedding <=> CAST(:v AS vector)
            LIMIT :k
            """
        )
        params = {"v": vec, "k": k}
        if guests:
            params["guests"] = [f"%{g}%" for g in guests]
        async with sessionmaker()() as s:
            res = await s.execute(sql, params)
            return [_row_to_hit(r, "dense") for r in res]

    async def lexical(self, query, k, guests=None):
        where = "AND guest ILIKE ANY(:guests)" if guests else ""
        sql = text(
            f"""
            SELECT chunk_id, document_id, text, guest, title, start_ts, end_ts,
                   youtube_url, ts_rank_cd(tsv, plainto_tsquery('english', :q)) AS score
            FROM chunk_vectors
            WHERE tsv @@ plainto_tsquery('english', :q) {where}
            ORDER BY score DESC
            LIMIT :k
            """
        )
        params = {"q": query, "k": k}
        if guests:
            params["guests"] = [f"%{g}%" for g in guests]
        async with sessionmaker()() as s:
            res = await s.execute(sql, params)
            return [_row_to_hit(r, "lexical") for r in res]

    async def count(self):
        async with sessionmaker()() as s:
            r = await s.execute(text("SELECT count(*) FROM chunk_vectors"))
            return int(r.scalar_one())

    async def all_chunks(self):
        async with sessionmaker()() as s:
            r = await s.execute(text(
                "SELECT chunk_id, document_id, ordinal, text, speakers, "
                "start_ts, end_ts, guest, title, youtube_url FROM chunk_vectors"
            ))
            return [_to_stored(row) for row in r.mappings()]

    async def get(self, chunk_id):
        async with sessionmaker()() as s:
            r = await s.execute(
                text("SELECT * FROM chunk_vectors WHERE chunk_id = :c"), {"c": chunk_id}
            )
            row = r.mappings().first()
            return _to_stored(row) if row else None

    async def neighbours(self, chunk_id, radius=1):
        async with sessionmaker()() as s:
            r = await s.execute(
                text(
                    """
                    SELECT n.* FROM chunk_vectors n
                    JOIN chunk_vectors c ON c.document_id = n.document_id
                    WHERE c.chunk_id = :c
                      AND n.ordinal BETWEEN c.ordinal - :r AND c.ordinal + :r
                    ORDER BY n.ordinal
                    """
                ),
                {"c": chunk_id, "r": radius},
            )
            return [_to_stored(row) for row in r.mappings()]


def _to_stored(row) -> StoredChunk:
    return StoredChunk(
        id=row["chunk_id"],
        document_id=row["document_id"],
        ordinal=row["ordinal"],
        text=row["text"],
        speakers=row["speakers"] or [],
        start_ts=row["start_ts"],
        end_ts=row["end_ts"],
        guest=row["guest"],
        title=row["title"],
        youtube_url=row["youtube_url"],
    )
