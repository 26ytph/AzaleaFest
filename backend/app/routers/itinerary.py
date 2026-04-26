"""Itinerary router (M7 owns). Mounted at /itinerary by main.py.

  POST /itinerary/generate -> Itinerary (spec M0.4 / M7.1)
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.itinerary import generate

router = APIRouter()


class ItineraryGenerateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    date: str = Field(..., min_length=1)
    start_time: str = Field("09:00")


class ItineraryStopOut(BaseModel):
    """對齊 frontend/src/lib/types.ts ItineraryStop（spec M0.5）。

    `place_id=0` 為哨兵值：來源是 Google Places fallback、無對應的 DB row
    （此時 `google_place_id` 會帶 Google 的 opaque id）。
    """

    time: str
    place_id: int
    name: str
    duration_min: int
    transport_to_next: str
    note: str
    lat: float
    lng: float
    address: str | None = None
    google_place_id: str | None = None


class ItineraryOut(BaseModel):
    """對齊 frontend/src/lib/types.ts Itinerary。"""

    id: int
    stops: list[ItineraryStopOut]
    total_duration_hours: float


@router.post("/generate", response_model=ItineraryOut)
async def generate_itinerary(payload: ItineraryGenerateRequest) -> dict:
    return await generate(
        session_id=payload.session_id,
        date=payload.date,
        start_time=payload.start_time,
    )
