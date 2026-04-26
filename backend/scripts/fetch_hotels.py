"""Fetch Taipei legal-hotel data → backend/data/legal_hotels.csv (no geocoding).

Run:
    python scripts/fetch_hotels.py

This script ONLY pulls and normalizes the data.taipei list. It writes the
CSV with `lat`/`lng` left blank — coordinates are filled in afterwards by
`scripts/regeocode_hotels_google.py` via Google Places API v1, which lands
authoritative coordinates and a `google_place_id` directly on the
`legal_hotels` rows after `ingest_hotels.py` has loaded them.

Source (single — see history note below):

    臺北市臺北旅遊網住宿資料(中文)
        dataset id : 58093ba6-4c98-4148-b27a-50ad97d7afca (landing page)
        resource id: adb6f5a6-3541-479a-bb32-d5be17eaa95b (API rid)
        fields used: 旅宿名稱, 地址, 旅館類別
        size       : ~619 rows

Why only one dataset: 旅遊網住宿 is effectively a superset of 臺北市一般旅館
名冊 (~582 rows). They use slightly different naming/address formatting,
so a (name, address) dedupe across the two sources doesn't actually
collapse the overlap, and we end up with ~1200 phantom rows for ~619
real hotels. Truth set = 旅遊網住宿.

The data.taipei v1 API requires `scope=resourceAquire` (their typo, not ours)
and the *resource* id, not the dataset id.

Pipeline:
    1. Fetch the dataset, normalize, dedupe by (name, address).
    2. Write the result back to CSV (sorted, deterministic) with empty
       lat/lng columns.

Depends only on httpx + stdlib (no DB, no third-party geocoder).
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Callable

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


def load_cache(path: Path) -> dict[tuple[str, str], dict]:
    """Read an existing CSV into {(name, address): row}.

    Kept so tests can roundtrip writes/reads. Coordinates may be present
    from older runs but are no longer authoritative — the Google
    re-geocode step on the live DB is the source of truth post-ingest.
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

    # Dedupe by (name, address) — first occurrence wins, so 一般旅館
    # (which carries license_number) takes precedence over 旅遊網住宿.
    seen: dict[tuple[str, str], dict] = {}
    for n in normalized:
        seen.setdefault((n["name"], n["address"]), n)
    unique = list(seen.values())
    print(f"[normalize] {len(unique)} unique after dedupe")

    write_csv(CSV_PATH, unique)
    print(f"[write] {len(unique)} rows -> {CSV_PATH.relative_to(PROJECT_ROOT)}")
    print(
        "[next] run scripts/ingest_hotels.py then "
        "scripts/regeocode_hotels_google.py to fill lat/lng + google_place_id"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
