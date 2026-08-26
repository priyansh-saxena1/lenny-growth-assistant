from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine():
    global _engine, _sessionmaker
    if _engine is None:
        url = get_settings().database_url
        # SQLite is only used by the test suite and `make eval`; Postgres is the
        # deployment target. Keeping both on SQLAlchemy async means one code path.
        kwargs = {"pool_pre_ping": True} if url.startswith("postgresql") else {}
        _engine = create_async_engine(url, echo=False, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        yield s


async def init_models() -> None:
    """Create tables if absent.

    Deliberately not Alembic. This is a single-service demo with a schema that
    hasn't shipped anywhere yet; migrations would be ceremony. architecture.md
    notes the point at which the client should introduce them.
    """
    async with engine().begin() as conn:
        if get_settings().vector_backend == "pgvector":
            from sqlalchemy import text

            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
