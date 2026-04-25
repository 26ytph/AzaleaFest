"""Ingest legal hotels from Taipei open data into legal_hotels table (spec M4.1).

Run:
    python scripts/ingest_hotels.py

Required env (loaded from project-root .env if present):
    DATABASE_URL
    GOOGLE_MAPS_API_KEY

Sources & exact field schemas (no fallbacks):

    1. 臺北市一般旅館名冊 — dataset 4d7d0b46-2e90-4ee7-b000-c0f2f3a37651
       fields: _id, 縣市代碼, 專用標識編號, 旅館名稱, 電話或手機號碼,
               營業地址, 客房最低定價, 客房最高定價, 房間數
       → name=旅館名稱, address=營業地址, license_number=專用標識編號

    2. 臺北市臺北旅遊網住宿資料(中文) — dataset 58093ba6-4c98-4148-b27a-50ad97d7afca
       fields: _id, 旅館類別, 旅宿名稱, 地址, 電話或手機號碼, 傳真, 房間數
       → name=旅宿名稱, address=地址, hotel_type=旅館類別 (no license_number)

Pipeline:
    fetch (paged) -> normalize -> geocode lat/lng -> upsert.

Per spec, this script depends only on httpx + asyncpg + stdlib so it can be
run standalone without the FastAPI app context.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Callable

import asyncpg
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

DATABASE_URL = os.environ.get("DATABASE_URL", "")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

DATASET_URL = "https://data.taipei/api/v1/dataset/{}"
PAGE_SIZE = 1000
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def _clean(record: dict, key: str) -> str | None:
    """Read a string field; return None for missing or whitespace-only values."""
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
        "4d7d0b46-2e90-4ee7-b000-c0f2f3a37651",
        "一般旅館",
        normalize_general_hotels,
    ),
    (
        "58093ba6-4c98-4148-b27a-50ad97d7afca",
        "旅遊網住宿",
        normalize_travel_hotels,
    ),
]


async def fetch_dataset(
    client: httpx.AsyncClient, dataset_id: str, label: str
) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        resp = await client.get(
            DATASET_URL.format(dataset_id),
            params={"format": "json", "limit": PAGE_SIZE, "offset": offset},
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


async def geocode(
    client: httpx.AsyncClient, query: str
) -> tuple[float | None, float | None]:
    if not GOOGLE_MAPS_API_KEY:
        return None, None
    try:
        resp = await client.get(
            GEOCODE_URL,
            params={
                "address": query,
                "language": "zh-TW",
                "region": "tw",
                "key": GOOGLE_MAPS_API_KEY,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except httpx.HTTPError:
        return None, None
    results = data.get("results") or []
    if not results:
        return None, None
    loc = (results[0].get("geometry") or {}).get("location") or {}
    return loc.get("lat"), loc.get("lng")


def to_asyncpg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def upsert(conn: asyncpg.Connection, rows: list[dict]) -> tuple[int, int]:
    """Upsert by license_number per spec M4.1.

    Rows without a license_number have nothing to conflict on, so they're
    inserted unconditionally (each run will re-insert them — acceptable
    because the script is intended to run rarely).
    """
    sql_with_license = """
        INSERT INTO legal_hotels
            (name, address, lat, lng, license_number,
             hotel_type, source, raw_data, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
        ON CONFLICT (license_number) DO UPDATE SET updated_at = NOW()
        RETURNING (xmax = 0) AS inserted
    """
    sql_no_license = """
        INSERT INTO legal_hotels
            (name, address, lat, lng, license_number,
             hotel_type, source, raw_data, updated_at)
        VALUES ($1, $2, $3, $4, NULL, $5, $6, $7::jsonb, NOW())
    """
    inserted = 0
    updated = 0
    for r in rows:
        raw = json.dumps(r["raw_data"], ensure_ascii=False)
        if r["license_number"]:
            row = await conn.fetchrow(
                sql_with_license,
                r["name"], r["address"], r["lat"], r["lng"],
                r["license_number"], r["hotel_type"], r["source"], raw,
            )
            if row and row["inserted"]:
                inserted += 1
            else:
                updated += 1
        else:
            await conn.execute(
                sql_no_license,
                r["name"], r["address"], r["lat"], r["lng"],
                r["hotel_type"], r["source"], raw,
            )
            inserted += 1
    return inserted, updated


async def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    normalized_records: list[dict] = []
    async with httpx.AsyncClient() as client:
        for ds_id, label, normalizer in DATASETS:
            try:
                rows = await fetch_dataset(client, ds_id, label)
            except httpx.HTTPError as e:
                print(f"[fetch] {label} failed: {e}", file=sys.stderr)
                continue
            kept = 0
            for r in rows:
                n = normalizer(r)
                if n is not None:
                    normalized_records.append(n)
                    kept += 1
            print(f"[normalize] {label}: kept {kept}/{len(rows)}")

        # Dedupe across the two datasets by (name, address) — first wins,
        # so 一般旅館 (which carries license_number) takes precedence.
        seen: dict[tuple[str, str], dict] = {}
        for n in normalized_records:
            seen.setdefault((n["name"], n["address"]), n)
        normalized = list(seen.values())
        print(f"[normalize] {len(normalized)} unique rows after dedupe")

        geocoded = 0
        failed = 0
        for n in normalized:
            lat, lng = await geocode(client, f"{n['address']} {n['name']}")
            if lat is not None and lng is not None:
                n["lat"], n["lng"] = lat, lng
                geocoded += 1
            else:
                failed += 1
            await asyncio.sleep(0.1)
        print(f"[geocode] success {geocoded}, failed {failed}")

    conn = await asyncpg.connect(to_asyncpg_dsn(DATABASE_URL))
    try:
        inserted, updated = await upsert(conn, normalized)
    finally:
        await conn.close()

    print(
        f"[upsert] inserted {inserted}, updated {updated}, "
        f"total {inserted + updated}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
