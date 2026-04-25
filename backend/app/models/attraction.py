"""M1: attractions ORM (schema 權威見 spec M0.3 / 0001_initial.py)."""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Attraction(Base):
    __tablename__ = "attractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    osm_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    embedding_bgem3: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embedding_mpnet: Mapped[list[float] | None] = mapped_column(Vector(768))
    source: Mapped[str | None] = mapped_column(Text, default="osm")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
