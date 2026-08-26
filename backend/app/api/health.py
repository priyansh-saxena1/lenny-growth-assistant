from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..config import get_settings
from ..db import sessionmaker
from ..llm.registry import health_all
from ..rag.store import get_store
from ..schemas import HealthOut

router = APIRouter(prefix="/api", tags=["ops"])

VERSION = "1.0.0"


@router.get("/health/live")
async def live():
    """Process is up. Deliberately checks nothing else — a liveness probe that
    depends on Postgres will restart a healthy app during a database blip."""
    return {"status": "ok"}


@router.get("/health", response_model=HealthOut)
async def health():
    s = get_settings()
    db_info: dict = {"ok": False}
    try:
        async with sessionmaker()() as sess:
            await sess.execute(text("SELECT 1"))
        db_info = {"ok": True, "backend": s.database_url.split("://")[0]}
    except Exception as exc:
        db_info = {"ok": False, "error": str(exc)[:200]}

    idx: dict = {"ok": False}
    try:
        n = await get_store().count()
        idx = {"ok": n > 0, "backend": s.vector_backend, "chunks": n,
               "embed_model": s.embed_model}
        if n == 0:
            idx["hint"] = "index is empty — run `make ingest`"
    except Exception as exc:
        idx = {"ok": False, "backend": s.vector_backend, "error": str(exc)[:200]}

    providers = await health_all()
    active_ok = any(p["provider"] == s.llm_provider and p["ok"] for p in providers)

    return HealthOut(
        status="ok" if (db_info["ok"] and idx["ok"] and active_ok) else "degraded",
        version=VERSION, database=db_info, index=idx, providers=providers,
        active_provider=s.llm_provider,
    )


@router.get("/config")
async def config():
    """What the UI needs to render the provider pill. No secrets — key presence
    only, never the key."""
    s = get_settings()
    return {
        "active_provider": s.llm_provider,
        "models": {"ollama": s.ollama_model, "anthropic": s.anthropic_model,
                   "openai": s.openai_model},
        "fallback_provider": s.fallback_provider,
        "keys_present": {"anthropic": bool(s.anthropic_api_key),
                         "openai": bool(s.openai_api_key)},
        "faithfulness_enabled": s.faithfulness_enabled,
        "vector_backend": s.vector_backend,
        "retrieval_top_k": s.retrieval_top_k,
    }
