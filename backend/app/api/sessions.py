from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Artifact, Citation, Message
from ..models import Session as SessionRow
from ..schemas import CreateSession, MessageOut, SessionOut

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
async def create_session(body: CreateSession, db: AsyncSession = Depends(get_session)):
    row = SessionRow(title=body.title or "New chat", user_metadata=body.user_metadata)
    db.add(row)
    await db.commit()
    return SessionOut(id=row.id, title=row.title, user_metadata=row.user_metadata,
                      created_at=row.created_at, updated_at=row.updated_at,
                      message_count=0)


@router.get("", response_model=list[SessionOut])
async def list_sessions(limit: int = 50, db: AsyncSession = Depends(get_session)):
    counts = (
        select(Message.session_id, func.count().label("n"))
        .group_by(Message.session_id).subquery()
    )
    rows = await db.execute(
        select(SessionRow, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == SessionRow.id)
        .order_by(SessionRow.updated_at.desc())
        .limit(min(limit, 200))
    )
    return [
        SessionOut(id=s.id, title=s.title, user_metadata=s.user_metadata,
                   created_at=s.created_at, updated_at=s.updated_at, message_count=n)
        for s, n in rows
    ]


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def get_messages(session_id: str, db: AsyncSession = Depends(get_session)):
    if not await db.get(SessionRow, session_id):
        raise HTTPException(404, "session not found")

    msgs = (await db.execute(
        select(Message).where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )).scalars().all()

    cites = (await db.execute(
        select(Citation).where(Citation.message_id.in_([m.id for m in msgs] or [""]))
        .order_by(Citation.marker)
    )).scalars().all()

    by_msg: dict[str, list] = {}
    for c in cites:
        by_msg.setdefault(c.message_id, []).append(c)

    out = []
    for m in msgs:
        out.append(MessageOut(
            id=m.id, role=m.role, content=m.content, skill=m.skill,
            provider=m.provider, model=m.model, latency_ms=m.latency_ms,
            grounding=m.grounding, created_at=m.created_at,
            citations=[
                {"marker": c.marker, "chunk_id": c.chunk_id,
                 "episode_slug": c.episode_slug, "guest": c.guest, "title": c.title,
                 "start_ts": c.start_ts, "end_ts": c.start_ts,
                 "youtube_url": c.youtube_url, "score": c.score, "excerpt": ""}
                for c in by_msg.get(m.id, [])
            ],
        ))
    return out


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_session)):
    if not await db.get(SessionRow, session_id):
        raise HTTPException(404, "session not found")
    # Cascade is declared on the ORM relationship but artifacts are attached by
    # session_id rather than a relationship, so clear them explicitly.
    await db.execute(delete(Artifact).where(Artifact.session_id == session_id))
    await db.execute(delete(SessionRow).where(SessionRow.id == session_id))
    await db.commit()
