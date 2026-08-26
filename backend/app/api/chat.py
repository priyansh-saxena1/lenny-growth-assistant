from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ..agent.orchestrator import load_history, run_turn, turn_payload
from ..db import get_session, sessionmaker
from ..llm.base import ProviderUnavailable
from ..logging_setup import get_logger, trace_id_var
from ..models import Session as SessionRow
from ..schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
log = get_logger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_session)):
    if not await db.get(SessionRow, body.session_id):
        raise HTTPException(404, "session not found")
    history = await load_history(db, body.session_id)
    try:
        r = await run_turn(body.message, body.session_id, db, body.provider, history)
    except ProviderUnavailable as exc:
        # 503 rather than 500: the request was fine, the model wasn't there.
        raise HTTPException(503, str(exc)) from exc
    return turn_payload(r)


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Progress events, then one final payload.

    Not token streaming. The grounding gate needs the whole answer before it can
    label anything, so streaming tokens would mean rendering text that might be
    struck through a second later — which is worse than a two-second wait with
    honest progress. Stage events keep it from feeling dead. architecture.md
    covers the token-streaming design if the client decides they want it.
    """

    async def gen():
        async with sessionmaker()() as db:
            if not await db.get(SessionRow, body.session_id):
                yield {"event": "error",
                       "data": json.dumps({"code": "session_not_found",
                                           "message": "session not found"})}
                return
            history = await load_history(db, body.session_id)
            yield {"event": "stage", "data": json.dumps({"stage": "routing"})}
            try:
                yield {"event": "stage", "data": json.dumps({"stage": "retrieving"})}
                r = await run_turn(body.message, body.session_id, db,
                                   body.provider, history)
            except ProviderUnavailable as exc:
                yield {"event": "error",
                       "data": json.dumps({"code": "provider_unavailable",
                                           "message": str(exc),
                                           "trace_id": trace_id_var.get()})}
                return
            except Exception as exc:
                log.exception("chat.stream_failed")
                yield {"event": "error",
                       "data": json.dumps({"code": "internal_error",
                                           "message": str(exc)[:300],
                                           "trace_id": trace_id_var.get()})}
                return
            yield {"event": "result", "data": json.dumps(turn_payload(r))}

    return EventSourceResponse(gen())
