"""Async SQLAlchemy engine and session helpers.

Kept minimal on purpose: the current build uses Postgres for the vehicle
catalog only, so there is one engine, one session factory, and one
``ensure_schema`` helper for local development. When more entities move to
the database, this file grows an Alembic setup — not more sessions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.logging import get_logger
from app.core.settings import Settings
from app.infrastructure.persistence.models import Base

logger = get_logger(__name__)


def build_engine(settings: Settings) -> AsyncEngine:
    """Construct the async engine.

    ``pool_pre_ping`` is on because Postgres in Docker restarts happily
    without notifying its clients; without pre-ping the first request after
    a container bounce would fail with an unhelpful "connection closed".
    """
    return create_async_engine(
        settings.postgres_dsn,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Async context manager for a single unit of work.

    Commits on clean exit, rolls back on exception, and always closes.
    """
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ensure_schema(engine: AsyncEngine) -> None:
    """Create the ORM schema in Postgres if it is not there yet.

    Used by the ingestion worker and by the app's lifespan hook so a fresh
    clone works without a separate migration step. When the domain outgrows
    a single table this gets replaced by Alembic; a schema-create hook only
    ever creates missing objects, so it is safe to leave in place until then.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("postgres_schema_ready")
