"""M4 匹配介面 — M3 import 的唯一入口 (spec M4.2).

Two-stage matching:
  Stage 1 — 1km coord window + cutoff 75. Fast path; geographic proximity
            acts as a sanity check, so a moderately fuzzy name match is OK.
  Stage 2 — global search over all legal_hotels + cutoff 85. Catches the
            case where geocoding mislocates the user's pin (Mapbox/Google
            disagreement on a vague query like '福華大飯店' can be 1km+ off,
            sliding the real match outside the 1km window). Stricter cutoff
            because we no longer have geographic prior.
  Stage 3 — illegal + 3 nearest legal hotels as alternatives.

We do not return 'unknown' in normal operation; that status is reserved for
the defensive case where the legal_hotels table is empty.
"""
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


SCORE_THRESHOLD = 75               # Stage 1 (1km window) — token_sort_ratio
# Stage 2 (whole DB) — uses fuzz.WRatio so substring patterns like
# "君悅酒店" ⊂ "台北君悅酒店" hit 90 (token_sort_ratio gives only 80, missing
# them). 90 also blocks chain false-positives like "台北福華" vs "台北美福" (86).
SCORE_THRESHOLD_GLOBAL = 90
# WRatio 對 1-字查詢仍給 90（"君" 命中 "台北君悅酒店"）。最少 3 字才跑 Stage 2。
MIN_GLOBAL_QUERY_LEN = 3

# 0.01° ≈ 1.1km. Trades off candidate count against geocoding error tolerance.
COORD_WINDOW = 0.01


async def match_hotel(name: str, lat: float, lng: float) -> MatchResult:
    """Hotel legality check (spec M4.2)."""
    async with SessionLocal() as session:
        # Stage 1: 1km window
        nearby = await _fetch_near(session, lat, lng)
        if nearby:
            hit = _fuzz_pick(name, nearby, SCORE_THRESHOLD)
            if hit is not None:
                row, score = hit
                return MatchResult(status="legal", match=row, score=score)

        # Stage 2: whole DB, stricter cutoff with WRatio
        all_rows = await _fetch_all(session)
        if not all_rows:
            return MatchResult(status="unknown", match=None)

        if len(name.strip()) >= MIN_GLOBAL_QUERY_LEN:
            hit = _fuzz_pick(
                name, all_rows, SCORE_THRESHOLD_GLOBAL, scorer=fuzz.WRatio
            )
            if hit is not None:
                row, score = hit
                return MatchResult(status="legal", match=row, score=score)

        # Stage 3: illegal + 3 nearest legal hotels (concrete redirect targets)
        alternatives = await _fetch_nearest(session, lat, lng, limit=3)
        return MatchResult(
            status="illegal", match=None, alternatives=alternatives
        )


def _fuzz_pick(
    name: str,
    rows: list[dict],
    cutoff: int,
    scorer=fuzz.token_sort_ratio,
) -> tuple[dict, float] | None:
    """rapidfuzz best-match over rows; None if below cutoff."""
    choices = {r["id"]: r["name"] for r in rows}
    hit = process.extractOne(
        query=name, choices=choices, scorer=scorer, score_cutoff=cutoff,
    )
    if hit is None:
        return None
    _, score, hotel_id = hit
    matched = next(r for r in rows if r["id"] == hotel_id)
    return matched, float(score)


async def _fetch_near(session, lat: float, lng: float) -> list[dict]:
    result = await session.execute(
        text(
            "SELECT id, name, address, lat, lng "
            "FROM legal_hotels "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL "
            "  AND ABS(lat - :lat) < :w AND ABS(lng - :lng) < :w"
        ),
        {"lat": lat, "lng": lng, "w": COORD_WINDOW},
    )
    return [dict(r) for r in result.mappings().all()]


async def _fetch_all(session) -> list[dict]:
    result = await session.execute(
        text("SELECT id, name, address, lat, lng FROM legal_hotels")
    )
    return [dict(r) for r in result.mappings().all()]


async def _fetch_nearest(
    session, lat: float, lng: float, limit: int
) -> list[dict]:
    result = await session.execute(
        text(
            "SELECT id, name, address, lat, lng "
            "FROM legal_hotels "
            "WHERE lat IS NOT NULL AND lng IS NOT NULL "
            "ORDER BY (lat - :lat) * (lat - :lat) "
            "       + (lng - :lng) * (lng - :lng) ASC "
            "LIMIT :limit"
        ),
        {"lat": lat, "lng": lng, "limit": limit},
    )
    return [dict(r) for r in result.mappings().all()]
