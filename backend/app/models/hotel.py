"""ORM model for legal_hotels (M4 owns; M3 reads via match_hotel).

Schema is owned by M0.3. This file mirrors that schema as SQLAlchemy ORM —
do not add columns here without updating spec M0.3 + an Alembic migration.
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LegalHotel(Base):
    __tablename__ = "legal_hotels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    license_number: Mapped[str | None] = mapped_column(Text, unique=True)
    hotel_type: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
