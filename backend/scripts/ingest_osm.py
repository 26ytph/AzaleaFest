"""M1: Overpass → attractions ingest (spec M1.2, resilient variant).

執行方式（推薦）:
    docker compose run --rm backend python scripts/ingest_osm.py

兩階段設計:
  Phase 1: Fetch Overpass → insert 所有 row（embedding=NULL）。
           即使 Gemini 整個壞掉，POI 資料一定先進 DB，M2/M3/M4 不會被擋。
  Phase 2: 查 embedding IS NULL 的 row，batch 過 Gemini，逐個更新。
           單一 batch 失敗 → log 後 skip，下次 re-run 自動續做。

可隨時 Ctrl-C 中斷再 re-run，是 idempotent 的。

需要環境變數: DATABASE_URL, GEMINI_API_KEY
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path

import httpx

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models.attraction import Attraction
from app.services.embedder import embed_batch

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

HTTP_HEADERS = {
    "User-Agent": "AzaleaFest-WanderGuard/1.0 (M1 OSM ingest; hackathon)",
    "Accept": "application/json,*/*",
}

OVERPASS_QUERY = """
[out:json][timeout:120];
area["name"="臺北市"]["admin_level"="4"]->.taipei;
(
  nwr["amenity"~"^(restaurant|cafe|bar|fast_food|food_court|ice_cream)$"](area.taipei);
  nwr["tourism"~"^(attraction|museum|gallery|viewpoint|theme_park)$"](area.taipei);
  nwr["leisure"~"^(park|garden|sports_centre)$"](area.taipei);
  nwr["shop"~"^(mall|department_store|market)$"](area.taipei);
);
out center;
"""

# OSM node/way/relation ID 各自獨立編號，會撞（例如 node 12345 跟 way 12345 同時存在）。
# 為了塞進單欄 BIGINT UNIQUE，way/relation 加上大型 offset。
# Node id 上限約 1.2e10，way 約 1.4e9，relation 約 1.7e7；offset 1e14 / 2e14 完全不會撞。
_TYPE_ID_OFFSET = {"node": 0, "way": 10**14, "relation": 2 * 10**14}

# 第二個 attraction 來源：交通部觀光署（Tourism Bureau）官方景點資料集，每日更新。
# 涵蓋全台 ~5000 景點，台北市約 436 筆，含完整經緯度、描述、地址、分類。
# osm_id offset 3e14，與 OSM 各 type 區隔。
TRAVEL_TAIWAN_URL = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.json"
_TRAVEL_TAIWAN_ID_OFFSET = 3 * 10**14
_TARGET_REGION = "臺北市"

TAG_TO_CATEGORY: dict[str, str] = {
    "restaurant": "food", "cafe": "food", "bar": "food",
    "fast_food": "food", "food_court": "food", "ice_cream": "food",
    "attraction": "attraction", "museum": "attraction", "gallery": "attraction",
    "viewpoint": "attraction", "theme_park": "attraction",
    "park": "attraction", "garden": "attraction", "sports_centre": "attraction",
    "mall": "attraction", "department_store": "attraction", "market": "food",
}

_TAG_KEYS_IN_ORDER = ("amenity", "tourism", "leisure", "shop")
_DESC_KEYS = ("cuisine", "opening_hours", "wheelchair", "phone", "website")
_DB_INSERT_CHUNK = 200
_EMBED_BATCH = 100
# 連續這麼多次整 batch 全失敗 → 認定 quota 短期內不會回，提早收工等下次 re-run
_GIVEUP_AFTER_FAILS = 5


def parse_osm_element(el: dict) -> dict | None:
    try:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:zh")
        if not name:
            return None

        category: str | None = None
        primary_tag_value: str | None = None
        for k in _TAG_KEYS_IN_ORDER:
            v = tags.get(k)
            if v and v in TAG_TO_CATEGORY:
                category = TAG_TO_CATEGORY[v]
                primary_tag_value = v
                break
        if category is None:
            return None

        # Node 直接帶 lat/lon；way/relation 經 `out center` 後座標在 el["center"]
        lat = el.get("lat")
        lng = el.get("lon")
        if lat is None or lng is None:
            center = el.get("center") or {}
            lat = center.get("lat")
            lng = center.get("lon")
        if lat is None or lng is None:
            return None

        raw_id = el.get("id")
        osm_type = el.get("type", "node")
        offset = _TYPE_ID_OFFSET.get(osm_type, 0)
        encoded_osm_id = raw_id + offset if raw_id is not None else None

        desc_parts = [f"{k}={tags[k]}" for k in _DESC_KEYS if tags.get(k)]
        description = "; ".join(desc_parts) if desc_parts else None

        addr = (
            tags.get("addr:full")
            or " ".join(
                p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p
            )
            or None
        )

        tag_list = [primary_tag_value]
        if tags.get("cuisine"):
            tag_list.append(tags["cuisine"])

        return {
            "osm_id": encoded_osm_id,
            "name": name,
            "name_en": tags.get("name:en"),
            "category": category,
            "lat": float(lat),
            "lng": float(lng),
            "address": addr,
            "description": description,
            "tags": tag_list,
            "source": "osm",
        }
    except (KeyError, TypeError, ValueError):
        return None


def build_embed_text(row: dict) -> str:
    name = row["name"]
    category = row["category"]
    address = row.get("address") or ""
    description = row.get("description") or ""
    tags_joined = " ".join(row.get("tags") or [])
    return f"{name}。{category}。{address}。{description}。{tags_joined}"


def _stable_id(text: str, offset: int) -> int:
    """把任意字串 ID 穩定 hash 成 BIGINT 內的數字 + offset。"""
    h = hashlib.md5(text.encode("utf-8")).digest()
    # 取前 6 bytes，最大 ~2.8e14，落在 offset 預留的 1e14 區間內也 OK
    return offset + int.from_bytes(h[:6], "big")


def parse_travel_taiwan_item(item: dict) -> dict | None:
    """中央觀光署景點 JSON → row dict。回傳 None 表示跳過。"""
    try:
        if (item.get("Region") or "").strip() != _TARGET_REGION:
            return None
        name = (item.get("Name") or "").strip()
        if not name:
            return None
        # 名稱常見「景點名_別名」格式，取主名
        name = name.split("_")[0].strip() or name

        try:
            lat = float(item["Py"])
            lng = float(item["Px"])
        except (KeyError, TypeError, ValueError):
            return None
        if lat == 0 or lng == 0:
            return None

        desc = (item.get("Toldescribe") or item.get("Description") or "").strip() or None
        addr = (item.get("Add") or "").strip() or None

        # 組 tags: 區/分類/keyword 摘要，給 embedding 用
        tag_list: list[str] = []
        town = (item.get("Town") or "").strip()
        if town:
            tag_list.append(town)
        if item.get("Class1"):
            tag_list.append(f"class{item['Class1']}")
        if item.get("Orgclass"):
            tag_list.append(item["Orgclass"])
        kw = (item.get("Keyword") or "").strip()
        if kw:
            tag_list.append(kw)

        return {
            "osm_id": _stable_id(item.get("Id", name), _TRAVEL_TAIWAN_ID_OFFSET),
            "name": name,
            "name_en": None,
            "category": "attraction",
            "lat": lat,
            "lng": lng,
            "address": addr,
            "description": desc,
            "tags": tag_list or None,
            "source": "travel_taiwan",
        }
    except (KeyError, TypeError, ValueError):
        return None


async def fetch_travel_taiwan_data() -> list[dict]:
    """下載觀光署景點 JSON，回傳完整 list（未過濾）。失敗拋 RuntimeError。"""
    last_err: Exception | None = None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(180.0), headers=HTTP_HEADERS
    ) as client:
        for attempt in (1, 2):
            try:
                resp = await client.get(TRAVEL_TAIWAN_URL)
                resp.raise_for_status()
                # 該檔以 BOM (utf-8-sig) 開頭，httpx 直接 .json() 會炸
                text = resp.content.decode("utf-8-sig")
                import json as _json
                data = _json.loads(text)
                return data["XML_Head"]["Infos"]["Info"]
            except (httpx.HTTPError, ValueError, KeyError) as e:
                last_err = e
                if attempt == 1:
                    await asyncio.sleep(15)
    raise RuntimeError(f"travel.taiwan fetch failed: {last_err}") from last_err


async def fetch_osm_data() -> list[dict]:
    last_err: Exception | None = None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(180.0), headers=HTTP_HEADERS
    ) as client:
        for attempt in (1, 2):
            try:
                resp = await client.post(OVERPASS_URL, data={"data": OVERPASS_QUERY})
                resp.raise_for_status()
                return resp.json().get("elements", [])
            except (httpx.HTTPError, ValueError) as e:
                last_err = e
                if attempt == 1:
                    await asyncio.sleep(30)
    raise RuntimeError(f"Overpass fetch failed: {last_err}") from last_err


async def batch_embed(texts: list[str]) -> list[list[float]]:
    """spec M1.2 在 script 內定義的批次入口，實際 forward 到共用 embedder。"""
    return await embed_batch(texts)


def _cleanup_tmp() -> None:
    """spec 要求清理暫存；M1 自身不產 /tmp 檔，這是給 M2 的鉤子（no-op）。"""
    return None


# ---------- Phase 1: insert rows with NULL embedding ----------

async def _insert_rows_no_embedding(rows: list[dict]) -> int:
    """寫入所有 row（embedding=NULL）。ON CONFLICT (osm_id) DO NOTHING。"""
    inserted = 0
    async with SessionLocal() as session:
        for i in range(0, len(rows), _DB_INSERT_CHUNK):
            chunk = rows[i : i + _DB_INSERT_CHUNK]
            stmt = pg_insert(Attraction).values(chunk).on_conflict_do_nothing(
                index_elements=["osm_id"]
            )
            result = await session.execute(stmt)
            await session.commit()
            inserted += result.rowcount or 0
    return inserted


# ---------- Phase 2: backfill embeddings for rows where embedding IS NULL ----------

async def _select_pending() -> list[dict]:
    """挑出尚未 embed 的 row，組裝 embed input 需要的欄位。"""
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                Attraction.id,
                Attraction.name,
                Attraction.category,
                Attraction.address,
                Attraction.description,
                Attraction.tags,
            ).where(Attraction.embedding.is_(None))
        )
        rows = []
        for r in result.all():
            rows.append({
                "id": r[0],
                "name": r[1],
                "category": r[2],
                "address": r[3],
                "description": r[4],
                "tags": r[5],
            })
        return rows


async def _count_embedded() -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.count()).select_from(Attraction).where(
                Attraction.embedding.is_not(None)
            )
        )
        return int(result.scalar_one())


async def _update_embeddings(chunk: list[dict], vectors: list[list[float]]) -> None:
    async with SessionLocal() as session:
        for r, v in zip(chunk, vectors, strict=True):
            await session.execute(
                update(Attraction).where(Attraction.id == r["id"]).values(embedding=v)
            )
        await session.commit()


async def _backfill_embeddings(pending: list[dict]) -> tuple[int, int]:
    """逐 batch 跑 embedder。失敗的 batch 直接 skip 不 crash，下次 re-run 會回來。"""
    embedded = 0
    skipped = 0
    consecutive_fails = 0
    total = len(pending)
    total_batches = (total + _EMBED_BATCH - 1) // _EMBED_BATCH

    for batch_idx, i in enumerate(range(0, total, _EMBED_BATCH), start=1):
        chunk = pending[i : i + _EMBED_BATCH]
        texts = [build_embed_text(r) for r in chunk]
        try:
            vectors = await batch_embed(texts)
        except Exception as e:
            consecutive_fails += 1
            skipped += len(chunk)
            print(
                f"[backfill] batch {batch_idx}/{total_batches} FAILED "
                f"({type(e).__name__}); will retry on next run. "
                f"consecutive_fails={consecutive_fails}",
                flush=True,
            )
            if consecutive_fails >= _GIVEUP_AFTER_FAILS:
                remaining = total - (embedded + skipped)
                print(
                    f"[backfill] {_GIVEUP_AFTER_FAILS} consecutive failures "
                    f"— quota likely exhausted. Aborting; {remaining} rows untouched. "
                    f"Re-run later.",
                    flush=True,
                )
                break
            continue

        consecutive_fails = 0
        await _update_embeddings(chunk, vectors)
        embedded += len(chunk)
        if batch_idx % 5 == 0 or batch_idx == total_batches:
            print(
                f"[backfill] batch {batch_idx}/{total_batches} done "
                f"(embedded={embedded}, skipped={skipped})",
                flush=True,
            )

    return embedded, skipped


async def ingest() -> None:
    t0 = time.monotonic()

    # ---- Phase 1a: OSM ----
    elements = await fetch_osm_data()
    print(f"Phase 1a | OSM: fetched {len(elements)} elements", flush=True)

    seen_ids: set[int] = set()
    parsed: list[dict] = []
    for el in elements:
        row = parse_osm_element(el)
        if row is None or row["osm_id"] in seen_ids:
            continue
        seen_ids.add(row["osm_id"])
        parsed.append(row)
    osm_count = len(parsed)
    print(f"Phase 1a | OSM: {osm_count} valid rows after parse + dedupe", flush=True)

    # ---- Phase 1b: Taiwan Tourism Bureau (中央觀光署) ----
    try:
        tw_items = await fetch_travel_taiwan_data()
        print(
            f"Phase 1b | TWBureau: fetched {len(tw_items)} (全台) items",
            flush=True,
        )
        for it in tw_items:
            row = parse_travel_taiwan_item(it)
            if row is None or row["osm_id"] in seen_ids:
                continue
            seen_ids.add(row["osm_id"])
            parsed.append(row)
        tw_count = len(parsed) - osm_count
        print(
            f"Phase 1b | TWBureau: {tw_count} valid Taipei rows added",
            flush=True,
        )
    except Exception as e:
        print(
            f"Phase 1b | TWBureau fetch FAILED ({type(e).__name__}); "
            f"continuing with OSM only",
            flush=True,
        )

    inserted = await _insert_rows_no_embedding(parsed)
    elapsed_p1 = int(time.monotonic() - t0)
    print(
        f"Phase 1 | Total valid: {len(parsed)} | New rows inserted: {inserted} "
        f"| Time: {elapsed_p1}s",
        flush=True,
    )

    # ---- Phase 2 ----
    if os.environ.get("SKIP_EMBED") == "1":
        print("Phase 2 | SKIP_EMBED=1 set, skipping embedding backfill", flush=True)
        elapsed = int(time.monotonic() - t0)
        print(f"DONE (phase 1 only) | total_rows: {len(parsed)} | Time: {elapsed}s", flush=True)
        return

    t1 = time.monotonic()
    pending = await _select_pending()
    if not pending:
        print("Phase 2 | nothing pending — all rows already have embedding", flush=True)
    else:
        print(
            f"Phase 2 | {len(pending)} rows need embedding "
            f"(batch={_EMBED_BATCH}, may take a while due to free-tier rate limit)",
            flush=True,
        )
        embedded, skipped = await _backfill_embeddings(pending)
        elapsed_p2 = int(time.monotonic() - t1)
        print(
            f"Phase 2 | Embedded: {embedded} | Skipped (quota): {skipped} | "
            f"Time: {elapsed_p2}s",
            flush=True,
        )

    _cleanup_tmp()

    total_with_embedding = await _count_embedded()
    elapsed = int(time.monotonic() - t0)
    print(
        f"DONE | total_rows: {len(parsed)} | with_embedding: {total_with_embedding} "
        f"| Time: {elapsed}s",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(ingest())
