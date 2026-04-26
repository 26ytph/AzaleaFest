"""M4 hotel matcher — public entry imported by M3 (spec M4.2).

Flow (Google Places-driven):
  1. Resolve the user's name to a specific Google place via
     `google_resolver.resolve_hotel`. This replaces the legacy Stage-1
     1km-window fuzz; the resolver gives us a canonical place_id and
     trustworthy coordinates instead of relying on the user-supplied lat/lng.
  2. If Google returns nothing → status="unknown" (no defensible verdict).
  3. If the resolved place is not in Taipei City → status="unknown".
     Crucially NOT illegal: legal_hotels only enumerates Taipei legal
     hotels, so a non-Taipei hotel is simply out of scope.
  4. Exact-match the resolved place_id against legal_hotels → status="legal".
  5. Fallback to global rapidfuzz (WRatio cutoff 90) for rows that Google
     hasn't been re-geocoded for yet, or chain-renames.
  6. Otherwise status="illegal", with the 3 nearest legal hotels (by
     resolved.lat/lng) as alternatives.

The signature keeps `lat` and `lng` for back-compat with the spec M0.4
HTTP contract `GET /hotels/verify?name&lat&lng`. Both are now ignored
internally — they are advisory hints only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process
from sqlalchemy import text

from app.database import SessionLocal
from app.services.hotel.google_resolver import ResolvedPlace, resolve_hotel

log = logging.getLogger(__name__)


@dataclass
class MatchResult:
    status: str                     # 'legal' | 'illegal' | 'unknown'
    match: dict | None              # matched hotel record
    alternatives: list = field(default_factory=list)
    score: float = 0.0


# Single global cutoff for the fuzz fallback. WRatio handles substring
# patterns ("君悅酒店" ⊂ "台北君悅酒店" → 90+) and blocks chain
# false-positives like "台北福華" vs "台北美福" (~86).
SCORE_THRESHOLD_GLOBAL = 90
# WRatio gives "君" ≥ 90 against "台北君悅酒店"; require ≥ 3 chars before
# the global path runs, otherwise single-character noise matches.
MIN_GLOBAL_QUERY_LEN = 3


async def match_hotel(
    name: str, lat: float | None = None, lng: float | None = None
) -> MatchResult:
    """Hotel legality check (spec M4.2).

    `lat`/`lng` are accepted for HTTP-contract back-compat (spec M0.4) but
    are not consulted; the matcher derives canonical coordinates from
    Google Places via `resolve_hotel`.
    """
    resolved = await resolve_hotel(name)
    if resolved is None:
        return MatchResult(status="unknown", match=None)
    if not resolved.in_taipei:
        # Out of Taipei → not "illegal"; legal_hotels is a Taipei-only set.
        return MatchResult(status="unknown", match=None)

    async with SessionLocal() as session:
        # Primary: place_id exact match. 100.0 is a synthetic confidence
        # marker (rapidfuzz tops out at 100 too) so callers can treat
        # this as "no fuzz involved".
        hit = await _fetch_by_place_id(session, resolved.place_id)
        if hit is not None:
            return MatchResult(status="legal", match=hit, score=100.0)

        # Fallback: global fuzz. Catches rows whose google_place_id is
        # still NULL (re-geocode missed them) or whose Google-canonical
        # name doesn't match what we stored — e.g. for Sheraton, Google
        # returns "Sheraton Grand Taipei Hotel" (English) but our DB row
        # is "台北寒舍喜來登大飯店", which scripts <10 across.
        # Solution: fuzz against BOTH the user's raw input and the Google-
        # resolved name, keep whichever scores higher. The raw input is
        # almost always Chinese (matching DB script) and is the strongest
        # signal of what the user actually meant.
        all_rows = await _fetch_all(session)
        if not all_rows:
            return MatchResult(status="unknown", match=None)

        queries = []
        if len(name.strip()) >= MIN_GLOBAL_QUERY_LEN:
            queries.append(name.strip())
        if (
            len(resolved.name.strip()) >= MIN_GLOBAL_QUERY_LEN
            and resolved.name.strip() != name.strip()
        ):
            queries.append(resolved.name.strip())

        best_hit: tuple[dict, float] | None = None
        for q in queries:
            h = _fuzz_pick(
                q, all_rows, SCORE_THRESHOLD_GLOBAL, scorer=fuzz.WRatio,
            )
            if h is None:
                continue
            if best_hit is None or h[1] > best_hit[1]:
                best_hit = h
        if best_hit is not None:
            row, score = best_hit
            return MatchResult(status="legal", match=row, score=score)

        alternatives = await _fetch_nearest(
            session, resolved.lat, resolved.lng, limit=3
        )
        return MatchResult(
            status="illegal", match=None, alternatives=alternatives
        )


def _fuzz_pick(
    name: str,
    rows: list[dict],
    cutoff: int,
    scorer=fuzz.WRatio,
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


async def _fetch_by_place_id(session, place_id: str) -> dict | None:
    result = await session.execute(
        text(
            "SELECT id, name, address, lat, lng "
            "FROM legal_hotels WHERE google_place_id = :pid"
        ),
        {"pid": place_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


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


__all__ = [
    "MatchResult",
    "ResolvedPlace",
    "SCORE_THRESHOLD_GLOBAL",
    "MIN_GLOBAL_QUERY_LEN",
    "match_hotel",
]
