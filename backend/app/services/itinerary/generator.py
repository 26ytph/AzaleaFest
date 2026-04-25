"""M7 行程生成服務 (spec M7.1).

入口: `generate(session_id, date, start_time)` → Itinerary dict (對齊 M0.5)

流程:
  1. 撈 session 所有 places（必含）
  2. 透過 M5 find_similar 各 category 各補 2 筆 attraction（軟性，失敗就略過）
  3. 合併 5–10 個地點，附上 stable id（places.id 或 attraction id 加偏移）
  4. CWB 取今日天氣（失敗 → weather=None）
  5. 呼叫 Gemini 2.5 pro 生 JSON 行程
  6. normalize 成 ItineraryStop[]，寫入 itineraries 表回傳

純邏輯（距離計算、prompt 組裝、JSON normalization）拆為私有函式，
方便 test_m7_itinerary.py 不靠 DB / Gemini 也能測得到。
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models.itinerary import Itinerary
from app.models.place import Place
from app.services.rag.recommender import find_similar

log = logging.getLogger(__name__)

_CWB_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
_CWB_LOCATION = "臺北市"
_CWB_TIMEOUT_SEC = 5.0

# Gemini 推薦 attraction 偏移 — 讓 itinerary stop 的 place_id 在 places 與 attractions
# 之間不會撞號。前端 Itinerary 型別只標 place_id: number；負值代表「來自推薦池
# 而非 places 表」，前端可選擇是否點擊跳轉。
_RECOMMENDATION_ID_OFFSET = -1_000_000

# 每個 category 補幾筆推薦
_RECS_PER_CATEGORY = 2
_MAX_TOTAL_PLACES = 10
_RECOMMEND_CATEGORIES = ("food", "attraction")


# ---------------------------------------------------------------------------
# 純邏輯（給 test_m7_itinerary.py 用）
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """大圓距離（公里）。台北市範圍 < 30km，誤差可忽略。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _format_place_line(p: dict) -> str:
    """把單一 place 轉成 prompt 可讀的單行。"""
    return (
        f"- id={p['place_id']}, name={p['name']}, category={p['category']}, "
        f"lat={p['lat']:.4f}, lng={p['lng']:.4f}"
    )


def _build_user_prompt(
    date: str,
    start_time: str,
    weather: dict | None,
    places: list[dict],
) -> str:
    """組 user prompt — LLM 會 reply 結構化 JSON。"""
    weather_line = "天氣資訊：未取得"
    if weather:
        desc = weather.get("description") or ""
        temp = weather.get("temp")
        temp_str = f"，氣溫約 {temp}°C" if temp is not None else ""
        weather_line = f"天氣資訊：{desc}{temp_str}".rstrip()

    place_lines = "\n".join(_format_place_line(p) for p in places)

    return (
        f"請為使用者規劃 {date} 的台北一日行程，從 {start_time} 開始。\n"
        f"{weather_line}\n\n"
        f"可用地點清單（請從這些挑 5–8 個排成一條合理動線；可重新排序、不必全選）：\n"
        f"{place_lines}\n\n"
        "交通時間估算規則（請參考兩點間直線距離）：\n"
        "- 直線距離 < 500m → 步行 5 分鐘\n"
        "- 500m–2km → 步行 10–20 分鐘 或 計程車 5 分鐘\n"
        "- > 2km → 建議 MRT/計程車，每 1km 約 3 分鐘\n\n"
        "請只回傳 JSON，schema 如下（不要任何 markdown 或前後文）：\n"
        "{\n"
        '  "stops": [\n'
        "    {\n"
        '      "time": "09:00",\n'
        '      "place_id": <上面清單中的 id>,\n'
        '      "name": "<地點名稱>",\n'
        '      "duration_min": 60,\n'
        '      "transport_to_next": "步行 8 分鐘",\n'
        '      "note": "建議先去這裡，避開午後雷陣雨"\n'
        "    }\n"
        "  ],\n"
        '  "total_duration_hours": 6.5\n'
        "}\n"
        "規則：\n"
        "- time 用 24 小時制 HH:MM\n"
        "- duration_min 為在該點停留分鐘數\n"
        "- 最後一站的 transport_to_next 設為空字串\n"
        "- note 用繁體中文，20 字以內\n"
    )


def _normalize_stops(
    raw_stops: list[Any], place_lookup: dict[int, dict]
) -> list[dict]:
    """把 Gemini 回的 stops 轉成嚴格符合 ItineraryStop 的 dict.

    過濾掉 LLM 幻想出來、不在 place_lookup 裡的 place_id；缺欄位的補預設值。
    回傳保留 LLM 原本的順序。
    """
    normalized: list[dict] = []
    for raw in raw_stops or []:
        if not isinstance(raw, dict):
            continue
        try:
            pid = int(raw.get("place_id"))
        except (TypeError, ValueError):
            continue
        if pid not in place_lookup:
            continue
        ref = place_lookup[pid]
        try:
            duration = int(raw.get("duration_min", 60))
        except (TypeError, ValueError):
            duration = 60
        normalized.append(
            {
                "time": str(raw.get("time", "")).strip(),
                "place_id": pid,
                "name": str(raw.get("name") or ref["name"]),
                "duration_min": max(0, duration),
                "transport_to_next": str(raw.get("transport_to_next") or ""),
                "note": str(raw.get("note") or "")[:80],
            }
        )
    return normalized


def _total_duration_hours(stops: list[dict], raw_total: Any = None) -> float:
    """LLM 給的 total 若合理就用它；否則由 duration_min 加總。

    Gemini 偶爾算錯/不給，這裡保底成回到 stops 的時數總和。
    """
    if isinstance(raw_total, (int, float)) and raw_total > 0:
        return round(float(raw_total), 2)
    minutes = sum(s.get("duration_min", 0) for s in stops)
    return round(minutes / 60.0, 2)


# ---------------------------------------------------------------------------
# 外部資料源：DB / M5 / CWB
# ---------------------------------------------------------------------------

async def _load_session_places(
    session: AsyncSession, session_id: str
) -> list[dict]:
    rows = await session.execute(
        select(
            Place.id, Place.name, Place.category, Place.lat, Place.lng,
        )
        .where(Place.user_session_id == session_id)
        .order_by(Place.created_at.desc())
    )
    return [
        {
            "place_id": int(r[0]),
            "name": r[1],
            "category": r[2],
            "lat": float(r[3]),
            "lng": float(r[4]),
            "source": "place",
        }
        for r in rows.all()
    ]


async def _gather_recommendations(session_id: str) -> list[dict]:
    """各 category 各補 _RECS_PER_CATEGORY 筆。整段 best-effort，失敗就回空。"""
    out: list[dict] = []
    for category in _RECOMMEND_CATEGORIES:
        try:
            recs = await find_similar(session_id, category, _RECS_PER_CATEGORY)
        except Exception:
            log.exception("find_similar failed for category=%s", category)
            continue
        for r in recs:
            a = r["attraction"]
            out.append(
                {
                    "place_id": _RECOMMENDATION_ID_OFFSET - int(a["id"]),
                    "name": a["name"],
                    "category": a["category"],
                    "lat": float(a["lat"]),
                    "lng": float(a["lng"]),
                    "source": "recommendation",
                }
            )
    return out


def _parse_cwb_payload(payload: dict) -> dict | None:
    """CWB F-C0032-001 → {description, temp}.

    回傳 None 表示無法解析（API 變更或地點不存在）。
    """
    try:
        location = payload["records"]["location"][0]
        elements = {e["elementName"]: e for e in location["weatherElement"]}
        wx = elements["Wx"]["time"][0]["parameter"]["parameterName"]
        temp_min = elements["MinT"]["time"][0]["parameter"]["parameterName"]
        temp_max = elements["MaxT"]["time"][0]["parameter"]["parameterName"]
        return {"description": wx, "temp": f"{temp_min}–{temp_max}"}
    except (KeyError, IndexError, TypeError):
        return None


async def _fetch_weather() -> dict | None:
    """從 CWB 36hr 預報抓今天的 Wx + 溫度。失敗 → None。"""
    if not settings.CWB_API_KEY:
        return None
    params = {
        "Authorization": settings.CWB_API_KEY,
        "locationName": _CWB_LOCATION,
    }
    try:
        async with httpx.AsyncClient(timeout=_CWB_TIMEOUT_SEC) as client:
            resp = await client.get(_CWB_URL, params=params)
            resp.raise_for_status()
            return _parse_cwb_payload(resp.json())
    except Exception:
        log.exception("CWB weather fetch failed")
        return None


# ---------------------------------------------------------------------------
# Gemini 呼叫
# ---------------------------------------------------------------------------

_gemini_client: Any = None


def _get_gemini_client() -> Any:
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


async def _generate_schedule(prompt: str) -> dict:
    """呼叫 Gemini 2.5 pro，期望回 JSON object。失敗 → 空 schedule。"""
    try:
        from google.genai import types

        client = _get_gemini_client()
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "你是台北旅遊規劃師。只回傳 JSON，不要任何說明文字或 markdown。"
                ),
                response_mime_type="application/json",
                temperature=0.5,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except Exception:
        log.exception("gemini itinerary generation failed")
        return {}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def _read_places(session_id: str) -> list[dict]:
    async with SessionLocal() as session:
        return await _load_session_places(session, session_id)


async def _persist_itinerary(
    session_id: str,
    candidates: list[dict],
    stops: list[dict],
    total_hours: float,
    weather: dict | None,
) -> int:
    async with SessionLocal() as session:
        row = Itinerary(
            user_session_id=session_id,
            places_snapshot=candidates,
            schedule={"stops": stops, "total_duration_hours": total_hours},
            weather_context=weather,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return int(row.id)


async def generate(
    session_id: str, date: str, start_time: str = "09:00"
) -> dict:
    """spec M7.1 入口。回傳 Itinerary dict（id + stops + total_duration_hours）。

    若 session 沒有任何 place 也沒有任何推薦 → 回傳空 stops 的 itinerary。
    """
    places = await _read_places(session_id)

    recs = await _gather_recommendations(session_id) if places else []
    candidates = (places + recs)[:_MAX_TOTAL_PLACES]
    place_lookup = {p["place_id"]: p for p in candidates}

    weather = await _fetch_weather()

    if candidates:
        prompt = _build_user_prompt(date, start_time, weather, candidates)
        raw = await _generate_schedule(prompt)
    else:
        raw = {}

    stops = _normalize_stops(raw.get("stops", []), place_lookup)
    total_hours = _total_duration_hours(stops, raw.get("total_duration_hours"))

    itinerary_id = await _persist_itinerary(
        session_id, candidates, stops, total_hours, weather
    )

    return {
        "id": itinerary_id,
        "stops": stops,
        "total_duration_hours": total_hours,
    }
