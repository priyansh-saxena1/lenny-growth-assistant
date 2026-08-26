from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import admin, artifacts, chat, health, sessions
from .config import get_settings
from .db import dispose, init_models
from .logging_setup import configure_logging, get_logger, new_trace_id, trace_id_var
from .schemas import ErrorBody

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup must not hard-fail on a missing database. If Postgres is slow to
    # come up under compose, the app should boot degraded and report it on
    # /api/health rather than crashloop and hide the reason.
    try:
        await init_models()
        log.info("startup.db_ready")
    except Exception as exc:
        log.error("startup.db_failed", error=str(exc))

    if settings.vector_backend == "pgvector":
        try:
            from .rag.store_pg import PgVectorStore

            await PgVectorStore().ensure_schema()
        except Exception as exc:
            log.error("startup.vector_schema_failed", error=str(exc))

    log.info("startup.ready", provider=settings.llm_provider,
             vector_backend=settings.vector_backend)
    yield
    await dispose()


app = FastAPI(
    title="Lenny Growth Assistant",
    version=health.VERSION,
    description="Grounded product & growth assistant over Lenny's Podcast transcripts.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    tid = request.headers.get("x-trace-id") or new_trace_id()
    trace_id_var.set(tid)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request.unhandled", path=request.url.path,
                      method=request.method)
        raise
    took = int((time.perf_counter() - t0) * 1000)
    response.headers["x-trace-id"] = tid
    # Health probes every few seconds would drown the log.
    if not request.url.path.startswith("/api/health"):
        log.info("request", method=request.method, path=request.url.path,
                 status=response.status_code, ms=took)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    codes = {404: "not_found", 409: "conflict", 503: "service_unavailable",
             401: "unauthorized", 429: "rate_limited"}
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorBody(code=codes.get(exc.status_code, "http_error"),
                          message=str(exc.detail),
                          trace_id=trace_id_var.get()).model_dump(),
    )


def _safe_errors(exc: RequestValidationError) -> list[dict]:
    """Pydantic puts the original exception object in `ctx`, which won't
    serialise. Keep the useful fields and stringify the rest."""
    out = []
    for e in exc.errors()[:10]:
        out.append({"loc": [str(x) for x in e.get("loc", [])],
                    "type": e.get("type", ""),
                    "msg": str(e.get("msg", ""))})
    return out


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=ErrorBody(code="validation_error", message="request failed validation",
                          detail={"errors": _safe_errors(exc)},
                          trace_id=trace_id_var.get()).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    # The trace id is the handle the user gives support; the exception text
    # stays in the logs.
    return JSONResponse(
        status_code=500,
        content=ErrorBody(code="internal_error",
                          message="something went wrong on our side",
                          trace_id=trace_id_var.get()).model_dump(),
    )


for r in (health.router, sessions.router, chat.router, artifacts.router, admin.router):
    app.include_router(r)


@app.get("/")
async def root():
    return {"service": "lenny-growth-assistant", "docs": "/docs",
            "health": "/api/health"}
