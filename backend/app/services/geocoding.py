"""Google Maps Geocoding wrapper (spec M3.2).

只供 M3 使用。把使用者輸入的地點名稱（可能含模糊地址線索）轉為座標。
"""
from __future__ import annotations

import httpx

from app.config import settings

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_TIMEOUT = 10.0


class GeocodingError(Exception):
    """Geocoding 失敗（找不到、API key 無效、網路錯誤）。"""


async def geocode(name: str, address_hint: str = "") -> tuple[float, float]:
    """把地點名稱轉為 (lat, lng)。

    query 統一加上「台北市」，並用 region=tw + zh-TW 提升命中率。
    任何失敗（results 為空、網路錯誤、API error）都拋 GeocodingError。
    """
    query = f"{name} {address_hint} 台北市".strip()
    params = {
        "address": query,
        "language": "zh-TW",
        "region": "tw",
        "key": settings.GOOGLE_MAPS_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_GEOCODE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise GeocodingError(f"geocoding 網路或解析失敗: {e}") from e

    status = data.get("status")
    results = data.get("results") or []
    if status != "OK" or not results:
        raise GeocodingError(f"找不到: {name} (status={status})")

    loc = results[0].get("geometry", {}).get("location", {})
    lat = loc.get("lat")
    lng = loc.get("lng")
    if lat is None or lng is None:
        raise GeocodingError(f"geocoding 結果無座標: {name}")
    return float(lat), float(lng)
