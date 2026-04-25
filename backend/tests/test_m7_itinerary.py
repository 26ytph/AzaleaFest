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


def test_normalize_stops_drops_unknown_place_id(lookup):
    raw = [
        {"time": "09:00", "place_id": 1, "name": "永康牛肉麵",
         "duration_min": 60, "transport_to_next": "步行 5 分鐘", "note": "招牌"},
        {"time": "11:00", "place_id": 999, "name": "鬼地方",
         "duration_min": 30, "transport_to_next": "", "note": ""},
    ]
    stops = gen._normalize_stops(raw, lookup)
    assert len(stops) == 1
    assert stops[0]["place_id"] == 1


def test_normalize_stops_fills_missing_fields_from_lookup(lookup):
    raw = [{"time": "09:00", "place_id": 2, "duration_min": 45}]
    stops = gen._normalize_stops(raw, lookup)
    assert stops[0]["name"] == "象山步道"  # filled from lookup
    assert stops[0]["transport_to_next"] == ""
    assert stops[0]["note"] == ""
    assert stops[0]["duration_min"] == 45


def test_normalize_stops_clamps_negative_duration(lookup):
    raw = [{"time": "09:00", "place_id": 1, "duration_min": -10}]
    stops = gen._normalize_stops(raw, lookup)
    assert stops[0]["duration_min"] == 0


def test_normalize_stops_handles_string_place_id(lookup):
    raw = [{"time": "09:00", "place_id": "1", "duration_min": 30}]
    stops = gen._normalize_stops(raw, lookup)
    assert stops[0]["place_id"] == 1


def test_normalize_stops_skips_non_dict_and_unparseable_id(lookup):
    raw = ["junk", None, {"place_id": "abc"}, {"place_id": None}]
    assert gen._normalize_stops(raw, lookup) == []


def test_normalize_stops_empty_input(lookup):
    assert gen._normalize_stops([], lookup) == []
    assert gen._normalize_stops(None, lookup) == []


def test_normalize_stops_truncates_long_note(lookup):
    raw = [{"time": "09:00", "place_id": 1, "duration_min": 30, "note": "x" * 200}]
    stops = gen._normalize_stops(raw, lookup)
    assert len(stops[0]["note"]) <= 80


def test_normalize_stops_preserves_order(lookup):
    raw = [
        {"time": "11:00", "place_id": 2, "duration_min": 60},
        {"time": "09:00", "place_id": 1, "duration_min": 60},
    ]
    stops = gen._normalize_stops(raw, lookup)
    assert [s["place_id"] for s in stops] == [2, 1]


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
    # prompt 只列出截斷後的 candidates
    assert "id=10" not in captured["prompt"]


@pytest.mark.asyncio
async def test_generate_recovers_when_gemini_returns_empty(monkeypatch):
    """Gemini 回 {} 時 stops=[]，total_duration_hours=0，整體仍要寫入表並回 200。"""
    async def fake_read_places(session_id):
        return [
            {"place_id": 1, "name": "X", "category": "food",
             "lat": 25.0, "lng": 121.5, "source": "place"},
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
    assert out == {"id": 99, "stops": [], "total_duration_hours": 0.0}


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
