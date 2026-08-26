from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Document, RequestTrace
from ..rag.ingest import ingest, ingest_state
from ..rag.store import get_store
from ..schemas import IngestRequest

router = APIRouter(prefix="/api/admin", tags=["ops"])


@router.post("/ingest", status_code=202)
async def start_ingest(body: IngestRequest):
    if ingest_state()["running"]:
        raise HTTPException(409, "an ingest is already running")
    # Fire and forget; poll /api/admin/ingest for progress. Ingesting 300
    # episodes takes minutes and holding an HTTP connection open for it is a
    # good way to discover your proxy's idle timeout.
    asyncio.create_task(ingest(limit=body.limit, force=body.force))
    return {"started": True, "poll": "/api/admin/ingest"}


@router.get("/ingest")
async def ingest_status(db: AsyncSession = Depends(get_session)):
    st = ingest_state()
    try:
        st["indexed_chunks"] = await get_store().count()
    except Exception as exc:
        st["indexed_chunks"] = None
        st["index_error"] = str(exc)[:200]
    try:
        st["documents"] = int((await db.execute(select(func.count(Document.id)))).scalar_one())
    except Exception:
        st["documents"] = None
    return st


@router.get("/traces")
async def traces(limit: int = 50, db: AsyncSession = Depends(get_session)):
    """Recent turns. This is the 'why was it slow / why was that answer bad'
    endpoint — provider, retrieval count, grounding score, stage timings."""
    rows = (await db.execute(
        select(RequestTrace).order_by(desc(RequestTrace.created_at)).limit(min(limit, 500))
    )).scalars().all()
    return [
        {"trace_id": t.trace_id, "session_id": t.session_id, "route": t.route,
         "provider": t.provider, "model": t.model, "used_fallback": bool(t.used_fallback),
         "retrieved_n": t.retrieved_n, "grounding_score": t.grounding_score,
         "total_ms": t.total_ms, "retrieval_ms": t.retrieval_ms,
         "generation_ms": t.generation_ms, "grounding_ms": t.grounding_ms,
         "error": t.error, "created_at": t.created_at}
        for t in rows
    ]
