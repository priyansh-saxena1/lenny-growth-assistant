import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    # Free-form client metadata (user handle, workspace, UA). Kept loose on
    # purpose: the client team hasn't settled their auth model yet.
    user_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)

    # Which skill produced this turn; null for plain user messages.
    skill: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Faithfulness gate output: {"score": 0.93, "supported": 14, "total": 15,
    #  "sentences": [{"text":..., "label":..., "evidence_chunk_id":...}]}
    grounding: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[Session] = relationship(back_populates="messages")
    citations: Mapped[list["Citation"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    marker: Mapped[int] = mapped_column(Integer)  # the [1], [2] the model wrote
    chunk_id: Mapped[str] = mapped_column(String(64))
    episode_slug: Mapped[str] = mapped_column(String(160))
    guest: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(Text)
    start_ts: Mapped[str] = mapped_column(String(12))
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    message: Mapped[Message] = relationship(back_populates="citations")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # markdown | html
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)  # post-sanitisation
    # What the sanitiser stripped, so the UI can show "2 things blocked".
    sanitizer_report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    """One podcast episode."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug
    guest: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(Text)
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publish_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    # sha256 of the source file. Ingest skips unchanged files on re-run.
    content_hash: Mapped[str] = mapped_column(String(64))
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    speakers: Mapped[list] = mapped_column(JSON, default=list)
    start_ts: Mapped[str] = mapped_column(String(12))
    end_ts: Mapped[str] = mapped_column(String(12))
    n_tokens: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("document_id", "ordinal", name="uq_chunk_ord"),)


class RequestTrace(Base):
    """One row per assistant turn. This is what you look at when someone says
    'it was slow yesterday' — provider, retrieval hit count, grounding score."""

    __tablename__ = "request_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    route: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    used_fallback: Mapped[int] = mapped_column(Integer, default=0)
    retrieved_n: Mapped[int] = mapped_column(Integer, default=0)
    grounding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_ms: Mapped[int] = mapped_column(Integer, default=0)
    generation_ms: Mapped[int] = mapped_column(Integer, default=0)
    grounding_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_traces_created", RequestTrace.created_at.desc())
