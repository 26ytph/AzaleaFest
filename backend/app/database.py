"""Async DB engine + session factory (spec M0.1).

FastAPI handlers use `get_session` as a dependency.
Scripts (M1 ingest, M4 ingest) construct sessions via `SessionLocal()`.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in app/models/."""


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
