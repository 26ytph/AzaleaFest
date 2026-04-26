"""Google Places API v1 resolver — disambiguates a hotel-name query
to a specific business (place_id + canonical lat/lng + admin area).

Used by:
  - matcher.match_hotel — primary path replacing the old user-supplied lat/lng
  - scripts/regeocode_hotels_google.py — one-shot backfill of legal_hotels

Why Places v1 :searchText (not legacy Find Place from Text):
  - One call returns id, displayName, formattedAddress, location,
    addressComponents — no follow-up Place Details required to do the
    台北市 admin-area check.
  - Field mask (X-Goog-FieldMask) means we pay only for the fields we use.
  - Google is deprecating legacy Places endpoints; v1 is the going-forward API.

Auth: header `X-Goog-Api-Key: {GOOGLE_MAPS_API_KEY}` (the same key already
used by `app.services.geocoding`).

This module is defensive: any network/JSON/empty-results outcome returns
None, never raises. Callers run inside fire-and-forget contexts (line_handler
hotel verification) where an exception would crash the task.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.addressComponents,places.types"
)
_TIMEOUT_SEC = 10.0

# Bias around central Taipei (~Taipei 101). 15km circle covers the whole
# municipality without restricting — out-of-Taipei queries still resolve,
# which is required for the "outside Taipei → unknown, not illegal" rule.
_TAIPEI_BIAS_CENTER_LAT = 25.04
_TAIPEI_BIAS_CENTER_LNG = 121.56
_TAIPEI_BIAS_RADIUS_M = 15000.0

# Recognised display names for Taipei City across the language variants
# Google may return depending on regionCode/languageCode.
_TAIPEI_NAMES = {"臺北市", "台北市", "Taipei City", "Taipei"}

# Bounding box fallback used when addressComponents is missing or unparsable.
_TAIPEI_BBOX_LAT = (24.95, 25.21)
_TAIPEI_BBOX_LNG = (121.45, 121.67)


@dataclass(frozen=True)
class ResolvedPlace:
    place_id: str
    name: str
    lat: float
    lng: float
    formatted_address: str
    in_taipei: bool


def is_in_taipei(place: dict[str, Any]) -> bool:
    """Return True iff the v1 place payload looks like it sits in Taipei City.

    Primary signal: addressComponents row whose `types` contains
    `administrative_area_level_1` and whose long/short text matches a known
    Taipei name. Authoritative — Google has done the reverse-geocoding.

    Fallback: lat/lng inside the Taipei bbox. Catches the rare case where
    addressComponents is absent or the admin component is missing.

    Both negative → not in Taipei.
    """
    components = place.get("addressComponents") or []
    for comp in components:
        types = comp.get("types") or []
        if "administrative_area_level_1" not in types:
            continue
        long_text = (comp.get("longText") or "").strip()
        short_text = (comp.get("shortText") or "").strip()
        if long_text in _TAIPEI_NAMES or short_text in _TAIPEI_NAMES:
            return True
        # Component said Taipei? we trust it. Component said something
        # else (e.g. 新北市) → not in Taipei, do NOT fall through to bbox
        # (otherwise New Taipei addresses near the Taipei border slip through).
        return False

    # No admin-1 component at all → bbox fallback.
    location = place.get("location") or {}
    lat = location.get("latitude")
    lng = location.get("longitude")
    if lat is None or lng is None:
        return False
    try:
        latf = float(lat)
        lngf = float(lng)
    except (TypeError, ValueError):
        return False
    return (
        _TAIPEI_BBOX_LAT[0] <= latf <= _TAIPEI_BBOX_LAT[1]
        and _TAIPEI_BBOX_LNG[0] <= lngf <= _TAIPEI_BBOX_LNG[1]
    )


def _parse_place(place: dict[str, Any]) -> ResolvedPlace | None:
    place_id = place.get("id")
    location = place.get("location") or {}
    lat = location.get("latitude")
    lng = location.get("longitude")
    if not place_id or lat is None or lng is None:
        return None
    display = place.get("displayName") or {}
    name = display.get("text") or place.get("formattedAddress") or ""
    try:
        latf = float(lat)
        lngf = float(lng)
    except (TypeError, ValueError):
        return None
    return ResolvedPlace(
        place_id=str(place_id),
        name=str(name),
        lat=latf,
        lng=lngf,
        formatted_address=str(place.get("formattedAddress") or ""),
        in_taipei=is_in_taipei(place),
    )


async def resolve_hotel(
    name: str, address_hint: str = "", *, client: httpx.AsyncClient | None = None
) -> ResolvedPlace | None:
    """Resolve a hotel-name query to a specific Google Place.

    Returns None on miss / network failure / missing API key. Never raises.

    `client` is injectable for the re-geocode script (which keeps a single
    long-lived client across thousands of calls); production callers leave
    it None to get a fresh per-request client.
    """
    if not settings.GOOGLE_MAPS_API_KEY:
        log.warning("GOOGLE_MAPS_API_KEY not set; resolve_hotel returns None")
        return None

    text_query = f"{name} {address_hint}".strip()
    if not text_query:
        return None

    body = {
        "textQuery": text_query,
        "languageCode": "zh-TW",
        "regionCode": "tw",
        "maxResultCount": 1,
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": _TAIPEI_BIAS_CENTER_LAT,
                    "longitude": _TAIPEI_BIAS_CENTER_LNG,
                },
                "radius": _TAIPEI_BIAS_RADIUS_M,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    async def _do(c: httpx.AsyncClient) -> ResolvedPlace | None:
        try:
            resp = await c.post(
                _PLACES_URL, json=body, headers=headers, timeout=_TIMEOUT_SEC
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("resolve_hotel(%r): %s", text_query, e)
            return None
        places = payload.get("places") or []
        if not places:
            return None
        return _parse_place(places[0])

    if client is not None:
        return await _do(client)
    async with httpx.AsyncClient() as c:
        return await _do(c)


resolve_place = resolve_hotel
