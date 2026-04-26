"""Ingest backend/data/legal_hotels.csv into the legal_hotels table (spec M4.1).

Run:
    python scripts/ingest_hotels.py

Required env (loaded from project-root .env if present):
    DATABASE_URL

The CSV is produced by `scripts/fetch_hotels.py` and committed to the repo,
so this script is fully offline and runs in seconds — no data.taipei or
geocoder calls happen here.

Upsert key: `(name, address)` UNIQUE constraint (alembic 0005). Re-runs
preserve lat/lng/google_place_id values populated by
scripts/regeocode_hotels_google.py — only metadata (hotel_type, source,
raw_data, updated_at) is refreshed.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path

import asyncpg

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
CSV_PATH = ROOT / "data" / "legal_hotels.csv"


def to_asyncpg_dsn(url: str) -> str:
    """SQLAlchemy uses 'postgresql+asyncpg://...'; asyncpg wants plain 'postgresql://...'."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


def load_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "name": row["name"],
                    "address": row["address"],
                    "lat": float(row["lat"]) if row["lat"] else None,
                    "lng": float(row["lng"]) if row["lng"] else None,
                    "license_number": row["license_number"] or None,
                    "hotel_type": row["hotel_type"] or None,
                    "source": row["source"] or None,
                    "raw_data": (
                        json.loads(row["raw_data"]) if row["raw_data"] else None
                    ),
                }
            )
    return rows


async def upsert(
    conn: asyncpg.Connection, rows: list[dict]
) -> tuple[int, int]:
    """Single upsert path keyed on (name, address).

    On conflict only metadata (license_number / hotel_type / source / raw_data
    / updated_at) is refreshed. lat/lng/google_place_id are *not* touched —
    those belong to the post-ingest Google re-geocode and would be expensive
    to redo.
    """
    sql = """
        INSERT INTO legal_hotels
            (name, address, lat, lng, license_number,
             hotel_type, source, raw_data, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
        ON CONFLICT (name, address) DO UPDATE SET
            license_number = COALESCE(
                legal_hotels.license_number, EXCLUDED.license_number
            ),
            hotel_type = EXCLUDED.hotel_type,
            source     = EXCLUDED.source,
            raw_data   = EXCLUDED.raw_data,
            updated_at = NOW()
        RETURNING (xmax = 0) AS inserted
    """
    inserted = 0
    updated = 0
    for r in rows:
        raw = (
            json.dumps(r["raw_data"], ensure_ascii=False)
            if r["raw_data"] is not None
            else None
        )
        row = await conn.fetchrow(
            sql,
            r["name"], r["address"], r["lat"], r["lng"],
            r["license_number"], r["hotel_type"], r["source"], raw,
        )
        if row and row["inserted"]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


async def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1
    if not CSV_PATH.exists():
        print(
            f"ERROR: {CSV_PATH} not found. Run scripts/fetch_hotels.py first.",
            file=sys.stderr,
        )
        return 1

    rows = load_csv(CSV_PATH)
    print(f"[load] {len(rows)} rows from {CSV_PATH.relative_to(PROJECT_ROOT)}")

    conn = await asyncpg.connect(to_asyncpg_dsn(DATABASE_URL))
    try:
        inserted, updated = await upsert(conn, rows)
    finally:
        await conn.close()

    print(
        f"[upsert] inserted {inserted}, updated {updated}, "
        f"total {inserted + updated}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
