"""ORM model for itineraries (M7 owns).

Schema is owned by M0.3 / migration 0001_initial. This file mirrors that
schema as SQLAlchemy ORM. Do not add columns without updating spec M0.3
plus a new Alembic migration.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Itinerary(Base):
    __tablename__ = "itineraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_session_id: Mapped[str] = mapped_column(Text, nullable=False)
    places_snapshot: Mapped[list | dict | None] = mapped_column(JSONB)
    schedule: Mapped[list | dict | None] = mapped_column(JSONB)
    weather_context: Mapped[dict | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
