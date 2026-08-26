from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ErrorBody(BaseModel):
    """Every 4xx/5xx from this API has this shape. `code` is stable and safe to
    branch on; `message` is for humans and may change."""

    code: str
    message: str
    detail: dict[str, Any] | None = None
    trace_id: str | None = None


class CreateSession(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    user_metadata: dict[str, Any] = Field(default_factory=dict)


class SessionOut(BaseModel):
    id: str
    title: str
    user_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=8000)
    # Per-request override so an evaluator can compare local vs cloud on the
    # same question without restarting anything.
    provider: Literal["ollama", "anthropic", "openai", "echo"] | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be blank")
        return v.strip()


class CitationOut(BaseModel):
    marker: int
    chunk_id: str
    episode_slug: str
    guest: str
    title: str
    start_ts: str
    end_ts: str
    youtube_url: str | None
    score: float
    excerpt: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    skill: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    grounding: dict[str, Any] | None = None
    citations: list[CitationOut] = Field(default_factory=list)
    created_at: datetime


class ChatResponse(BaseModel):
    message_id: str | None
    text: str
    route: str
    decided_by: str
    provider: str
    model: str
    used_fallback: bool
    citations: list[CitationOut]
    grounding: dict[str, Any] | None
    scorecard: dict[str, Any] | None
    artifact: dict[str, Any] | None
    timings: dict[str, int]


class ArtifactOut(BaseModel):
    id: str
    session_id: str
    kind: str
    title: str
    content: str
    sanitizer_report: dict[str, Any]
    created_at: datetime


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: dict[str, Any]
    index: dict[str, Any]
    providers: list[dict[str, Any]]
    active_provider: str


class IngestRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=5000)
    force: bool = False
