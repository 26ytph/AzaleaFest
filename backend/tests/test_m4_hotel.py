"""M4 unit tests.

Integration coverage (DB + real data) lives in spec M4.4 acceptance curls;
this file covers the parts we can verify without a running Postgres or network.
"""
import sys
from pathlib import Path

import pytest
from rapidfuzz import fuzz, process

from app.services.hotel import match_hotel as exported_match_hotel
from app.services.hotel.matcher import (
    MatchResult,
    SCORE_THRESHOLD,
    match_hotel,
)

# Import the standalone scripts (not packages) for normalizer + CSV coverage.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_hotels  # noqa: E402
import ingest_hotels  # noqa: E402


# ---------- matcher ----------

def test_score_threshold_is_75():
    assert SCORE_THRESHOLD == 75


def test_match_result_defaults():
    r = MatchResult(status="unknown", match=None)
    assert r.alternatives == []
    assert r.score == 0.0


def test_public_export_points_to_matcher():
    assert exported_match_hotel is match_hotel


def test_rapidfuzz_finds_legal_hotel_above_threshold():
    """Sanity check: the scorer wired in matcher actually clears 75
    on a realistic Chinese-name partial match."""
    choices = {1: "台北君悅酒店", 2: "台北晶華酒店", 3: "圓山大飯店"}
    hit = process.extractOne(
        query="君悅酒店",
        choices=choices,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=SCORE_THRESHOLD,
    )
    assert hit is not None
    _, score, key = hit
    assert key == 1
    assert score >= SCORE_THRESHOLD


def test_rapidfuzz_rejects_unrelated_name():
    choices = {1: "台北君悅酒店", 2: "圓山大飯店"}
    hit = process.extractOne(
        query="阿貓阿狗非法民宿XYZ",
        choices=choices,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=SCORE_THRESHOLD,
    )
    assert hit is None


@pytest.mark.asyncio
async def test_match_hotel_signature_is_async_callable():
    assert callable(match_hotel)
    import inspect

    assert inspect.iscoroutinefunction(match_hotel)


# ---------- fetch_hotels normalizers ----------

def test_normalize_general_hotels_happy_path():
    record = {
        "_id": 1,
        "縣市代碼": "63",
        "專用標識編號": "HOTEL-001",
        "旅館名稱": "台北君悅酒店",
        "電話或手機號碼": "02-12345678",
        "營業地址": "台北市信義區松壽路2號",
        "客房最低定價": "3000",
        "客房最高定價": "20000",
        "房間數": "850",
    }
    n = fetch_hotels.normalize_general_hotels(record)
    assert n is not None
    assert n["name"] == "台北君悅酒店"
    assert n["address"] == "台北市信義區松壽路2號"
    assert n["license_number"] == "HOTEL-001"
    assert n["hotel_type"] is None
    assert n["lat"] is None and n["lng"] is None
    assert n["source"] == "一般旅館"
    assert n["raw_data"] is record


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
        {"旅館名稱": "X"},                      # missing address
        {"營業地址": "台北市..."},               # missing name
        {"旅館名稱": "  ", "營業地址": "  "},    # whitespace-only
        {"旅館名稱": None, "營業地址": None},
        {"電話或手機號碼": "02-1234"},           # only an unrelated field
    ],
)
def test_normalize_general_hotels_skips_invalid(record):
    assert fetch_hotels.normalize_general_hotels(record) is None


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


def test_normalize_does_not_raise_on_unexpected_keys():
    """Extra/unknown columns must not break normalization."""
    record = {
        "旅館名稱": "Foo",
        "營業地址": "Bar",
        "未來新增欄位_xyz": "whatever",
    }
    assert fetch_hotels.normalize_general_hotels(record) is not None


def test_datasets_registry_uses_correct_normalizers():
    by_rid = {rid: (label, fn) for rid, label, fn in fetch_hotels.DATASETS}
    assert by_rid["3cea29db-66b1-4ab5-886c-4cafd3e1dcbc"] == (
        "一般旅館",
        fetch_hotels.normalize_general_hotels,
    )
    assert by_rid["adb6f5a6-3541-479a-bb32-d5be17eaa95b"] == (
        "旅遊網住宿",
        fetch_hotels.normalize_travel_hotels,
    )


# ---------- CSV roundtrip (fetch_hotels.write_csv ↔ load_cache / ingest.load_csv) ----------

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
            "lat": None,  # geocoding may fail — must round-trip cleanly
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


# ---------- Mapbox response parsing ----------

@pytest.mark.asyncio
async def test_mapbox_geocode_parses_geojson_coords(monkeypatch):
    """Mapbox returns [lng, lat]; mapbox_geocode must flip to (lat, lng)."""
    monkeypatch.setattr(fetch_hotels, "MAPBOX_TOKEN", "fake-token")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "features": [
                    {"geometry": {
                        "type": "Point",
                        "coordinates": [121.5654177, 25.0329694],
                    }}
                ]
            }

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResp()

    lat, lng = await fetch_hotels.mapbox_geocode(FakeClient(), "台北101")
    assert lat == pytest.approx(25.0329694)
    assert lng == pytest.approx(121.5654177)


@pytest.mark.asyncio
async def test_mapbox_geocode_handles_empty_features(monkeypatch):
    monkeypatch.setattr(fetch_hotels, "MAPBOX_TOKEN", "fake-token")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"features": []}

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResp()

    lat, lng = await fetch_hotels.mapbox_geocode(FakeClient(), "nonexistent")
    assert lat is None and lng is None


@pytest.mark.asyncio
async def test_mapbox_geocode_returns_none_when_token_missing(monkeypatch):
    monkeypatch.setattr(fetch_hotels, "MAPBOX_TOKEN", "")

    class FakeClient:
        async def get(self, *args, **kwargs):
            raise AssertionError("must not call HTTP without token")

    lat, lng = await fetch_hotels.mapbox_geocode(FakeClient(), "anything")
    assert lat is None and lng is None
