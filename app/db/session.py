"""Database connection. DATABASE_URL comes from Railway's Postgres; locally it defaults to SQLite."""
import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./local.db")
    # Railway gives postgres:// or postgresql://; SQLAlchemy's async driver needs postgresql+asyncpg://
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


_engine = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def engine():
    global _engine, _sessions
    if _engine is None:
        _engine = create_async_engine(database_url(), pool_pre_ping=True)
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset(url: str | None = None) -> None:
    """Point at a different database (tests)."""
    global _engine, _sessions
    if url:
        os.environ["DATABASE_URL"] = url
    _engine = _sessions = None


@asynccontextmanager
async def session():
    engine()
    async with _sessions() as s:
        yield s


async def create_tables_if_sqlite() -> None:
    """SQLite (local runs and tests) builds tables directly. Postgres uses Alembic migrations."""
    if database_url().startswith("sqlite"):
        async with engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
