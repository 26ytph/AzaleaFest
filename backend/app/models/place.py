"""ORM model for the `places` table (spec M0.3, owned by M3).

The table itself is created by alembic migration 0001_initial; this file
only declares the mapping so M3 routers/handlers can use SQLAlchemy ORM.
Other modules (M5/M6/M7) may SELECT but must not INSERT/UPDATE.
"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_session_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reels_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    hotel_legal_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to legal_hotels(id) is enforced at DB level by the alembic migration.
    # The ORM declaration is intentionally a plain Integer so M3 doesn't
    # depend on M4's not-yet-implemented LegalHotel mapper.
    hotel_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
