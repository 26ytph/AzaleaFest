"""M4 匹配介面 — M3 import 的唯一入口 (spec M4.2).

Matching policy: the static legal_hotels list is authoritative — if a fuzzy
match clears SCORE_THRESHOLD, the hotel is legal; otherwise it is illegal,
and we surface the 3 nearest legal hotels as alternatives. We do not return
'unknown' in normal operation; that status is reserved for the defensive
case where the legal_hotels table is empty (operator hasn't run ingest yet).
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


SCORE_THRESHOLD = 75

# ~1km candidate window (0.01° ≈ 1.1km) — keeps the fuzzy comparison cheap
# without changing the legal/illegal verdict, since a hotel that doesn't
# appear within 1km of its own claimed coords almost certainly isn't a match.
COORD_WINDOW = 0.01


async def match_hotel(name: str, lat: float, lng: float) -> MatchResult:
    """Hotel legality check (spec M4.2).

    Steps:
      1. Pull candidates from legal_hotels within ~1km of (lat, lng).
         Fallback: SELECT ALL when no nearby rows exist (so we still match
         on hotels with missing coords).
      2. Score against candidate names with rapidfuzz token_sort_ratio,
         cutoff=75.
      3. Verdict:
           score >= 75 → 'legal' + matched record
           score <  75 → 'illegal' + up to 3 nearest legal hotels
           empty DB    → 'unknown' (defensive only)
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

        # Not on the static list → illegal. Show 3 nearest legal hotels so
        # the user has something concrete to redirect to.
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
