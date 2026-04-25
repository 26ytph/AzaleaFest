"""M4 unit tests.

Integration coverage (DB + real data) lives in spec M4.4 acceptance curls;
this file covers the parts we can verify without a running Postgres.
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

# Import the standalone ingest script for normalizer coverage.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
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


# ---------- ingest_hotels normalizers ----------

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
    n = ingest_hotels.normalize_general_hotels(record)
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
    n = ingest_hotels.normalize_travel_hotels(record)
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
    assert ingest_hotels.normalize_general_hotels(record) is None


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
    assert ingest_hotels.normalize_travel_hotels(record) is None


def test_normalize_does_not_raise_on_unexpected_keys():
    """Extra/unknown columns must not break normalization."""
    record = {
        "旅館名稱": "Foo",
        "營業地址": "Bar",
        "未來新增欄位_xyz": "whatever",
    }
    assert ingest_hotels.normalize_general_hotels(record) is not None


def test_to_asyncpg_dsn_strips_sqlalchemy_prefix():
    assert (
        ingest_hotels.to_asyncpg_dsn(
            "postgresql+asyncpg://u:p@h:5432/db"
        )
        == "postgresql://u:p@h:5432/db"
    )
    # Plain postgresql:// is unchanged.
    assert (
        ingest_hotels.to_asyncpg_dsn("postgresql://u:p@h:5432/db")
        == "postgresql://u:p@h:5432/db"
    )


def test_datasets_registry_uses_correct_normalizers():
    by_id = {ds_id: (label, fn) for ds_id, label, fn in ingest_hotels.DATASETS}
    assert by_id["4d7d0b46-2e90-4ee7-b000-c0f2f3a37651"] == (
        "一般旅館",
        ingest_hotels.normalize_general_hotels,
    )
    assert by_id["58093ba6-4c98-4148-b27a-50ad97d7afca"] == (
        "旅遊網住宿",
        ingest_hotels.normalize_travel_hotels,
    )
