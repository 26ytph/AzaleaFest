"""M4 unit tests.

Integration coverage (DB + real Google Places) lives in spec M4.4 acceptance
curls; this file covers everything we can verify without a running Postgres
or live network.
"""
import sys
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.services.hotel import match_hotel as exported_match_hotel
from app.services.hotel import google_resolver
from app.services.hotel.google_resolver import (
    ResolvedPlace,
    is_in_taipei,
    resolve_hotel,
)
from app.services.hotel import matcher as matcher_mod
from app.services.hotel.matcher import (
    MatchResult,
    SCORE_THRESHOLD_GLOBAL,
    match_hotel,
)

# Import the standalone scripts (not packages) for normalizer + CSV coverage.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_hotels  # noqa: E402
import ingest_hotels  # noqa: E402


# ---------- matcher constants & exports ----------

def test_score_threshold_global_is_90():
    assert SCORE_THRESHOLD_GLOBAL == 90


def test_match_result_defaults():
    r = MatchResult(status="unknown", match=None)
    assert r.alternatives == []
    assert r.score == 0.0


def test_public_export_points_to_matcher():
    assert exported_match_hotel is match_hotel


@pytest.mark.asyncio
async def test_match_hotel_signature_is_async_callable():
    import inspect

    assert callable(match_hotel)
    assert inspect.iscoroutinefunction(match_hotel)
    sig = inspect.signature(match_hotel)
    # lat/lng accepted for HTTP-contract back-compat (spec M0.4) but optional.
    assert sig.parameters["lat"].default is None
    assert sig.parameters["lng"].default is None


# ---------- google_resolver: is_in_taipei ----------

def _admin_component(long_text: str, short_text: str | None = None) -> dict:
    return {
        "longText": long_text,
        "shortText": short_text or long_text,
        "types": ["administrative_area_level_1", "political"],
    }


def test_is_in_taipei_admin_component_matches_taipei():
    place = {
        "addressComponents": [_admin_component("臺北市")],
        "location": {"latitude": 25.0, "longitude": 121.5},
    }
    assert is_in_taipei(place) is True


def test_is_in_taipei_admin_component_matches_alt_form():
    # Google sometimes returns "Taipei City" (English) under regionCode=tw.
    place = {
        "addressComponents": [_admin_component("Taipei City", "Taipei")],
        "location": {"latitude": 25.04, "longitude": 121.56},
    }
    assert is_in_taipei(place) is True


def test_is_in_taipei_admin_component_says_new_taipei_returns_false():
    """Authoritative admin signal must NOT fall through to bbox.

    A New Taipei address near the Taipei border (e.g. 永和) sits inside
    the bbox but isn't legally in Taipei City — admin-1 is the trump card.
    """
    place = {
        "addressComponents": [_admin_component("新北市")],
        "location": {"latitude": 25.0, "longitude": 121.51},
    }
    assert is_in_taipei(place) is False


def test_is_in_taipei_bbox_fallback_when_no_admin_component():
    place = {
        "addressComponents": [],
        "location": {"latitude": 25.04, "longitude": 121.56},
    }
    assert is_in_taipei(place) is True


def test_is_in_taipei_bbox_fallback_outside_box_returns_false():
    place = {
        "addressComponents": [],
        "location": {"latitude": 23.86, "longitude": 120.91},  # 日月潭
    }
    assert is_in_taipei(place) is False


def test_is_in_taipei_no_location_returns_false():
    assert is_in_taipei({"addressComponents": []}) is False


# ---------- google_resolver: resolve_hotel ----------

def _places_payload(
    *, place_id: str, name: str, lat: float, lng: float,
    admin_long: str = "臺北市", formatted: str = "",
) -> dict:
    return {
        "places": [
            {
                "id": place_id,
                "displayName": {"text": name, "languageCode": "zh-TW"},
                "formattedAddress": formatted or f"{admin_long}{name}",
                "location": {"latitude": lat, "longitude": lng},
                "addressComponents": [_admin_component(admin_long)],
                "types": ["lodging"],
            }
        ]
    }


def _mock_client(
    payload: dict | list, status_code: int = 200
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient backed by a MockTransport returning payload.

    Pass a list of payloads to script multiple successive requests.
    """
    queue = list(payload) if isinstance(payload, list) else [payload]

    def handler(request: httpx.Request) -> httpx.Response:
        body = queue.pop(0) if queue else {}
        return httpx.Response(status_code, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_resolve_hotel_returns_place_id_and_components(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "fake-key")
    payload = _places_payload(
        place_id="ChIJabc123",
        name="台北君悅酒店",
        lat=25.0339,
        lng=121.5645,
    )
    async with _mock_client(payload) as client:
        result = await resolve_hotel("台北君悅酒店", client=client)
    assert result is not None
    assert result.place_id == "ChIJabc123"
    assert result.name == "台北君悅酒店"
    assert result.lat == pytest.approx(25.0339)
    assert result.lng == pytest.approx(121.5645)
    assert result.in_taipei is True


@pytest.mark.asyncio
async def test_resolve_hotel_returns_none_on_empty_places(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "fake-key")
    async with _mock_client({"places": []}) as client:
        assert await resolve_hotel("不存在ZZZZ", client=client) is None


@pytest.mark.asyncio
async def test_resolve_hotel_returns_none_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "")

    class ExplodingClient:
        async def post(self, *_a, **_kw):  # pragma: no cover
            raise AssertionError("must not call HTTP without API key")

    assert await resolve_hotel("anything", client=ExplodingClient()) is None


@pytest.mark.asyncio
async def test_resolve_hotel_swallows_http_errors(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "fake-key")

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await resolve_hotel("anywhere", client=c) is None


@pytest.mark.asyncio
async def test_resolve_hotel_marks_outside_taipei(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "fake-key")
    payload = _places_payload(
        place_id="ChIJoutside",
        name="日月潭涵碧樓",
        lat=23.86, lng=120.91,
        admin_long="南投縣",
    )
    async with _mock_client(payload) as client:
        result = await resolve_hotel("日月潭涵碧樓", client=client)
    assert result is not None
    assert result.in_taipei is False


# ---------- matcher: full flow with mocked resolver + DB ----------

class _FakeSession:
    """Stub satisfying `async with SessionLocal() as session:` in matcher.py.

    The matcher only passes the session through to the four `_fetch_*`
    helpers, all of which we monkeypatch — so the session value is never
    actually used. We just need an async context manager to enter cleanly.
    """

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _fake_session_local():
    return _FakeSession()


def _resolved(in_taipei: bool = True, place_id: str = "PID-X",
              name: str = "台北君悅酒店",
              lat: float = 25.03, lng: float = 121.56) -> ResolvedPlace:
    return ResolvedPlace(
        place_id=place_id, name=name, lat=lat, lng=lng,
        formatted_address=f"台北市信義區 {name}", in_taipei=in_taipei,
    )


@pytest.fixture
def patched_session(monkeypatch):
    monkeypatch.setattr(matcher_mod, "SessionLocal", _fake_session_local)


@pytest.mark.asyncio
async def test_match_hotel_resolver_miss_returns_unknown(
    monkeypatch, patched_session
):
    async def fake_resolve(*_a, **_kw):
        return None

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    result = await match_hotel("ZZZZ不存在")
    assert result.status == "unknown"
    assert result.match is None
    assert result.alternatives == []


@pytest.mark.asyncio
async def test_match_hotel_outside_taipei_returns_unknown_not_illegal(
    monkeypatch, patched_session
):
    """Regression guard for requirement #3: non-Taipei resolution must
    NEVER produce status='illegal'."""

    async def fake_resolve(*_a, **_kw):
        return _resolved(in_taipei=False, place_id="PID-NANTOU",
                         name="日月潭涵碧樓", lat=23.86, lng=120.91)

    async def boom(*_a, **_kw):  # pragma: no cover
        raise AssertionError("DB must not be queried for non-Taipei")

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    monkeypatch.setattr(matcher_mod, "_fetch_by_place_id", boom)
    monkeypatch.setattr(matcher_mod, "_fetch_all", boom)
    monkeypatch.setattr(matcher_mod, "_fetch_nearest", boom)

    result = await match_hotel("日月潭涵碧樓")
    assert result.status == "unknown"
    assert result.status != "illegal"
    assert result.match is None
    assert result.alternatives == []


@pytest.mark.asyncio
async def test_match_hotel_place_id_hit_returns_legal(
    monkeypatch, patched_session
):
    resolved = _resolved(place_id="PID-HYATT")

    async def fake_resolve(*_a, **_kw):
        return resolved

    async def fake_by_pid(_session, pid):
        assert pid == "PID-HYATT"
        return {"id": 42, "name": "台北君悅酒店",
                "address": "台北市信義區松壽路2號",
                "lat": 25.0339, "lng": 121.5645}

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    monkeypatch.setattr(matcher_mod, "_fetch_by_place_id", fake_by_pid)

    result = await match_hotel("台北君悅酒店")
    assert result.status == "legal"
    assert result.score == 100.0
    assert result.match is not None
    assert result.match["id"] == 42


@pytest.mark.asyncio
async def test_match_hotel_falls_back_to_fuzz_when_place_id_misses(
    monkeypatch, patched_session
):
    resolved = _resolved(place_id="PID-NEW")

    async def fake_resolve(*_a, **_kw):
        return resolved

    async def fake_by_pid(*_a, **_kw):
        return None  # place_id miss

    async def fake_all(_session):
        return [
            {"id": 1, "name": "台北君悅酒店",
             "address": "信義區", "lat": 25.0, "lng": 121.5},
            {"id": 2, "name": "圓山大飯店",
             "address": "中山區", "lat": 25.07, "lng": 121.52},
        ]

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    monkeypatch.setattr(matcher_mod, "_fetch_by_place_id", fake_by_pid)
    monkeypatch.setattr(matcher_mod, "_fetch_all", fake_all)

    result = await match_hotel("台北君悅酒店")
    assert result.status == "legal"
    assert result.match is not None
    assert result.match["id"] == 1
    assert result.score >= SCORE_THRESHOLD_GLOBAL


@pytest.mark.asyncio
async def test_match_hotel_falls_back_on_user_input_when_resolved_name_is_english(
    monkeypatch, patched_session
):
    """Google's v1 :searchText sometimes returns an English displayName
    even with regionCode=tw (Sheraton, Caesar Park, etc.). When the
    DB row's google_place_id doesn't match the resolved place_id, the
    fuzz fallback against the English name fails — but the user's
    original Chinese input still matches the Chinese DB name. This is
    the regression case behind '輸入喜來登大飯店出現非法日租'."""

    resolved = ResolvedPlace(
        place_id="ChIJ-google-other-listing",
        name="Sheraton Grand Taipei Hotel",  # English from Google
        lat=25.0446, lng=121.5220,
        formatted_address="100臺北市中正區忠孝東路一段12號",
        in_taipei=True,
    )

    async def fake_resolve(*_a, **_kw):
        return resolved

    async def fake_by_pid(*_a, **_kw):
        return None  # DB has a different place_id for the same hotel

    async def fake_all(_session):
        return [
            {"id": 100, "name": "台北寒舍喜來登大飯店",
             "address": "臺北市中正區忠孝東路1段12號",
             "lat": 25.04, "lng": 121.52},
            {"id": 200, "name": "圓山大飯店",
             "address": "中山區", "lat": 25.07, "lng": 121.52},
        ]

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    monkeypatch.setattr(matcher_mod, "_fetch_by_place_id", fake_by_pid)
    monkeypatch.setattr(matcher_mod, "_fetch_all", fake_all)

    result = await match_hotel("喜來登大飯店")
    assert result.status == "legal", (
        f"expected legal via user-input fuzz, got {result.status}"
    )
    assert result.match is not None
    assert result.match["id"] == 100
    assert result.score >= SCORE_THRESHOLD_GLOBAL


@pytest.mark.asyncio
async def test_match_hotel_illegal_uses_resolved_coords_for_alternatives(
    monkeypatch, patched_session
):
    resolved = _resolved(place_id="PID-FAKE",
                         name="阿貓阿狗非法民宿XYZ",
                         lat=25.04, lng=121.56)

    async def fake_resolve(*_a, **_kw):
        return resolved

    async def fake_by_pid(*_a, **_kw):
        return None

    async def fake_all(_session):
        return [
            {"id": 7, "name": "台北君悅酒店",
             "address": "信義區", "lat": 25.0, "lng": 121.5},
        ]

    captured: dict = {}

    async def fake_nearest(_session, lat, lng, limit):
        captured["lat"] = lat
        captured["lng"] = lng
        captured["limit"] = limit
        return [
            {"id": 7, "name": "台北君悅酒店", "address": "信義區",
             "lat": 25.0, "lng": 121.5},
        ]

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    monkeypatch.setattr(matcher_mod, "_fetch_by_place_id", fake_by_pid)
    monkeypatch.setattr(matcher_mod, "_fetch_all", fake_all)
    monkeypatch.setattr(matcher_mod, "_fetch_nearest", fake_nearest)

    result = await match_hotel("阿貓阿狗非法民宿XYZ")
    assert result.status == "illegal"
    assert result.match is None
    assert len(result.alternatives) == 1
    assert captured["lat"] == pytest.approx(25.04)
    assert captured["lng"] == pytest.approx(121.56)
    assert captured["limit"] == 3


@pytest.mark.asyncio
async def test_match_hotel_unknown_when_db_empty(
    monkeypatch, patched_session
):
    """Defensive: legal_hotels emptied → can't say legal/illegal."""
    resolved = _resolved(place_id="PID-X")

    async def fake_resolve(*_a, **_kw):
        return resolved

    async def fake_by_pid(*_a, **_kw):
        return None

    async def fake_all(_session):
        return []

    monkeypatch.setattr(matcher_mod, "resolve_hotel", fake_resolve)
    monkeypatch.setattr(matcher_mod, "_fetch_by_place_id", fake_by_pid)
    monkeypatch.setattr(matcher_mod, "_fetch_all", fake_all)

    result = await match_hotel("台北君悅酒店")
    assert result.status == "unknown"


# ---------- fetch_hotels normalizers ----------

def test_normalize_travel_hotels_happy_path():
    record = {
        "_id": 1,
        "旅館類別": "一般旅館",
        "旅宿名稱": "台北晶華酒店",
        "地址": "台北市中山區中山北路二段39巷3號",
        "電話或手機號碼": "02-25238000",
        "傳真": "02-25238001",
        "房間數": "538",
    }
    n = fetch_hotels.normalize_travel_hotels(record)
    assert n is not None
    assert n["name"] == "台北晶華酒店"
    assert n["address"] == "台北市中山區中山北路二段39巷3號"
    assert n["license_number"] is None
    assert n["hotel_type"] == "一般旅館"
    assert n["source"] == "旅遊網住宿"


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"旅宿名稱": "X"},
        {"地址": "台北市..."},
        {"旅宿名稱": "  ", "地址": "  "},
        {"旅宿名稱": None, "地址": None},
    ],
)
def test_normalize_travel_hotels_skips_invalid(record):
    assert fetch_hotels.normalize_travel_hotels(record) is None


def test_normalize_travel_hotels_does_not_raise_on_unexpected_keys():
    record = {
        "旅宿名稱": "Foo",
        "地址": "Bar",
        "未來新增欄位_xyz": "whatever",
    }
    assert fetch_hotels.normalize_travel_hotels(record) is not None


def test_datasets_registry_is_travel_hotels_only():
    """臺北市一般旅館 dropped — 旅遊網住宿 is a superset, ~619 rows total."""
    assert len(fetch_hotels.DATASETS) == 1
    rid, label, fn = fetch_hotels.DATASETS[0]
    assert rid == "adb6f5a6-3541-479a-bb32-d5be17eaa95b"
    assert label == "旅遊網住宿"
    assert fn is fetch_hotels.normalize_travel_hotels
    # Sanity: the old normalize_general_hotels is gone.
    assert not hasattr(fetch_hotels, "normalize_general_hotels")


# ---------- CSV roundtrip (fetch_hotels.write_csv ↔ ingest.load_csv) ----------

@pytest.fixture
def sample_rows():
    return [
        {
            "name": "台北君悅酒店",
            "address": "台北市信義區松壽路2號",
            "lat": 25.0339,
            "lng": 121.5645,
            "license_number": "HOTEL-001",
            "hotel_type": None,
            "source": "一般旅館",
            "raw_data": {"旅館名稱": "台北君悅酒店", "營業地址": "台北市信義區松壽路2號"},
        },
        {
            "name": "台北晶華酒店",
            "address": "台北市中山區中山北路二段39巷3號",
            # lat/lng now empty by default — Google re-geocode fills them
            # post-ingest. Roundtrip must still survive None.
            "lat": None,
            "lng": None,
            "license_number": None,
            "hotel_type": "一般旅館",
            "source": "旅遊網住宿",
            "raw_data": {"旅宿名稱": "台北晶華酒店"},
        },
    ]


def test_csv_write_then_load_cache_roundtrip(tmp_path, sample_rows):
    csv_path = tmp_path / "legal_hotels.csv"
    fetch_hotels.write_csv(csv_path, sample_rows)
    assert csv_path.exists()

    cache = fetch_hotels.load_cache(csv_path)
    assert len(cache) == 2

    hyatt = cache[("台北君悅酒店", "台北市信義區松壽路2號")]
    assert hyatt["lat"] == pytest.approx(25.0339, abs=1e-6)
    assert hyatt["lng"] == pytest.approx(121.5645, abs=1e-6)
    assert hyatt["license_number"] == "HOTEL-001"
    assert hyatt["raw_data"]["旅館名稱"] == "台北君悅酒店"

    regent = cache[("台北晶華酒店", "台北市中山區中山北路二段39巷3號")]
    assert regent["lat"] is None and regent["lng"] is None
    assert regent["license_number"] is None
    assert regent["hotel_type"] == "一般旅館"


def test_csv_write_then_ingest_load_roundtrip(tmp_path, sample_rows):
    csv_path = tmp_path / "legal_hotels.csv"
    fetch_hotels.write_csv(csv_path, sample_rows)

    rows = ingest_hotels.load_csv(csv_path)
    assert len(rows) == 2
    by_name = {r["name"]: r for r in rows}

    hyatt = by_name["台北君悅酒店"]
    assert hyatt["lat"] == pytest.approx(25.0339, abs=1e-6)
    assert hyatt["license_number"] == "HOTEL-001"
    assert isinstance(hyatt["raw_data"], dict)

    regent = by_name["台北晶華酒店"]
    assert regent["lat"] is None and regent["lng"] is None
    assert regent["license_number"] is None


def test_load_cache_returns_empty_when_file_missing(tmp_path):
    assert fetch_hotels.load_cache(tmp_path / "nope.csv") == {}


def test_csv_output_is_sorted_deterministically(tmp_path):
    rows = [
        {
            "name": "B", "address": "addr-b", "lat": 1.0, "lng": 1.0,
            "license_number": None, "hotel_type": None,
            "source": "旅遊網住宿", "raw_data": {},
        },
        {
            "name": "A", "address": "addr-a", "lat": 1.0, "lng": 1.0,
            "license_number": None, "hotel_type": None,
            "source": "一般旅館", "raw_data": {},
        },
    ]
    p = tmp_path / "legal_hotels.csv"
    fetch_hotels.write_csv(p, rows)
    lines = p.read_text(encoding="utf-8").splitlines()
    # Header + 2 rows; order is by (source, name, address) so 一般旅館 (A) first.
    assert lines[1].startswith("A,addr-a")
    assert lines[2].startswith("B,addr-b")


def test_fetch_hotels_no_longer_exposes_mapbox():
    """Mapbox is gone — guard against accidental re-introduction."""
    assert not hasattr(fetch_hotels, "mapbox_geocode")
    assert not hasattr(fetch_hotels, "MAPBOX_TOKEN")


# ---------- ingest helpers ----------

def test_to_asyncpg_dsn_strips_sqlalchemy_prefix():
    assert (
        ingest_hotels.to_asyncpg_dsn("postgresql+asyncpg://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )
    assert (
        ingest_hotels.to_asyncpg_dsn("postgresql://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )


# Silence unused-import warning; google_resolver imported for symbol presence.
assert google_resolver is not None
