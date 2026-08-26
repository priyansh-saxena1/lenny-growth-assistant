from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Artifact
from ..schemas import ArtifactOut
from ..security.sanitize import POLICY

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/policy")
async def policy():
    """What the viewer permits and blocks, and why.

    Exposed as an endpoint rather than buried in docs so the UI can render it in
    the viewer's info panel and it can't drift from the code enforcing it.
    """
    return POLICY


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(artifact_id: str, db: AsyncSession = Depends(get_session)):
    a = await db.get(Artifact, artifact_id)
    if not a:
        raise HTTPException(404, "artifact not found")
    return ArtifactOut(id=a.id, session_id=a.session_id, kind=a.kind, title=a.title,
                       content=a.content, sanitizer_report=a.sanitizer_report,
                       created_at=a.created_at)


@router.get("", response_model=list[ArtifactOut])
async def list_artifacts(session_id: str, db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(
        select(Artifact).where(Artifact.session_id == session_id)
        .order_by(Artifact.created_at.desc())
    )).scalars().all()
    return [ArtifactOut(id=a.id, session_id=a.session_id, kind=a.kind, title=a.title,
                        content=a.content, sanitizer_report=a.sanitizer_report,
                        created_at=a.created_at) for a in rows]
