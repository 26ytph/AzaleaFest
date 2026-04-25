"""Recommend router (M5 owns). Mounted at /recommend by main.py.

Endpoints (spec M0.4):
    POST "" -> RecommendResult[]
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.rag.recommender import find_similar

router = APIRouter()

Category = Literal["hotel", "food", "attraction", "all"]


class RecommendRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    category: Category
    limit: int = Field(5, ge=1, le=20)


class AttractionOut(BaseModel):
    """對齊 frontend/src/lib/types.ts Attraction（spec M0.5）。"""

    id: int
    name: str
    category: str
    lat: float
    lng: float
    address: str | None = None
    description: str | None = None
    tags: list[str] = []


class RecommendResult(BaseModel):
    """對齊 frontend/src/lib/types.ts RecommendResult。"""

    attraction: AttractionOut
    reason: str
    score: float


@router.post("", response_model=list[RecommendResult])
async def recommend(payload: RecommendRequest) -> list[dict]:
    return await find_similar(
        session_id=payload.session_id,
        category=payload.category,
        limit=payload.limit,
    )
