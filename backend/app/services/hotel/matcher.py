"""M4 匹配介面 — M3 import 的唯一入口 (spec M4.2)."""
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process
from sqlalchemy import text

from app.database import SessionLocal


@dataclass
class MatchResult:
    status: str                     # 'legal' | 'illegal' | 'unknown'
    match: dict | None              # matched hotel record
    alternatives: list = field(default_factory=list)
    score: float = 0.0


SCORE_THRESHOLD = 75

# ~1km candidate window (0.01° ≈ 1.1km)
COORD_WINDOW = 0.01

# Rough Taipei City bounding box — used to decide whether a sub-threshold
# match should be flagged 'illegal' (in Taipei) vs 'unknown' (out of scope).
TAIPEI_LAT_MIN, TAIPEI_LAT_MAX = 24.95, 25.21
TAIPEI_LNG_MIN, TAIPEI_LNG_MAX = 121.45, 121.67


async def match_hotel(name: str, lat: float, lng: float) -> MatchResult:
    """Hotel legality check (spec M4.2).

    1. Pull candidates from legal_hotels:
         - within ~1km box around (lat, lng)
         - fallback: SELECT ALL when no nearby rows exist
    2. rapidfuzz.process.extractOne with token_sort_ratio, score_cutoff=75.
    3. Map result:
         score >= 75              → legal
         score < 75, in Taipei    → illegal + 3 nearest legal hotels
         else                     → unknown
    """
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, name, address, lat, lng "
                "FROM legal_hotels "
                "WHERE lat IS NOT NULL AND lng IS NOT NULL "
                "  AND ABS(lat - :lat) < :w AND ABS(lng - :lng) < :w"
            ),
            {"lat": lat, "lng": lng, "w": COORD_WINDOW},
        )
        candidates = [dict(r) for r in result.mappings().all()]

        if not candidates:
            result = await session.execute(
                text("SELECT id, name, address, lat, lng FROM legal_hotels")
            )
            candidates = [dict(r) for r in result.mappings().all()]

        if not candidates:
            return MatchResult(status="unknown", match=None)

        choices = {c["id"]: c["name"] for c in candidates}
        hit = process.extractOne(
            query=name,
            choices=choices,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=SCORE_THRESHOLD,
        )

        if hit is not None:
            _, score, hotel_id = hit
            matched = next(c for c in candidates if c["id"] == hotel_id)
            return MatchResult(
                status="legal", match=matched, score=float(score)
            )

        in_taipei = (
            TAIPEI_LAT_MIN <= lat <= TAIPEI_LAT_MAX
            and TAIPEI_LNG_MIN <= lng <= TAIPEI_LNG_MAX
        )
        if in_taipei:
            result = await session.execute(
                text(
                    "SELECT id, name, address, lat, lng "
                    "FROM legal_hotels "
                    "WHERE lat IS NOT NULL AND lng IS NOT NULL "
                    "ORDER BY (lat - :lat) * (lat - :lat) "
                    "       + (lng - :lng) * (lng - :lng) ASC "
                    "LIMIT 3"
                ),
                {"lat": lat, "lng": lng},
            )
            alternatives = [dict(r) for r in result.mappings().all()]
            return MatchResult(
                status="illegal", match=None, alternatives=alternatives
            )

        return MatchResult(status="unknown", match=None)
