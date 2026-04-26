"""Re-geocode every legal_hotels row via Google Places API v1.

Run:
    python scripts/regeocode_hotels_google.py

Required env (loaded from project-root .env if present):
    DATABASE_URL
    GOOGLE_MAPS_API_KEY

What it does (per row):
    1. SELECT id, name, address FROM legal_hotels ORDER BY id
    2. resolve_hotel(name, address_hint=address) → ResolvedPlace | None
    3. Hit  → UPDATE lat, lng, google_place_id, updated_at
       Miss → log + skip (existing lat/lng are NOT cleared)
    4. 200 ms sleep between calls (well under v1 QPS allowance)

Idempotent. Re-runs report 0 changes. If a row's resolved place_id ever
changes between runs, an explicit warning is logged for human review.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import asyncpg
import httpx
from asyncpg.exceptions import UniqueViolationError

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

# Make `app.*` importable from a standalone script context.
sys.path.insert(0, str(ROOT))

from app.services.hotel.google_resolver import resolve_hotel  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SLEEP_SEC = 0.2

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("regeocode")


def to_asyncpg_dsn(url: str) -> str:
    """SQLAlchemy URL → plain asyncpg URL."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def main() -> int:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1
    if not os.environ.get("GOOGLE_MAPS_API_KEY"):
        print("ERROR: GOOGLE_MAPS_API_KEY not set", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(to_asyncpg_dsn(DATABASE_URL))
    try:
        rows = await conn.fetch(
            "SELECT id, name, address, google_place_id "
            "FROM legal_hotels ORDER BY id"
        )
        total = len(rows)
        log.info("loaded %d rows from legal_hotels", total)

        hit = 0
        miss = 0
        changed_place_id = 0
        dup_place_id = 0
        async with httpx.AsyncClient() as client:
            for i, row in enumerate(rows, start=1):
                rid = row["id"]
                name = row["name"]
                address = row["address"] or ""
                old_pid = row["google_place_id"]

                resolved = await resolve_hotel(
                    name, address_hint=address, client=client
                )
                if resolved is None:
                    miss += 1
                    log.info("[%d/%d] MISS id=%s name=%r", i, total, rid, name)
                else:
                    if old_pid and old_pid != resolved.place_id:
                        changed_place_id += 1
                        log.warning(
                            "[%d/%d] place_id changed for id=%s name=%r: "
                            "%s → %s",
                            i, total, rid, name, old_pid, resolved.place_id,
                        )
                    # Update lat/lng + place_id together. If the place_id is
                    # already taken by another row (i.e. two source records
                    # describe the same physical hotel — common in 旅遊網住宿
                    # for buildings with multi-floor entries), fall back to
                    # writing only lat/lng. The matcher's fuzz path will
                    # still find the row by name; we just lose the exact-
                    # match fast-path for the duplicate.
                    try:
                        await conn.execute(
                            "UPDATE legal_hotels "
                            "SET lat=$1, lng=$2, google_place_id=$3, "
                            "    updated_at=NOW() "
                            "WHERE id=$4",
                            resolved.lat, resolved.lng,
                            resolved.place_id, rid,
                        )
                    except UniqueViolationError:
                        await conn.execute(
                            "UPDATE legal_hotels "
                            "SET lat=$1, lng=$2, updated_at=NOW() "
                            "WHERE id=$3",
                            resolved.lat, resolved.lng, rid,
                        )
                        dup_place_id += 1
                        log.warning(
                            "[%d/%d] duplicate place_id %s for id=%s name=%r"
                            " — kept lat/lng only, google_place_id left NULL",
                            i, total, resolved.place_id, rid, name,
                        )
                    hit += 1
                    if i % 50 == 0 or i == total:
                        log.info(
                            "[%d/%d] progress hit=%d miss=%d "
                            "changed_pid=%d dup_pid=%d",
                            i, total, hit, miss, changed_place_id,
                            dup_place_id,
                        )

                await asyncio.sleep(SLEEP_SEC)

        log.info(
            "done: total=%d hit=%d miss=%d "
            "changed_place_id=%d dup_place_id=%d",
            total, hit, miss, changed_place_id, dup_place_id,
        )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
