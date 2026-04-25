"""M5 smoke tests — 純邏輯部分（RRF / centroid）不需要 DB / Gemini.

Integration test（含 DB + Gemini）放 docstring 裡當手動跑的指引，避免 CI 卡。
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.rag.recommender import _centroid, _rrf_merge


def test_rrf_merges_and_orders_by_combined_rank():
    # 兩個 model 的 top-K 排序：a 兩邊都很前，b 只有 mpnet 前，c 只有 bge 前
    bge = [10, 20, 30]
    mp = [10, 40, 50]
    fused = _rrf_merge([bge, mp])
    fused_ids = [aid for aid, _ in fused]
    # 10 兩邊都 rank 1 → 應該排第一
    assert fused_ids[0] == 10
    # 20、40 都各只有一邊 rank 2，分數一樣，但都該擠在 10 後面
    top3 = set(fused_ids[:3])
    assert 10 in top3
    assert 20 in top3
    assert 40 in top3


def test_rrf_handles_empty_rankings():
    assert _rrf_merge([[], []]) == []


def test_rrf_preserves_score_descending():
    fused = _rrf_merge([[1, 2, 3], [3, 2, 1]])
    scores = [s for _, s in fused]
    assert scores == sorted(scores, reverse=True)


def test_centroid_skips_none():
    vecs = [[1.0, 0.0], None, [3.0, 0.0], None]
    c = _centroid(vecs)
    assert c == pytest.approx([2.0, 0.0])


def test_centroid_all_none_returns_none():
    assert _centroid([None, None]) is None


def test_centroid_single_vector():
    c = _centroid([[1.0, 2.0, 3.0]])
    assert c == pytest.approx([1.0, 2.0, 3.0])


def test_centroid_dim_consistency():
    """centroid 維度必須跟 input 對齊（M5 用來查 1024 / 768 兩種空間）。"""
    vecs_1024 = [np.random.rand(1024).tolist() for _ in range(5)]
    c = _centroid(vecs_1024)
    assert len(c) == 1024
    vecs_768 = [np.random.rand(768).tolist() for _ in range(3)]
    c2 = _centroid(vecs_768)
    assert len(c2) == 768


# ---------- 手動 integration test 指引 ----------
# 1. docker compose up -d db
# 2. docker compose run --rm backend alembic upgrade head
# 3. docker compose run --rm backend python scripts/ingest_osm.py
#    （或讓 bootstrap 從 HF 拉 dump）
# 4. 用 Line Bot 加幾個 places，或直接：
#    curl -X POST localhost:8000/places -H 'Content-Type: application/json' -d '{
#      "session_id": "test", "name": "鼎泰豐", "category": "food",
#      "lat": 25.0335, "lng": 121.5648, "source_type": "manual"
#    }'
# 5. curl -X POST localhost:8000/recommend -H 'Content-Type: application/json' -d '{
#      "session_id": "test", "category": "food", "limit": 3
#    }'
#    預期：3 個 attraction，每個 reason 非空，score < 0.5
