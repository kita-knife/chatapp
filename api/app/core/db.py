"""SQLAlchemy async engine and session helpers.

Schema management is delegated to Alembic (`alembic upgrade head`). The
declarative `Base` here is purely the metadata registry used by env.py and
ORM queries.

All business tables live in the `ai` schema (not `public`). Set via the
shared `MetaData` so every model class inherits the schema automatically;
individual models don't need to declare `__table_args__ = {"schema": "ai"}`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    metadata = MetaData(schema="ai")


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session
