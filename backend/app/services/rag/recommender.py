"""M5 推薦引擎 — 雙路檢索 + RRF + Gemini reason.

設計細節見 M1.md §13–§14。

入口: `find_similar(session_id, category, limit)` → RecommendResult[]

流程:
  1. 撈 user 已收藏的 places（含預先算好的 embedding_bgem3 / embedding_mpnet）
  2. 各算一個 centroid（純 numpy.mean，零 embedding cost）
  3. 對 attractions 跑兩條 pgvector cosine ANN，各取 top-K
  4. RRF 合併（k=60）→ 取 top-{limit}
  5. asyncio.gather 並行呼叫 Gemini 2.5 flash 生 reason，個別失敗 fallback 預設句
  6. 回傳 [{attraction, reason, score}]
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models.attraction import Attraction
from app.models.place import Place

log = logging.getLogger(__name__)

# 兩個 model 各取的 top-K，融合後再切 limit
_PER_MODEL_TOP_K = 20
# RRF 標準參數，文獻默契值
_RRF_K = 60
# pgvector ivfflat 預設 probes=1，搜尋只看一個 cluster；當 user 收藏 category 偏斜時
# 容易完全 miss 掉目標 category（centroid 落在 attraction 區，搜 food 就會 0 筆）。
# 50 在 lists=100 上是 recall ≥ 95% 的安全值，query 仍 < 100ms。
_IVFFLAT_PROBES = 50
# 推薦理由的 prompt 上下文：只放最近收藏的幾個 place 名（避免 prompt 過長）
_REASON_CONTEXT_PLACES = 5
_FALLBACK_REASON = "依你最近收藏的風格挑的"

_gemini_client: Any = None


def _get_gemini_client() -> Any:
    """Lazy init google-genai async client（spec M3.3 / M5.1）。"""
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


async def _load_session_places(
    session: AsyncSession, session_id: str
) -> list[dict]:
    """撈 session 所有 places + 兩欄 embedding。"""
    result = await session.execute(
        select(
            Place.id,
            Place.name,
            Place.embedding_bgem3,
            Place.embedding_mpnet,
        )
        .where(Place.user_session_id == session_id)
        .order_by(Place.created_at.desc())
    )
    return [
        {"id": r[0], "name": r[1], "embedding_bgem3": r[2], "embedding_mpnet": r[3]}
        for r in result.all()
    ]


def _centroid(vecs: list[Any]) -> list[float] | None:
    """np.mean over non-null vectors. None if all null."""
    valid = [v for v in vecs if v is not None]
    if not valid:
        return None
    return np.mean(np.asarray(valid, dtype=np.float32), axis=0).tolist()


async def _search_attractions(
    session: AsyncSession,
    column,
    centroid: list[float],
    category: str,
    limit: int,
) -> list[dict]:
    """單一 model 的 ANN 檢索。column 是 ORM 欄位（Vector 型別）。
    category='all' 表示不依 category 過濾。"""
    stmt = (
        select(
            Attraction.id,
            Attraction.name,
            Attraction.category,
            Attraction.lat,
            Attraction.lng,
            Attraction.address,
            Attraction.description,
            Attraction.tags,
            column.cosine_distance(centroid).label("distance"),
        )
        .where(column.is_not(None))
        .order_by("distance")
        .limit(limit)
    )
    if category != "all":
        stmt = stmt.where(Attraction.category == category)
    result = await session.execute(stmt)
    return [
        {
            "id": r[0],
            "name": r[1],
            "category": r[2],
            "lat": r[3],
            "lng": r[4],
            "address": r[5],
            "description": r[6],
            "tags": list(r[7]) if r[7] else [],
            "distance": float(r[8]),
        }
        for r in result.all()
    ]


def _rrf_merge(rankings: list[list[int]], k: int = _RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion。
    rankings: 多個 model 各自 top-K 的 attraction id 順序（rank 從 1 開始計）。
    回傳 [(id, fused_score)]，依 score DESC。
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, aid in enumerate(ranking, start=1):
            scores[aid] = scores.get(aid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


async def _generate_reason(
    place_names_context: str, attraction_name: str
) -> str:
    """單個 attraction 的推薦理由。失敗 → fallback。"""
    try:
        from google.genai import types

        client = _get_gemini_client()
        prompt = (
            f"使用者收藏過：{place_names_context}。"
            f"請用繁體中文一句話（20 字以內）說明為什麼推薦「{attraction_name}」。"
            f"只輸出那一句話，不要其他文字。"
        )
        # gemini-2.5-flash 預設 thinking 會吃掉大量 output token，64 token 經常切到剩
        # 幾個字。google-genai 0.8.0 的 ThinkingConfig 還沒有 thinking_budget 參數可關，
        # 改用 gemini-2.5-flash-lite（沒有 thinking 機制、速度更快），輸出穩定。
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=128,
            ),
        )
        text = (resp.text or "").strip()
        # 去除偶爾跑出來的引號/句點
        return text.strip("「」\"'。 ") or _FALLBACK_REASON
    except Exception:
        log.exception("gemini reason failed for %s", attraction_name)
        return _FALLBACK_REASON


async def find_similar(
    session_id: str,
    category: str,
    limit: int = 5,
) -> list[dict]:
    """spec M5.1 入口。返回 RecommendResult[] 對齊 frontend types。

    無 places、或 places 沒任何有效 embedding → 回 []。
    """
    async with SessionLocal() as session:
        # SET LOCAL 只影響本 transaction；ANN 兩次都會用到
        await session.execute(
            text(f"SET LOCAL ivfflat.probes = {_IVFFLAT_PROBES}")
        )
        places = await _load_session_places(session, session_id)
        if not places:
            return []

        centroid_bge = _centroid([p["embedding_bgem3"] for p in places])
        centroid_mp = _centroid([p["embedding_mpnet"] for p in places])
        if centroid_bge is None and centroid_mp is None:
            return []

        # 兩條 ANN 各取 top-K（同一個 session 內順序跑：兩個 query 都 < 20ms，
        # asyncio.gather 同 session 不安全，改開兩個 session 才能並行）
        bge_results: list[dict] = []
        mp_results: list[dict] = []
        if centroid_bge is not None:
            bge_results = await _search_attractions(
                session, Attraction.embedding_bgem3, centroid_bge,
                category, _PER_MODEL_TOP_K,
            )
        if centroid_mp is not None:
            mp_results = await _search_attractions(
                session, Attraction.embedding_mpnet, centroid_mp,
                category, _PER_MODEL_TOP_K,
            )

    # RRF 合併
    bge_ids = [r["id"] for r in bge_results]
    mp_ids = [r["id"] for r in mp_results]
    fused = _rrf_merge([bge_ids, mp_ids])[:limit]
    if not fused:
        return []

    # 建立 id → 完整 row 的 lookup（取兩邊 union；同 id 以 bge 為主）
    by_id: dict[int, dict] = {r["id"]: r for r in mp_results}
    by_id.update({r["id"]: r for r in bge_results})  # bge 覆蓋
    bge_dist = {r["id"]: r["distance"] for r in bge_results}
    mp_dist = {r["id"]: r["distance"] for r in mp_results}

    # 1.0 fallback 給「對方 model 沒選進 top-K」的情況（cosine dist ∈ [0, 2]，1.0 中性）
    def avg_distance(aid: int) -> float:
        return (bge_dist.get(aid, 1.0) + mp_dist.get(aid, 1.0)) / 2

    # Reason context: 最近 N 個 place 的名字
    context = "、".join(p["name"] for p in places[:_REASON_CONTEXT_PLACES])

    # 並行生成 reason
    reasons = await asyncio.gather(
        *[_generate_reason(context, by_id[aid]["name"]) for aid, _ in fused]
    )

    return [
        {
            "attraction": {
                "id": by_id[aid]["id"],
                "name": by_id[aid]["name"],
                "category": by_id[aid]["category"],
                "lat": by_id[aid]["lat"],
                "lng": by_id[aid]["lng"],
                "address": by_id[aid]["address"],
                "description": by_id[aid]["description"],
                "tags": by_id[aid]["tags"],
            },
            "reason": reasons[i],
            "score": avg_distance(aid),
        }
        for i, (aid, _) in enumerate(fused)
    ]
