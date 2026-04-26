"""M7 行程生成 — 純邏輯 + orchestrator 單元測試 (spec M7.1).

整合測試（真 DB + Gemini + CWB）依賴 docker compose、GEMINI_API_KEY、CWB_API_KEY；
跑法寫在檔尾 docstring。

執行:
    cd backend && pytest tests/test_m7_itinerary.py -v
"""
from __future__ import annotations

import math

import pytest

from app.services.itinerary import generator as gen


# ---------------------------------------------------------------------------
# _haversine_km
# ---------------------------------------------------------------------------

def test_haversine_zero_for_same_point():
    assert gen._haversine_km(25.0330, 121.5654, 25.0330, 121.5654) == 0.0


def test_haversine_taipei_101_to_taipei_main_station_about_5km():
    # 信義區 ≈ 25.0330,121.5654; 台北車站 ≈ 25.0478,121.5170。實際 ~5km。
    d = gen._haversine_km(25.0330, 121.5654, 25.0478, 121.5170)
    assert 4.0 < d < 6.0


def test_haversine_symmetric():
    a = gen._haversine_km(25.05, 121.51, 25.10, 121.55)
    b = gen._haversine_km(25.10, 121.55, 25.05, 121.51)
    assert math.isclose(a, b, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_places():
    return [
        {"place_id": 1, "name": "永康牛肉麵", "category": "food",
         "lat": 25.0329, "lng": 121.5299, "source": "place"},
        {"place_id": 2, "name": "象山步道", "category": "attraction",
         "lat": 25.0274, "lng": 121.5707, "source": "place"},
    ]


def test_prompt_contains_date_start_time_and_places(sample_places):
    p = gen._build_user_prompt("2026-05-01", "10:30", None, sample_places)
    assert "2026-05-01" in p
    assert "10:30" in p
    assert "永康牛肉麵" in p
    assert "象山步道" in p
    # ids must be embedded so LLM can reference them in stops
    assert "id=1" in p and "id=2" in p
    # reply schema must be requested as JSON
    assert "JSON" in p
    assert '"stops"' in p
    assert '"total_duration_hours"' in p


def test_prompt_includes_transport_rules(sample_places):
    p = gen._build_user_prompt("2026-05-01", "09:00", None, sample_places)
    assert "500m" in p and "2km" in p
    assert "步行" in p


def test_prompt_weather_none_uses_未取得(sample_places):
    p = gen._build_user_prompt("2026-05-01", "09:00", None, sample_places)
    assert "未取得" in p


def test_prompt_includes_weather_when_given(sample_places):
    p = gen._build_user_prompt(
        "2026-05-01", "09:00",
        {"description": "午後雷陣雨", "temp": "22–28"},
        sample_places,
    )
    assert "午後雷陣雨" in p
    assert "22" in p and "28" in p


def test_prompt_weather_temp_optional(sample_places):
    """description 給但 temp=None 時，仍可正常組合。"""
    p = gen._build_user_prompt(
        "2026-05-01", "09:00",
        {"description": "晴", "temp": None},
        sample_places,
    )
    assert "晴" in p
    # 不該出現 None 字樣
    assert "None" not in p


# ---------------------------------------------------------------------------
# _normalize_stops
# ---------------------------------------------------------------------------

@pytest.fixture
def lookup(sample_places):
    return {p["place_id"]: p for p in sample_places}


async def test_normalize_stops_drops_unknown_place_id(lookup):
    raw = [
        {"time": "09:00", "place_id": 1, "name": "永康牛肉麵",
         "duration_min": 60, "transport_to_next": "步行 5 分鐘", "note": "招牌"},
        {"time": "11:00", "place_id": 999, "name": "鬼地方",
         "duration_min": 30, "transport_to_next": "", "note": ""},
    ]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert len(stops) == 1
    assert stops[0]["place_id"] == 1


async def test_normalize_stops_fills_missing_fields_from_lookup(lookup):
    raw = [{"time": "09:00", "place_id": 2, "duration_min": 45}]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert stops[0]["name"] == "象山步道"  # canonical from lookup
    assert stops[0]["transport_to_next"] == ""
    assert stops[0]["note"] == ""
    assert stops[0]["duration_min"] == 45
    # 新欄位：lat/lng/address/google_place_id 必須帶出
    assert stops[0]["lat"] == 25.0274
    assert stops[0]["lng"] == 121.5707
    assert stops[0]["google_place_id"] is None


async def test_normalize_stops_overrides_gemini_name_with_canonical(lookup):
    """pid 命中 → 用 DB canonical name，不信 Gemini 給的名字（防幻覺名）。"""
    raw = [{"time": "09:00", "place_id": 1, "name": "完全錯的店名", "duration_min": 60}]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert stops[0]["name"] == "永康牛肉麵"


async def test_normalize_stops_clamps_negative_duration(lookup):
    raw = [{"time": "09:00", "place_id": 1, "duration_min": -10}]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert stops[0]["duration_min"] == 0


async def test_normalize_stops_handles_string_place_id(lookup):
    raw = [{"time": "09:00", "place_id": "1", "duration_min": 30}]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert stops[0]["place_id"] == 1


async def test_normalize_stops_skips_non_dict_and_unparseable_id(lookup):
    raw = ["junk", None, {"place_id": "abc"}, {"place_id": None}]
    assert await gen._normalize_stops(raw, lookup, allow_google_fallback=False) == []


async def test_normalize_stops_empty_input(lookup):
    assert await gen._normalize_stops([], lookup, allow_google_fallback=False) == []
    assert await gen._normalize_stops(None, lookup, allow_google_fallback=False) == []


async def test_normalize_stops_truncates_long_note(lookup):
    raw = [{"time": "09:00", "place_id": 1, "duration_min": 30, "note": "x" * 200}]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert len(stops[0]["note"]) <= 80


async def test_normalize_stops_preserves_order(lookup):
    raw = [
        {"time": "11:00", "place_id": 2, "duration_min": 60},
        {"time": "09:00", "place_id": 1, "duration_min": 60},
    ]
    stops = await gen._normalize_stops(raw, lookup, allow_google_fallback=False)
    assert [s["place_id"] for s in stops] == [2, 1]


# ---------------------------------------------------------------------------
# _normalize_stops — Google Places fallback
# ---------------------------------------------------------------------------

class _FakeResolved:
    """Lightweight stand-in for app.services.hotel.google_resolver.ResolvedPlace."""
    def __init__(self, place_id, name, lat, lng, formatted_address, in_taipei=True):
        self.place_id = place_id
        self.name = name
        self.lat = lat
        self.lng = lng
        self.formatted_address = formatted_address
        self.in_taipei = in_taipei


async def test_normalize_stops_google_fallback_hits(lookup, monkeypatch):
    """pid 不在 candidate 但 name 真實存在 → Google 解析後加入行程。"""
    monkeypatch.setattr(gen.settings, "GOOGLE_MAPS_API_KEY", "fake-key")

    async def fake_resolve(name, *a, **kw):
        return _FakeResolved(
            place_id="ChIJtest", name="台北 101",
            lat=25.0330, lng=121.5654,
            formatted_address="台北市信義區信義路五段7號",
        )
    monkeypatch.setattr(gen, "resolve_place", fake_resolve)

    raw = [{"time": "13:00", "place_id": 9999, "name": "台北 101", "duration_min": 60}]
    stops = await gen._normalize_stops(raw, lookup)
    assert len(stops) == 1
    s = stops[0]
    assert s["place_id"] == 0
    assert s["google_place_id"] == "ChIJtest"
    assert s["name"] == "台北 101"
    assert s["lat"] == 25.0330
    assert s["lng"] == 121.5654
    assert s["address"] == "台北市信義區信義路五段7號"


async def test_normalize_stops_google_fallback_miss_drops(lookup, monkeypatch):
    monkeypatch.setattr(gen.settings, "GOOGLE_MAPS_API_KEY", "fake-key")

    async def fake_resolve(name, *a, **kw):
        return None
    monkeypatch.setattr(gen, "resolve_place", fake_resolve)

    raw = [{"time": "13:00", "place_id": 9999, "name": "完全不存在的店", "duration_min": 60}]
    stops = await gen._normalize_stops(raw, lookup)
    assert stops == []


async def test_normalize_stops_drops_out_of_taipei_when_candidates_taipei_only(lookup, monkeypatch):
    """所有 candidate 都在台北、Google 解到外縣市 → 視為跑題，drop。"""
    monkeypatch.setattr(gen.settings, "GOOGLE_MAPS_API_KEY", "fake-key")

    async def fake_resolve(name, *a, **kw):
        return _FakeResolved(
            place_id="ChIJkaohsiung", name="高雄某地",
            lat=22.6, lng=120.3,
            formatted_address="高雄市", in_taipei=False,
        )
    monkeypatch.setattr(gen, "resolve_place", fake_resolve)

    raw = [{"time": "13:00", "place_id": 9999, "name": "高雄夢時代", "duration_min": 60}]
    stops = await gen._normalize_stops(raw, lookup)
    assert stops == []


async def test_normalize_stops_no_google_fallback_when_key_missing(lookup, monkeypatch):
    """GOOGLE_MAPS_API_KEY 未設 → 不嘗試 Google，直接 drop（避免無謂 API 呼叫）。"""
    monkeypatch.setattr(gen.settings, "GOOGLE_MAPS_API_KEY", "")

    called = []
    async def fake_resolve(name, *a, **kw):
        called.append(name)
        return None
    monkeypatch.setattr(gen, "resolve_place", fake_resolve)

    raw = [{"time": "13:00", "place_id": 9999, "name": "X", "duration_min": 60}]
    stops = await gen._normalize_stops(raw, lookup)
    assert stops == []
    assert called == []  # 完全不該呼叫


# ---------------------------------------------------------------------------
# _total_duration_hours
# ---------------------------------------------------------------------------

def test_total_uses_llm_value_when_positive():
    stops = [{"duration_min": 60}, {"duration_min": 30}]
    assert gen._total_duration_hours(stops, raw_total=4.5) == 4.5


def test_total_falls_back_to_sum_when_llm_missing():
    stops = [{"duration_min": 60}, {"duration_min": 90}]
    # 150 / 60 = 2.5
    assert gen._total_duration_hours(stops) == 2.5


def test_total_falls_back_when_llm_value_invalid():
    stops = [{"duration_min": 60}]
    assert gen._total_duration_hours(stops, raw_total=0) == 1.0
    assert gen._total_duration_hours(stops, raw_total=-2) == 1.0
    assert gen._total_duration_hours(stops, raw_total="six") == 1.0


def test_total_zero_for_empty_stops():
    assert gen._total_duration_hours([]) == 0.0


# ---------------------------------------------------------------------------
# _parse_cwb_payload
# ---------------------------------------------------------------------------

def _cwb_sample():
    return {
        "records": {
            "location": [
                {
                    "locationName": "臺北市",
                    "weatherElement": [
                        {"elementName": "Wx", "time": [
                            {"parameter": {"parameterName": "午後短暫雷陣雨"}}
                        ]},
                        {"elementName": "PoP", "time": [
                            {"parameter": {"parameterName": "60"}}
                        ]},
                        {"elementName": "MinT", "time": [
                            {"parameter": {"parameterName": "23"}}
                        ]},
                        {"elementName": "MaxT", "time": [
                            {"parameter": {"parameterName": "29"}}
                        ]},
                    ],
                }
            ]
        }
    }


def test_parse_cwb_extracts_description_and_temp_range():
    out = gen._parse_cwb_payload(_cwb_sample())
    assert out == {"description": "午後短暫雷陣雨", "temp": "23–29"}


def test_parse_cwb_returns_none_for_unexpected_shape():
    assert gen._parse_cwb_payload({}) is None
    assert gen._parse_cwb_payload({"records": {"location": []}}) is None
    assert gen._parse_cwb_payload(
        {"records": {"location": [{"weatherElement": []}]}}
    ) is None


# ---------------------------------------------------------------------------
# _fetch_weather
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_weather_returns_none_when_key_missing(monkeypatch):
    monkeypatch.setattr(gen.settings, "CWB_API_KEY", "")
    assert await gen._fetch_weather() is None


@pytest.mark.asyncio
async def test_fetch_weather_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(gen.settings, "CWB_API_KEY", "fake")

    class FailingClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, *a, **kw):
            raise RuntimeError("network down")

    monkeypatch.setattr(gen.httpx, "AsyncClient", FailingClient)
    assert await gen._fetch_weather() is None


# ---------------------------------------------------------------------------
# generate() orchestration — patches DB + recs + weather + Gemini
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_happy_path(monkeypatch):
    """Places + recommendations 都進 candidates；Gemini 回的 stops 經 normalize 後輸出。"""
    fake_places = [
        {"place_id": 1, "name": "永康牛肉麵", "category": "food",
         "lat": 25.0329, "lng": 121.5299, "source": "place"},
        {"place_id": 2, "name": "象山步道", "category": "attraction",
         "lat": 25.0274, "lng": 121.5707, "source": "place"},
    ]
    fake_recs = [
        {"place_id": -1_000_101, "name": "富錦街咖啡", "category": "food",
         "lat": 25.0559, "lng": 121.5541, "source": "recommendation"},
    ]

    captured: dict = {}

    async def fake_read_places(session_id):
        captured["session_id"] = session_id
        return fake_places

    async def fake_recs_fn(session_id):
        return fake_recs

    async def fake_weather():
        return {"description": "晴", "temp": "22–28"}

    async def fake_schedule(prompt):
        captured["prompt"] = prompt
        return {
            "stops": [
                {"time": "09:00", "place_id": 1, "name": "永康牛肉麵",
                 "duration_min": 60, "transport_to_next": "步行 8 分鐘",
                 "note": "招牌半筋半肉"},
                {"time": "10:30", "place_id": -1_000_101, "name": "富錦街咖啡",
                 "duration_min": 45, "transport_to_next": "計程車 10 分鐘",
                 "note": "下午時段悠閒"},
                {"time": "12:00", "place_id": 2, "name": "象山步道",
                 "duration_min": 90, "transport_to_next": "",
                 "note": "看 101 夜景"},
            ],
            "total_duration_hours": 3.5,
        }

    async def fake_persist(session_id, candidates, stops, total, weather):
        captured["persisted"] = {
            "session_id": session_id,
            "candidates": candidates,
            "stops": stops,
            "total": total,
            "weather": weather,
        }
        return 42

    monkeypatch.setattr(gen, "_read_places", fake_read_places)
    monkeypatch.setattr(gen, "_gather_recommendations", fake_recs_fn)
    monkeypatch.setattr(gen, "_fetch_weather", fake_weather)
    monkeypatch.setattr(gen, "_generate_schedule", fake_schedule)
    monkeypatch.setattr(gen, "_persist_itinerary", fake_persist)

    out = await gen.generate("sess-abc", "2026-05-01", "09:00")

    assert out["id"] == 42
    assert out["total_duration_hours"] == 3.5
    assert [s["place_id"] for s in out["stops"]] == [1, -1_000_101, 2]
    assert all("note" in s for s in out["stops"])

    # session_id flow through
    assert captured["session_id"] == "sess-abc"
    # prompt embeds candidates
    assert "永康牛肉麵" in captured["prompt"]
    assert "富錦街咖啡" in captured["prompt"]
    # persistence call shape matches
    assert captured["persisted"]["session_id"] == "sess-abc"
    assert captured["persisted"]["weather"]["description"] == "晴"
    # all 3 candidates persisted (2 places + 1 rec)
    assert len(captured["persisted"]["candidates"]) == 3


@pytest.mark.asyncio
async def test_generate_no_places_returns_empty_itinerary(monkeypatch):
    """沒收藏 → 不 call recs / Gemini，回傳空 stops 但仍寫入 itinerary 表。"""
    schedule_calls: list = []
    rec_calls: list = []

    async def fake_read_places(session_id):
        return []

    async def fake_recs(session_id):
        rec_calls.append(session_id)
        return []

    async def fake_weather():
        return None

    async def fake_schedule(prompt):
        schedule_calls.append(prompt)
        return {}

    async def fake_persist(*a, **kw):
        return 7

    monkeypatch.setattr(gen, "_read_places", fake_read_places)
    monkeypatch.setattr(gen, "_gather_recommendations", fake_recs)
    monkeypatch.setattr(gen, "_fetch_weather", fake_weather)
    monkeypatch.setattr(gen, "_generate_schedule", fake_schedule)
    monkeypatch.setattr(gen, "_persist_itinerary", fake_persist)

    out = await gen.generate("empty-sess", "2026-05-01")

    assert out == {"id": 7, "stops": [], "total_duration_hours": 0.0}
    # 沒 places 時不該打 Gemini，也不該打推薦（避免無謂成本）
    assert schedule_calls == []
    assert rec_calls == []


@pytest.mark.asyncio
async def test_generate_filters_hallucinated_place_ids(monkeypatch):
    """LLM 回了不在 candidates 裡的 place_id 時，要被丟掉，避免前端跳到 null place。"""
    async def fake_read_places(session_id):
        return [
            {"place_id": 1, "name": "永康牛肉麵", "category": "food",
             "lat": 25.0329, "lng": 121.5299, "source": "place"},
        ]

    async def fake_recs(session_id):
        return []

    async def fake_weather():
        return None

    async def fake_schedule(prompt):
        return {
            "stops": [
                # 合法
                {"time": "09:00", "place_id": 1, "duration_min": 60},
                # 幻想出來的
                {"time": "11:00", "place_id": 9999, "duration_min": 30},
            ],
            "total_duration_hours": 1.5,
        }

    async def fake_persist(*a, **kw):
        return 1

    monkeypatch.setattr(gen, "_read_places", fake_read_places)
    monkeypatch.setattr(gen, "_gather_recommendations", fake_recs)
    monkeypatch.setattr(gen, "_fetch_weather", fake_weather)
    monkeypatch.setattr(gen, "_generate_schedule", fake_schedule)
    monkeypatch.setattr(gen, "_persist_itinerary", fake_persist)

    out = await gen.generate("s", "2026-05-01")
    assert len(out["stops"]) == 1
    assert out["stops"][0]["place_id"] == 1


@pytest.mark.asyncio
async def test_generate_caps_candidates_to_max(monkeypatch):
    """places + recs 超過 _MAX_TOTAL_PLACES 時要被截斷。"""
    many_places = [
        {"place_id": i, "name": f"P{i}", "category": "food",
         "lat": 25.03, "lng": 121.5, "source": "place"}
        for i in range(15)
    ]

    async def fake_read_places(session_id):
        return many_places

    async def fake_recs(session_id):
        return []

    async def fake_weather():
        return None

    captured: dict = {}

    async def fake_schedule(prompt):
        captured["prompt"] = prompt
        return {"stops": [], "total_duration_hours": 0}

    async def fake_persist(session_id, candidates, *a, **kw):
        captured["candidates"] = candidates
        return 1

    monkeypatch.setattr(gen, "_read_places", fake_read_places)
    monkeypatch.setattr(gen, "_gather_recommendations", fake_recs)
    monkeypatch.setattr(gen, "_fetch_weather", fake_weather)
    monkeypatch.setattr(gen, "_generate_schedule", fake_schedule)
    monkeypatch.setattr(gen, "_persist_itinerary", fake_persist)

    await gen.generate("s", "2026-05-01")
    assert len(captured["candidates"]) == gen._MAX_TOTAL_PLACES
    # prompt 重新映射為 1..N（_build_prompt_candidates）→ 截斷後最大 id 為 _MAX_TOTAL_PLACES
    assert f"id={gen._MAX_TOTAL_PLACES + 1}" not in captured["prompt"]


@pytest.mark.asyncio
async def test_generate_recovers_when_gemini_returns_empty(monkeypatch):
    """Gemini 回 {} 時走 _fallback_schedule，產生確定性 stops 並寫入表回 200。"""
    async def fake_read_places(session_id):
        return [
            {"place_id": 1, "name": "X", "category": "food",
             "lat": 25.0, "lng": 121.5, "address": "台北市某街 1 號", "source": "place"},
        ]

    async def fake_recs(session_id):
        return []

    async def fake_weather():
        return None

    async def fake_schedule(prompt):
        return {}  # Gemini 失敗或回空

    async def fake_persist(*a, **kw):
        return 99

    monkeypatch.setattr(gen, "_read_places", fake_read_places)
    monkeypatch.setattr(gen, "_gather_recommendations", fake_recs)
    monkeypatch.setattr(gen, "_fetch_weather", fake_weather)
    monkeypatch.setattr(gen, "_generate_schedule", fake_schedule)
    monkeypatch.setattr(gen, "_persist_itinerary", fake_persist)

    out = await gen.generate("s", "2026-05-01")
    assert out["id"] == 99
    # fallback 排程：1 個 candidate → 1 個 stop，並帶出座標 / 地址
    assert len(out["stops"]) == 1
    assert out["stops"][0]["place_id"] == 1
    assert out["stops"][0]["lat"] == 25.0
    assert out["stops"][0]["lng"] == 121.5
    assert out["stops"][0]["address"] == "台北市某街 1 號"
    assert out["total_duration_hours"] > 0


# ---------------------------------------------------------------------------
# Router contract — POST /itinerary/generate ↔ ItineraryOut alignment
# ---------------------------------------------------------------------------

def test_router_response_model_matches_frontend_types():
    """守住 spec M0.5 ↔ M0.4 contract: router 響應欄位必須與 TS Itinerary 對齊。"""
    from app.routers.itinerary import ItineraryOut, ItineraryStopOut

    assert set(ItineraryOut.model_fields) == {
        "id", "stops", "total_duration_hours",
    }
    assert set(ItineraryStopOut.model_fields) == {
        "time", "place_id", "name", "duration_min",
        "transport_to_next", "note",
        "lat", "lng", "address", "google_place_id",
    }


# ---------- 手動 integration test 指引 ----------
# 1. docker compose up -d db
# 2. docker compose run --rm backend alembic upgrade head
# 3. 用 Line Bot 或 POST /places 加幾個 places
# 4. curl -X POST localhost:8000/itinerary/generate -H 'Content-Type: application/json' -d '{
#      "session_id": "your_session", "date": "2026-05-01", "start_time": "09:00"
#    }'
#    預期：回 Itinerary，stops 非空，total_duration_hours > 0
# 5. psql -c "SELECT id, schedule->'stops' FROM itineraries ORDER BY id DESC LIMIT 1"
