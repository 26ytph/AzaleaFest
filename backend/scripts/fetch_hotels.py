"""Fetch Taipei legal-hotel data + Mapbox geocode → backend/data/legal_hotels.csv.

Run:
    python scripts/fetch_hotels.py

Required env (loaded from project-root .env if present):
    NEXT_PUBLIC_MAPBOX_TOKEN  (same token the frontend uses for the Mapbox map)

Sources & exact field schemas (no fallbacks):

    1. 臺北市一般旅館名冊
         dataset id : 4d7d0b46-2e90-4ee7-b000-c0f2f3a37651 (landing page)
         resource id: 3cea29db-66b1-4ab5-886c-4cafd3e1dcbc (API rid)
         fields used: 旅館名稱, 營業地址, 專用標識編號

    2. 臺北市臺北旅遊網住宿資料(中文)
         dataset id : 58093ba6-4c98-4148-b27a-50ad97d7afca (landing page)
         resource id: adb6f5a6-3541-479a-bb32-d5be17eaa95b (API rid)
         fields used: 旅宿名稱, 地址, 旅館類別

The data.taipei v1 API requires `scope=resourceAquire` (their typo, not ours)
and the *resource* id, not the dataset id.

Pipeline:
    1. Load existing CSV (if any) → cache of (name, address) → lat/lng.
    2. Fetch both data.taipei datasets, normalize, dedupe by (name, address).
    3. For rows without cached lat/lng, hit Mapbox Geocoding once each (0.2s
       gap → 5 req/sec, well under Mapbox's 600 req/min limit).
    4. Write the merged result back to CSV (sorted, deterministic).

Subsequent runs only geocode rows new since the last run, so the CSV is the
durable artifact and Mapbox usage stays minimal (and within free tier).

Why Mapbox and not Nominatim/Photon: from this network (WSL2 NAT), the OSM
public Nominatim instance returns 429 immediately and Photon returns 0 hits
for Taipei street addresses in Chinese. Mapbox resolved 4/4 test addresses.

Depends only on httpx + stdlib (no DB).
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "legal_hotels.csv"

DATASET_URL = "https://data.taipei/api/v1/dataset/{}"
PAGE_SIZE = 1000

MAPBOX_TOKEN = os.environ.get("NEXT_PUBLIC_MAPBOX_TOKEN", "")
MAPBOX_URL_PREFIX = "https://api.mapbox.com/geocoding/v5/mapbox.places/"
# Mapbox limit is 600 req/min (10/sec); 0.2s margin keeps us well under.
MAPBOX_INTERVAL_SEC = 0.2

CSV_FIELDS = [
    "name", "address", "lat", "lng",
    "license_number", "hotel_type", "source", "raw_data",
]


def _clean(record: dict, key: str) -> str | None:
    """Read a string field; None for missing/whitespace-only values."""
    v = record.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def normalize_general_hotels(record: dict) -> dict | None:
    """臺北市一般旅館名冊."""
    name = _clean(record, "旅館名稱")
    address = _clean(record, "營業地址")
    if not name or not address:
        return None
    return {
        "name": name,
        "address": address,
        "license_number": _clean(record, "專用標識編號"),
        "hotel_type": None,
        "lat": None,
        "lng": None,
        "source": "一般旅館",
        "raw_data": record,
    }


def normalize_travel_hotels(record: dict) -> dict | None:
    """臺北市臺北旅遊網住宿資料(中文)."""
    name = _clean(record, "旅宿名稱")
    address = _clean(record, "地址")
    if not name or not address:
        return None
    return {
        "name": name,
        "address": address,
        "license_number": None,
        "hotel_type": _clean(record, "旅館類別"),
        "lat": None,
        "lng": None,
        "source": "旅遊網住宿",
        "raw_data": record,
    }


DATASETS: list[tuple[str, str, Callable[[dict], dict | None]]] = [
    (
        "3cea29db-66b1-4ab5-886c-4cafd3e1dcbc",
        "一般旅館",
        normalize_general_hotels,
    ),
    (
        "adb6f5a6-3541-479a-bb32-d5be17eaa95b",
        "旅遊網住宿",
        normalize_travel_hotels,
    ),
]


async def fetch_dataset(
    client: httpx.AsyncClient, resource_id: str, label: str
) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        resp = await client.get(
            DATASET_URL.format(resource_id),
            params={
                "scope": "resourceAquire",
                "limit": PAGE_SIZE,
                "offset": offset,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        result = (resp.json() or {}).get("result", {}) or {}
        page = result.get("results") or []
        count = result.get("count") or 0
        if not page:
            break
        rows.extend(page)
        offset += len(page)
        if len(page) < PAGE_SIZE or offset >= count:
            break
    print(f"[fetch] {label}: {len(rows)} rows")
    return rows


async def mapbox_geocode(
    client: httpx.AsyncClient, query: str
) -> tuple[float | None, float | None]:
    """Forward-geocode an address via Mapbox Places API.

    Returns (lat, lng) or (None, None) on miss / network failure / no token.
    Mapbox returns coordinates in [lng, lat] GeoJSON order; we normalize to
    (lat, lng) to match the rest of the codebase.
    """
    if not MAPBOX_TOKEN:
        return None, None
    try:
        url = f"{MAPBOX_URL_PREFIX}{quote(query, safe='')}.json"
        resp = await client.get(
            url,
            params={
                "access_token": MAPBOX_TOKEN,
                "limit": 1,
                "country": "tw",
                "language": "zh-Hant",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except httpx.HTTPError:
        return None, None
    feats = data.get("features") or []
    if not feats:
        return None, None
    coords = (feats[0].get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None, None
    try:
        return float(coords[1]), float(coords[0])
    except (ValueError, TypeError):
        return None, None


def load_cache(path: Path) -> dict[tuple[str, str], dict]:
    """Read an existing CSV into {(name, address): row}.

    Designed so that re-runs reuse already-known lat/lng without hitting
    Nominatim again.
    """
    if not path.exists():
        return {}
    cache: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["name"], row["address"])
            cache[key] = {
                "lat": float(row["lat"]) if row["lat"] else None,
                "lng": float(row["lng"]) if row["lng"] else None,
                "license_number": row.get("license_number") or None,
                "hotel_type": row.get("hotel_type") or None,
                "source": row.get("source") or None,
                "raw_data": (
                    json.loads(row["raw_data"]) if row.get("raw_data") else None
                ),
            }
    return cache


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_sorted = sorted(
        rows, key=lambda r: (r.get("source") or "", r["name"], r["address"])
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in rows_sorted:
            writer.writerow(
                {
                    "name": r["name"],
                    "address": r["address"],
                    "lat": "" if r["lat"] is None else f"{r['lat']:.7f}",
                    "lng": "" if r["lng"] is None else f"{r['lng']:.7f}",
                    "license_number": r["license_number"] or "",
                    "hotel_type": r["hotel_type"] or "",
                    "source": r["source"] or "",
                    "raw_data": (
                        json.dumps(r["raw_data"], ensure_ascii=False)
                        if r["raw_data"] is not None
                        else ""
                    ),
                }
            )


async def main() -> int:
    cache = load_cache(CSV_PATH)
    print(
        f"[cache] loaded {len(cache)} rows from "
        f"{CSV_PATH.relative_to(PROJECT_ROOT)}"
    )

    normalized: list[dict] = []
    async with httpx.AsyncClient() as client:
        for rid, label, normalizer in DATASETS:
            try:
                rows = await fetch_dataset(client, rid, label)
            except httpx.HTTPError as e:
                print(f"[fetch] {label} failed: {e}", file=sys.stderr)
                continue
            kept = 0
            for r in rows:
                n = normalizer(r)
                if n is not None:
                    normalized.append(n)
                    kept += 1
            print(f"[normalize] {label}: kept {kept}/{len(rows)}")

        # Dedupe by (name, address) — first occurrence wins, so
        # 一般旅館 (with license_number) takes precedence.
        seen: dict[tuple[str, str], dict] = {}
        for n in normalized:
            seen.setdefault((n["name"], n["address"]), n)
        unique = list(seen.values())
        print(f"[normalize] {len(unique)} unique after dedupe")

        # Reuse cached coords where available.
        need_geocode = 0
        for n in unique:
            cached = cache.get((n["name"], n["address"]))
            if (
                cached
                and cached["lat"] is not None
                and cached["lng"] is not None
            ):
                n["lat"] = cached["lat"]
                n["lng"] = cached["lng"]
            else:
                need_geocode += 1
        eta_sec = int(need_geocode * MAPBOX_INTERVAL_SEC)
        print(
            f"[geocode] {need_geocode} rows need Mapbox "
            f"(~{eta_sec}s @ {MAPBOX_INTERVAL_SEC}s/req)"
        )
        if need_geocode > 0 and not MAPBOX_TOKEN:
            print(
                "ERROR: NEXT_PUBLIC_MAPBOX_TOKEN not set; cannot geocode.",
                file=sys.stderr,
            )
            return 1

        ok = 0
        fail = 0
        done = 0
        for n in unique:
            if n["lat"] is not None and n["lng"] is not None:
                continue
            lat, lng = await mapbox_geocode(client, n["address"])
            if lat is not None and lng is not None:
                n["lat"], n["lng"] = lat, lng
                ok += 1
            else:
                fail += 1
            done += 1
            if done % 50 == 0:
                print(f"[geocode] {done}/{need_geocode}  ok={ok} fail={fail}")
            await asyncio.sleep(MAPBOX_INTERVAL_SEC)
        print(f"[geocode] success {ok}, failed {fail}")

    write_csv(CSV_PATH, unique)
    print(f"[write] {len(unique)} rows -> {CSV_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
