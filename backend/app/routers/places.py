"""Places router (M3 owns). Mounted at /places by main.py (spec M0.4, M3.4).

  GET    /places?session_id={str}     -> Place[]    (按 created_at DESC)
  POST   /places                      -> Place      (body: PlaceCreate)
  DELETE /places/{id}?session_id={str} -> 204       (驗證 session_id 匹配)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.place import Place
from app.services.embedder import embed

log = logging.getLogger(__name__)

router = APIRouter()

Category = Literal["hotel", "food", "attraction"]
SourceType = Literal["reels_url", "image", "text", "manual"]
HotelStatus = Literal["legal", "illegal", "unknown"]


class PlaceOut(BaseModel):
    """對應 frontend/src/lib/types.ts Place（spec M0.5）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_session_id: str
    name: str
    category: Category
    lat: float
    lng: float
    address: str | None = None
    description: str | None = None
    source_type: SourceType | None = None
    source_url: str | None = None
    hotel_legal_status: HotelStatus | None = None
    created_at: datetime


class PlaceCreate(BaseModel):
    """對應 frontend/src/lib/types.ts PlaceCreate（spec M0.5）。"""

    session_id: str
    name: str
    category: Category
    lat: float
    lng: float
    address: str | None = None
    description: str | None = None
    source_type: SourceType
    source_url: str | None = None


@router.get("", response_model=list[PlaceOut])
async def list_places(
    session_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_session),
) -> list[Place]:
    rows = await db.execute(
        select(Place)
        .where(Place.user_session_id == session_id)
        .order_by(Place.created_at.desc())
    )
    return list(rows.scalars().all())


@router.post("", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
async def create_place(
    payload: PlaceCreate,
    db: AsyncSession = Depends(get_session),
) -> Place:
    embed_text = f"{payload.name}。{payload.category}。{payload.description or ''}"
    try:
        embedding = await embed(embed_text)
    except Exception:
        log.exception("embed failed in POST /places; inserting without vector")
        embedding = None

    place = Place(
        user_session_id=payload.session_id,
        name=payload.name,
        category=payload.category,
        lat=payload.lat,
        lng=payload.lng,
        address=payload.address,
        description=payload.description,
        source_type=payload.source_type,
        source_url=payload.source_url,
        embedding=embedding,
    )
    db.add(place)
    await db.commit()
    await db.refresh(place)
    return place


@router.delete("/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_place(
    place_id: int,
    session_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_session),
) -> Response:
    # 驗證 owner 後再刪 — 避免 session 互相刪除。
    row = await db.execute(
        select(Place.id).where(
            Place.id == place_id, Place.user_session_id == session_id
        )
    )
    if row.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="place not found")

    await db.execute(delete(Place).where(Place.id == place_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
