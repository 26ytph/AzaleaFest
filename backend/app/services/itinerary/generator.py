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
from app.services.hotel.google_resolver import resolve_place
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


def _build_prompt_candidates(candidates: list[dict]) -> tuple[list[dict], dict[int, int]]:
    """把 candidates 轉成 prompt 用的版本（id 都換成正整數），並回傳 prompt_id → place_id 對照表。

    Gemini 容易把負數 id 搞錯，所以傳給 prompt 的全用 1-based 正整數，
    normalize 時再透過 id_map 換回原始 place_id。
    """
    prompt_list: list[dict] = []
    id_map: dict[int, int] = {}
    for i, p in enumerate(candidates, start=1):
        id_map[i] = p["place_id"]
        prompt_list.append({**p, "place_id": i})
    return prompt_list, id_map


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
        "嚴格規則（違反會導致行程被丟棄）：\n"
        "- place_id 只能從下方清單挑選；嚴禁自創新 id 或新地點。\n"
        "- 每個 stop 的 name 必須與清單中該 id 的 name 完全一致。\n"
        "- 若清單地點不足以排 5 站以上，請重複利用清單地點，不要編造新地點。\n"
        "- 產出前自我檢查：每個 stop.place_id 都在下方清單中嗎？若否，整段重排。\n\n"
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


_TAIPEI_BBOX_LAT = (24.95, 25.21)
_TAIPEI_BBOX_LNG = (121.45, 121.67)


def _all_candidates_in_taipei(place_lookup: dict[int, dict]) -> bool:
    """所有 candidate 都在台北 bbox 時，外縣市的 Google fallback 應視為跑題。"""
    if not place_lookup:
        return False
    for ref in place_lookup.values():
        lat = ref.get("lat")
        lng = ref.get("lng")
        if lat is None or lng is None:
            return False
        if not (_TAIPEI_BBOX_LAT[0] <= float(lat) <= _TAIPEI_BBOX_LAT[1]):
            return False
        if not (_TAIPEI_BBOX_LNG[0] <= float(lng) <= _TAIPEI_BBOX_LNG[1]):
            return False
    return True


def _stop_from_candidate(
    raw: dict, ref: dict, default_duration: int = 60
) -> dict:
    """命中 candidate：用 DB 的 canonical name/座標/地址，覆寫 Gemini 的 name。"""
    try:
        duration = int(raw.get("duration_min", default_duration))
    except (TypeError, ValueError):
        duration = default_duration
    return {
        "time": str(raw.get("time", "")).strip(),
        "place_id": int(ref["place_id"]),
        "name": str(ref["name"]),
        "duration_min": max(0, duration),
        "transport_to_next": str(raw.get("transport_to_next") or ""),
        "note": str(raw.get("note") or "")[:80],
        "lat": float(ref["lat"]),
        "lng": float(ref["lng"]),
        "address": ref.get("address"),
        "google_place_id": None,
    }


def _stop_from_resolved(raw: dict, resolved: Any) -> dict:
    """Google Places 解析成功：以 Google 結果作為地點來源。place_id=0 為哨兵值。"""
    try:
        duration = int(raw.get("duration_min", 60))
    except (TypeError, ValueError):
        duration = 60
    return {
        "time": str(raw.get("time", "")).strip(),
        "place_id": 0,
        "name": str(resolved.name),
        "duration_min": max(0, duration),
        "transport_to_next": str(raw.get("transport_to_next") or ""),
        "note": str(raw.get("note") or "")[:80],
        "lat": float(resolved.lat),
        "lng": float(resolved.lng),
        "address": resolved.formatted_address or None,
        "google_place_id": resolved.place_id,
    }


async def _normalize_stops(
    raw_stops: list[Any],
    place_lookup: dict[int, dict],
    *,
    allow_google_fallback: bool = True,
) -> list[dict]:
    """把 Gemini 回的 stops 轉成嚴格符合 ItineraryStop 的 dict（含 lat/lng/address）。

    Resolution 三層：
      1. place_id 在 candidate → 用 DB canonical（覆寫 Gemini 的 name），保證真實。
      2. place_id 不在 candidate 但 name 非空 → 呼叫 Google Places 驗證；命中 → 採用。
      3. 否則 drop（log warning，方便日後 grep 幻覺率）。
    """
    normalized: list[dict] = []
    taipei_only = _all_candidates_in_taipei(place_lookup)
    for raw in raw_stops or []:
        if not isinstance(raw, dict):
            continue
        try:
            pid = int(raw.get("place_id"))
        except (TypeError, ValueError):
            pid = None

        if pid is not None and pid in place_lookup:
            normalized.append(_stop_from_candidate(raw, place_lookup[pid]))
            continue

        name = str(raw.get("name") or "").strip()
        if not name or not allow_google_fallback or not settings.GOOGLE_MAPS_API_KEY:
            log.warning(
                "dropped hallucinated stop name=%r pid=%r", raw.get("name"), raw.get("place_id")
            )
            continue

        try:
            resolved = await resolve_place(name)
        except Exception:
            log.exception("resolve_place failed for name=%r", name)
            resolved = None

        if resolved is None:
            log.warning(
                "dropped hallucinated stop name=%r pid=%r (google miss)",
                raw.get("name"),
                raw.get("place_id"),
            )
            continue

        if taipei_only and not resolved.in_taipei:
            log.warning(
                "dropped out-of-taipei google resolution name=%r → %r",
                name,
                resolved.formatted_address,
            )
            continue

        normalized.append(_stop_from_resolved(raw, resolved))
    return normalized


_DURATION_BY_CATEGORY: dict[str, int] = {
    "attraction": 90,
    "food": 60,
    "hotel": 30,
}
_TRANSPORT_BETWEEN_MIN = 15


def _fallback_schedule(places: list[dict], start_time: str) -> dict:
    """Gemini 不可用時的確定性排程：依清單順序分配時間。"""
    try:
        h, m = map(int, start_time.split(":"))
    except (ValueError, AttributeError):
        h, m = 9, 0
    current_min = h * 60 + m

    stops = []
    for i, p in enumerate(places):
        t_h, t_m = divmod(current_min, 60)
        duration = _DURATION_BY_CATEGORY.get(p.get("category", ""), 60)
        is_last = i == len(places) - 1
        next_p = places[i + 1] if not is_last else None
        transport = ""
        if next_p:
            dist = _haversine_km(p["lat"], p["lng"], next_p["lat"], next_p["lng"])
            if dist < 0.5:
                transport = "步行 5 分鐘"
            elif dist < 2:
                transport = f"步行約 {int(dist * 10)} 分鐘"
            else:
                transport = f"MRT / 計程車約 {int(dist * 3)} 分鐘"
        stops.append({
            "time": f"{t_h:02d}:{t_m:02d}",
            "place_id": p["place_id"],
            "name": p["name"],
            "duration_min": duration,
            "transport_to_next": transport,
            "note": "",
            "lat": float(p["lat"]),
            "lng": float(p["lng"]),
            "address": p.get("address"),
            "google_place_id": None,
        })
        current_min += duration + (0 if is_last else _TRANSPORT_BETWEEN_MIN)

    total = sum(s["duration_min"] for s in stops) / 60.0
    return {"stops": stops, "total_duration_hours": round(total, 2)}


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
            Place.id, Place.name, Place.category, Place.lat, Place.lng, Place.address,
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
            "address": r[5],
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
                    "address": a.get("address"),
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
    """呼叫 Gemini，期望回 JSON object。失敗 → 空 schedule。"""
    try:
        from google.genai import types

        client = _get_gemini_client()
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "你是台北旅遊規劃師。只回傳 JSON，不要任何說明文字或 markdown。"
                ),
                response_mime_type="application/json",
                temperature=0.2,
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
        prompt_candidates, id_map = _build_prompt_candidates(candidates)
        prompt_place_lookup = {p["place_id"]: p for p in prompt_candidates}
        prompt = _build_user_prompt(date, start_time, weather, prompt_candidates)
        raw = await _generate_schedule(prompt)
        # 把 Gemini 回傳的 prompt_id 翻譯回真實 place_id
        for stop in raw.get("stops", []):
            if isinstance(stop, dict):
                try:
                    pid = int(stop["place_id"])
                    if pid in id_map:
                        stop["place_id"] = id_map[pid]
                except (KeyError, TypeError, ValueError):
                    pass
    else:
        raw = {}

    stops = await _normalize_stops(raw.get("stops", []), place_lookup)
    if not stops and candidates:
        fallback = _fallback_schedule(candidates, start_time)
        stops = fallback["stops"]
        raw = fallback
    total_hours = _total_duration_hours(stops, raw.get("total_duration_hours"))

    itinerary_id = await _persist_itinerary(
        session_id, candidates, stops, total_hours, weather
    )

    return {
        "id": itinerary_id,
        "stops": stops,
        "total_duration_hours": total_hours,
    }
