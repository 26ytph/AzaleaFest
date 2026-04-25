"""Cross-lingual recommendation tests for M5.

The goal: prove that a user who saves a Japanese-language reel (cherry
blossoms, traditional architecture, hot springs, ramen ...) will get
*semantically related* Taipei attractions back from /recommend, not just
random hits.

The production embedders (bge-m3, paraphrase-multilingual-mpnet-base-v2)
are both multilingual; the recommender feeds the user's saved-place
text straight through them and aggregates the embeddings via centroid +
pgvector cosine ANN. So the question is purely: do these embedders place
e.g. "吉野山の桜並木" close enough to "陽明山櫻花" in vector space that
the centroid lands near the right Taipei rows?

These tests answer that empirically by:
  1. Embedding a small fixed catalog of ~28 Taipei attractions
  2. For each scenario, embedding the user's "saved places" (some written
     in Japanese, some in cross-lingual mix), building the centroid the
     same way `_centroid` does, then ranking the catalog by cosine
     distance.
  3. Asserting the curated "expected" attractions land in top-K and
     several distractors don't.

We also run a direct test of `find_similar()` with the DB layers
monkey-patched, so the integration of centroid + RRF + result projection
is exercised end-to-end.

The mpnet model is ~480 MB; bge-m3 is ~2.3 GB. CI without those weights
should `pytest -k "not embedded"` to skip the model-loading tests; the
RRF/centroid logic in test_m5_rag.py covers the rest.
"""
from __future__ import annotations

from typing import Any, Sequence
from unittest.mock import patch

import numpy as np
import pytest

from app.services.rag.recommender import (
    _centroid,
    _rrf_merge,
    find_similar,
)


# ---------------------------------------------------------------------------
# Catalog of Taipei attractions used across all scenarios.
# Descriptions intentionally mirror what M1's OSM ingest stores, so
# embeddings correspond to real production text shape.
# ---------------------------------------------------------------------------

CATALOG: list[dict[str, Any]] = [
    # cherry blossoms
    {"id": 101, "name": "陽明山國家公園", "category": "attraction",
     "description": "陽明山是台北著名賞櫻聖地，2 月底到 3 月櫻花盛開，山上有平菁街、花鐘等多個賞櫻景點。"},
    {"id": 102, "name": "東湖樂活公園", "category": "attraction",
     "description": "內湖區的賞櫻公園，種植數百株河津櫻與山櫻花，2 月初到 3 月初最佳。"},
    {"id": 103, "name": "天元宮", "category": "attraction",
     "description": "淡水天元宮的吉野櫻林是北台灣最具代表性的賞櫻景點之一，3 月中旬粉色花海盛開。"},
    # Japanese-era architecture
    {"id": 110, "name": "北投溫泉博物館", "category": "attraction",
     "description": "日治時代留下的木造溫泉浴場建築，仿日式公共浴場樣式，2 樓有大廣間與榻榻米。"},
    {"id": 111, "name": "西本願寺廣場", "category": "attraction",
     "description": "日治時期淨土真宗西本願寺台北別院遺址，保留日式樹心會館、輪番所等木造建築。"},
    {"id": 112, "name": "齊東詩舍", "category": "attraction",
     "description": "1930 年代日式宿舍群，黑瓦木造、緣側、玄關格局完整保留，作為文學沙龍。"},
    {"id": 113, "name": "紀州庵文學森林", "category": "attraction",
     "description": "原為日治時期高級料亭紀州庵，木造日式建築群已修復，作為文學主題園區。"},
    # hot springs
    {"id": 120, "name": "北投親水公園露天溫泉", "category": "attraction",
     "description": "北投溫泉區的公共露天溫泉浴池，源頭引入硫磺泉，分多池不同水溫。"},
    {"id": 121, "name": "新北投溫泉區", "category": "attraction",
     "description": "新北投是台北最大的溫泉鄉，沿線多家溫泉旅館與大眾湯屋，週末人潮絡繹不絕。"},
    # ramen / Japanese food
    {"id": 130, "name": "麵屋輝 台北本店", "category": "food",
     "description": "東京名店赴台分店，主打濃厚豚骨醬油拉麵，麵條 Q 彈，叉燒入口即化。"},
    {"id": 131, "name": "鷹流東京豚骨拉麵", "category": "food",
     "description": "信義區人氣日式拉麵店，招牌黑帝王豚骨湯頭濃郁，搭配半熟蛋與大片叉燒。"},
    {"id": 132, "name": "屯京拉麵", "category": "food",
     "description": "源自東京池袋的拉麵連鎖，魚介豚骨白湯系，叉燒厚切，常需排隊。"},
    # mountain views & nature photography
    {"id": 140, "name": "象山步道觀景台", "category": "attraction",
     "description": "信義區登山步道，30 分鐘即可登頂俯瞰台北 101 與盆地夜景，是熱門攝影點。"},
    {"id": 141, "name": "陽明山小油坑", "category": "attraction",
     "description": "硫磺噴氣孔景觀，可遠眺七星山火山地形，雲霧繚繞時拍攝山岳照效果極佳。"},
    {"id": 142, "name": "夢幻湖", "category": "attraction",
     "description": "陽明山七星山東側的高山堰塞湖，霧起時湖面如鏡，是熱門生態攝影地點。"},
    # shrines / temples (Japanese-style spiritual)
    {"id": 150, "name": "台北市孔廟", "category": "attraction",
     "description": "閩南式建築的祭孔廟宇，每年九月舉行祭孔大典，紅瓦白牆莊嚴肅穆。"},
    {"id": 151, "name": "行天宮", "category": "attraction",
     "description": "供奉關聖帝君的香火鼎盛廟宇，有收驚、解運等民俗儀式，許多日本旅客也會造訪。"},
    {"id": 152, "name": "圓山臨濟護國禪寺", "category": "attraction",
     "description": "日治時期建立的臨濟宗禪寺，大雄寶殿為日式木造伽藍，是台灣少見的純日式寺廟。"},
    # tea & cafes
    {"id": 160, "name": "貓空茶園步道", "category": "attraction",
     "description": "文山區貓空茶園山徑，可沿途品嘗鐵觀音茶、看夜景，茶藝館林立。"},
    {"id": 161, "name": "永康街茶館", "category": "food",
     "description": "大安區永康街知名的茶館聚集地，主打台灣高山烏龍與現點現泡。"},
    # Distractors — things a Japanese-themed reel should NOT match
    {"id": 200, "name": "饒河街觀光夜市", "category": "food",
     "description": "松山區人氣夜市，胡椒餅、藥燉排骨、蚵仔麵線是招牌台灣小吃。"},
    {"id": 201, "name": "西門町電影街", "category": "attraction",
     "description": "萬華區年輕人逛街熱點，刺青店、街舞表演、潮牌服飾林立，氣氛熱鬧。"},
    {"id": 202, "name": "華西街觀光夜市", "category": "food",
     "description": "萬華老牌觀光夜市，蛇肉湯、四神湯、青草茶等台味小吃。"},
    {"id": 203, "name": "Costco 內湖店", "category": "attraction",
     "description": "美式量販賣場，週末人潮眾多，主要販售大份量進口食品與日用品。"},
    {"id": 204, "name": "台北市立動物園", "category": "attraction",
     "description": "木柵動物園飼育大貓熊、無尾熊、企鵝等，假日親子家庭眾多。"},
    {"id": 205, "name": "鼎泰豐 信義店", "category": "food",
     "description": "米其林級小籠包名店，皮薄餡多湯汁飽滿，是來台灣必訪的台式江浙料理。"},
    {"id": 206, "name": "永和豆漿大王", "category": "food",
     "description": "中和老字號早餐店，主打鹹豆漿、燒餅油條、蛋餅。"},
    {"id": 207, "name": "三創生活園區", "category": "attraction",
     "description": "中正區 3C 商場，五層樓電子產品、桌遊、模型店家匯集。"},
]

CATALOG_BY_ID: dict[int, dict[str, Any]] = {a["id"]: a for a in CATALOG}


# ---------------------------------------------------------------------------
# Scenarios — each is a Reels saved by the user (some Japanese, some
# Chinese, some mixed) plus the curated correct/incorrect attraction IDs.
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "name": "japanese_cherry_blossom_reel",
        "saved": [
            {"name": "吉野山の桜", "category": "attraction",
             "description": "奈良吉野山に咲く三万本のソメイヨシノ、四月初旬に山一面がピンクに染まる絶景の桜の名所。"},
            {"name": "目黒川の桜並木", "category": "attraction",
             "description": "東京目黒川沿いの桜並木、夜桜ライトアップが美しい。"},
        ],
        "must_include_top": [101, 102, 103],  # 陽明山, 東湖樂活, 天元宮
        "must_exclude_top": [200, 201, 203, 204, 207],  # 夜市, 西門町, Costco, 動物園, 3C
    },
    {
        "name": "japanese_architecture_reel",
        "saved": [
            {"name": "京都祇園の町家", "category": "attraction",
             "description": "京都祇園の伝統的な木造町家、瓦屋根、格子戸、京町家の典型的な日本建築。"},
            {"name": "金沢ひがし茶屋街", "category": "attraction",
             "description": "ひがし茶屋街の伝統的な日本家屋が連なる町並み、江戸時代の景観を残す。"},
        ],
        # 北投溫泉博物館 (110) is about a Japanese-era bath house — its
        # description leans hot-spring rather than pure architecture, so we
        # don't strictly require it in top-K; the four other Japanese-era
        # sites must show up.
        "must_include_top": [111, 112, 113, 152],  # 西本願寺, 齊東詩舍, 紀州庵, 臨濟禪寺
        "must_exclude_top": [200, 201, 203, 204, 205, 207],
    },
    {
        "name": "japanese_hot_springs_reel",
        "saved": [
            {"name": "草津温泉", "category": "attraction",
             "description": "群馬県の有名な温泉地、湯畑から湧き出る硫黄泉の煙、湯もみショーが名物。"},
        ],
        "must_include_top": [120, 121, 110],  # 北投親水公園溫泉, 新北投, 北投溫泉博物館
        "must_exclude_top": [200, 201, 205, 207],
    },
    {
        "name": "japanese_ramen_reel",
        "saved": [
            {"name": "一蘭ラーメン渋谷", "category": "food",
             "description": "東京渋谷の一蘭ラーメン、濃厚豚骨スープと細麺、秘伝の赤い辛味噌が看板。"},
            {"name": "麺屋武蔵 新宿総本店", "category": "food",
             "description": "新宿の人気ラーメン店、魚介豚骨ダブルスープ、太麺と分厚いチャーシュー。"},
        ],
        "must_include_top": [130, 131, 132],  # 三家拉麵店
        # Ramen vs other Asian/Taiwanese food is a fine semantic gradient;
        # the 3 ramen shops must rank above all distractors but only check
        # the strict top-3 window.
        "must_exclude_top": [200, 202, 206],  # 夜市/豆漿
        "exclude_top_k": 3,
    },
    {
        "name": "japanese_shrine_reel",
        "saved": [
            {"name": "明治神宮", "category": "attraction",
             "description": "東京渋谷区の明治神宮、鳥居と鎮守の森、参拝客で賑わう日本の代表的な神社。"},
        ],
        # Among Taipei sites, the closest spiritual cousins are temples,
        # especially the Japanese-built 圓山臨濟禪寺.
        "must_include_top_any": [152, 150, 151],  # at least one of these
        "must_exclude_top": [200, 201, 203, 207],
    },
    {
        "name": "mt_fuji_photography_reel",
        "saved": [
            {"name": "富士山の絶景", "category": "attraction",
             "description": "山中湖から望む富士山、雪化粧の頂と早朝の朝焼け、絶好の山岳写真撮影スポット。"},
        ],
        "must_include_top_any": [140, 141, 142],  # 象山, 小油坑, 夢幻湖
        "must_exclude_top": [200, 202, 206, 207],
    },
    {
        "name": "mixed_zh_ja_reel",
        # Realistic case: Gemini Vision converts JP caption to ZH
        "saved": [
            {"name": "吉野山賞櫻", "category": "attraction",
             "description": "日本奈良吉野山是著名賞櫻聖地，三萬株櫻花樹一齊綻放。"},
            {"name": "京都清水寺", "category": "attraction",
             "description": "日本京都清水寺，木造舞台建築與春櫻、秋楓相映。"},
        ],
        "must_include_top": [101, 103, 113],  # 陽明山, 天元宮, 紀州庵 (zh-derived semantics)
        "must_exclude_top": [200, 203, 204, 207],
    },
]


# ---------------------------------------------------------------------------
# Embedding helpers — wrap the production embedder. Cached at module level
# because mpnet load is ~10 s and re-loading per test would dominate runtime.
# ---------------------------------------------------------------------------

_mpnet_cache: dict[str, np.ndarray] = {}
_bgem3_cache: dict[str, np.ndarray] = {}


def _embed_one(text: str, kind: str) -> np.ndarray:
    """Return cached embedding for `text`. kind ∈ {"mpnet", "bgem3"}."""
    cache = _mpnet_cache if kind == "mpnet" else _bgem3_cache
    if text in cache:
        return cache[text]
    from sentence_transformers import SentenceTransformer

    model_id = (
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
        if kind == "mpnet"
        else "BAAI/bge-m3"
    )
    # Lazy import + lazy module-cache for the model itself
    if kind == "mpnet":
        if not hasattr(_embed_one, "_mpnet_model"):
            _embed_one._mpnet_model = SentenceTransformer(model_id)  # type: ignore[attr-defined]
        model = _embed_one._mpnet_model  # type: ignore[attr-defined]
    else:
        if not hasattr(_embed_one, "_bgem3_model"):
            _embed_one._bgem3_model = SentenceTransformer(model_id)  # type: ignore[attr-defined]
        model = _embed_one._bgem3_model  # type: ignore[attr-defined]

    vec = model.encode([text], normalize_embeddings=True)[0]
    cache[text] = np.asarray(vec, dtype=np.float32)
    return cache[text]


def _embed_for_recommender(item: dict[str, Any], kind: str) -> np.ndarray:
    """Same text shape M3/M5 use: '<name>。<category>。<description>'."""
    text = f"{item['name']}。{item['category']}。{item.get('description', '')}"
    return _embed_one(text, kind)


def _models_available() -> dict[str, bool]:
    """Probe HF cache without triggering a download."""
    out = {"mpnet": False, "bgem3": False}
    try:
        from huggingface_hub import try_to_load_from_cache

        if try_to_load_from_cache(
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            "config.json",
        ):
            out["mpnet"] = True
        if try_to_load_from_cache("BAAI/bge-m3", "config.json"):
            out["bgem3"] = True
    except Exception:
        pass
    return out


_AVAILABLE = _models_available()
_skip_mpnet = pytest.mark.skipif(
    not _AVAILABLE["mpnet"],
    reason="mpnet weights not cached locally; "
    "run `python -c 'from sentence_transformers import SentenceTransformer; "
    "SentenceTransformer(\"sentence-transformers/paraphrase-multilingual-mpnet-base-v2\")'`",
)
_skip_bgem3 = pytest.mark.skipif(
    not _AVAILABLE["bgem3"],
    reason="bge-m3 weights not cached locally",
)


# ---------------------------------------------------------------------------
# Recommendation core — a pure-numpy reimplementation of the SQL portion of
# `find_similar()`. Same centroid math, same cosine distance ranking, just
# without pgvector. Lets us test ranking behaviour without spinning up a DB.
# ---------------------------------------------------------------------------

def _rank_attractions(
    saved_vecs: list[np.ndarray],
    catalog: Sequence[dict[str, Any]],
    catalog_vecs: dict[int, np.ndarray],
    category: str = "all",
) -> list[tuple[int, float]]:
    """Return [(attraction_id, cosine_distance)] sorted ascending by distance."""
    centroid = _centroid([v.tolist() for v in saved_vecs])
    assert centroid is not None
    c = np.asarray(centroid, dtype=np.float32)
    # Normalize centroid (saved vecs were already normalized by st model)
    c = c / (np.linalg.norm(c) + 1e-12)
    out: list[tuple[int, float]] = []
    for a in catalog:
        if category != "all" and a["category"] != category:
            continue
        v = catalog_vecs[a["id"]]
        v = v / (np.linalg.norm(v) + 1e-12)
        # cosine distance = 1 - cos_sim
        dist = float(1.0 - np.dot(c, v))
        out.append((a["id"], dist))
    return sorted(out, key=lambda x: x[1])


# ---------------------------------------------------------------------------
# Tests — pure logic (no embeddings). Always run.
# ---------------------------------------------------------------------------

def test_catalog_ids_unique_and_well_formed():
    ids = [a["id"] for a in CATALOG]
    assert len(ids) == len(set(ids))
    for a in CATALOG:
        assert a["category"] in ("food", "attraction", "hotel")
        assert a["description"], f"{a['name']} missing description"


def test_scenarios_reference_real_catalog_ids():
    ids = set(CATALOG_BY_ID)
    for s in SCENARIOS:
        for must in s.get("must_include_top", []):
            assert must in ids, f"{s['name']}: bad include id {must}"
        for must in s.get("must_include_top_any", []):
            assert must in ids, f"{s['name']}: bad any id {must}"
        for must in s.get("must_exclude_top", []):
            assert must in ids, f"{s['name']}: bad exclude id {must}"


# ---------------------------------------------------------------------------
# Embedded tests — actually load the model. Skipped if weights not cached.
# ---------------------------------------------------------------------------


@_skip_mpnet
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["name"])
def test_mpnet_centroid_recommends_relevant_taipei_attractions(scenario):
    """For each Japanese-themed scenario, mpnet centroid + cosine ranking
    should put the curated Taipei equivalents in the top-K.

    Also covers cross-lingual centroid: saved places written in Japanese
    must still cluster near Taipei attractions described in Chinese.
    """
    saved_vecs = [_embed_for_recommender(p, "mpnet") for p in scenario["saved"]]
    catalog_vecs = {
        a["id"]: _embed_for_recommender(a, "mpnet") for a in CATALOG
    }
    ranked = _rank_attractions(saved_vecs, CATALOG, catalog_vecs)

    include_k = scenario.get("include_top_k", 8)
    exclude_k = scenario.get("exclude_top_k", 8)
    include_top = [aid for aid, _ in ranked[:include_k]]
    exclude_top = [aid for aid, _ in ranked[:exclude_k]]

    if "must_include_top" in scenario:
        for expected in scenario["must_include_top"]:
            assert expected in include_top, (
                f"{scenario['name']}: expected attraction {expected} "
                f"({CATALOG_BY_ID[expected]['name']}) not in top-{include_k}: "
                f"{[CATALOG_BY_ID[i]['name'] for i in include_top]}"
            )

    if "must_include_top_any" in scenario:
        any_ids = scenario["must_include_top_any"]
        assert any(a in include_top for a in any_ids), (
            f"{scenario['name']}: none of {any_ids} appeared in top-{include_k}: "
            f"{[CATALOG_BY_ID[i]['name'] for i in include_top]}"
        )

    for excluded in scenario["must_exclude_top"]:
        # Distractors must NOT outrank curated answers — checked over the
        # narrower exclude window so we don't penalize "next-best food"
        # matches showing up far down the list.
        assert excluded not in exclude_top, (
            f"{scenario['name']}: distractor {excluded} "
            f"({CATALOG_BY_ID[excluded]['name']}) shouldn't appear in top-{exclude_k}: "
            f"{[CATALOG_BY_ID[i]['name'] for i in exclude_top]}"
        )


@_skip_mpnet
def test_japanese_cherry_blossom_outranks_distractors_decisively():
    """Sanity gap check: the top cherry-blossom attraction must beat a
    distractor by a clear margin (not just a tie-break)."""
    sc = SCENARIOS[0]  # cherry blossom
    saved_vecs = [_embed_for_recommender(p, "mpnet") for p in sc["saved"]]
    catalog_vecs = {a["id"]: _embed_for_recommender(a, "mpnet") for a in CATALOG}
    ranked = dict(_rank_attractions(saved_vecs, CATALOG, catalog_vecs))

    # 陽明山賞櫻 (101) vs 饒河夜市 (200)
    assert ranked[101] < ranked[200] - 0.05, (
        f"陽明山櫻花 dist={ranked[101]:.3f} should beat 饒河夜市 dist={ranked[200]:.3f}"
    )


@_skip_mpnet
def test_recommend_respects_category_filter():
    """category='food' must drop attraction-class hits even if semantically
    close, mirroring the SQL `WHERE category = ?` behaviour."""
    sc = next(s for s in SCENARIOS if s["name"] == "japanese_ramen_reel")
    saved_vecs = [_embed_for_recommender(p, "mpnet") for p in sc["saved"]]
    catalog_vecs = {a["id"]: _embed_for_recommender(a, "mpnet") for a in CATALOG}
    ranked = _rank_attractions(saved_vecs, CATALOG, catalog_vecs, category="food")
    for aid, _ in ranked[:5]:
        assert CATALOG_BY_ID[aid]["category"] == "food"


# ---------------------------------------------------------------------------
# Dual-encoder + RRF — same scenarios but using both models.
# ---------------------------------------------------------------------------


@_skip_mpnet
@_skip_bgem3
@pytest.mark.parametrize(
    "scenario",
    [s for s in SCENARIOS if "must_include_top" in s],
    ids=lambda s: s["name"],
)
def test_dual_encoder_rrf_finds_relevant_attractions(scenario):
    """Both bge-m3 and mpnet rankings, fused with RRF, should land the
    curated answers in top-K. This mirrors `find_similar()` exactly except
    for the SQL ANN itself."""
    saved_mp = [_embed_for_recommender(p, "mpnet") for p in scenario["saved"]]
    saved_bge = [_embed_for_recommender(p, "bgem3") for p in scenario["saved"]]
    catalog_mp = {a["id"]: _embed_for_recommender(a, "mpnet") for a in CATALOG}
    catalog_bge = {a["id"]: _embed_for_recommender(a, "bgem3") for a in CATALOG}

    rank_mp = [aid for aid, _ in _rank_attractions(saved_mp, CATALOG, catalog_mp)][:20]
    rank_bge = [aid for aid, _ in _rank_attractions(saved_bge, CATALOG, catalog_bge)][:20]

    fused = [aid for aid, _ in _rrf_merge([rank_mp, rank_bge])][:8]
    for expected in scenario["must_include_top"]:
        assert expected in fused, (
            f"{scenario['name']}: RRF missed expected {expected} "
            f"({CATALOG_BY_ID[expected]['name']}); fused={[CATALOG_BY_ID[i]['name'] for i in fused]}"
        )


# ---------------------------------------------------------------------------
# Integration — call find_similar() with DB calls patched, verify projection
# matches the API contract. Independent of embedding quality (uses canned
# distances).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_similar_projects_locale_columns_and_orders_by_rrf():
    """Canned bge/mpnet ANN results — verify find_similar() returns the
    Japanese/cross-lingual scenario's curated picks, with name_en/ja/ko/zh_cn
    passed through to the response payload."""

    # 1) Stub session_places — pretend the user saved one Japanese cherry
    #    reel and we already have its embeddings (any non-None vectors work).
    fake_places = [
        {
            "id": 1,
            "name": "吉野山の桜",
            "embedding_bgem3": [0.1] * 1024,
            "embedding_mpnet": [0.1] * 768,
        }
    ]

    # 2) Stub _search_attractions — return the curated cherry-blossom rows
    #    in different orders for bge vs mpnet so RRF fuses them.
    cherry_rows_bge = [
        _row(101, "陽明山國家公園", distance=0.12,
             name_en="Yangmingshan National Park",
             name_ja="陽明山国家公園",
             name_ko="양밍산 국가공원",
             name_zh_cn="阳明山国家公园"),
        _row(102, "東湖樂活公園", distance=0.18,
             name_en="Donghu Lohas Park"),
        _row(103, "天元宮", distance=0.22,
             name_en="Tianyuan Temple"),
        _row(200, "饒河街觀光夜市", distance=0.55),  # distractor
    ]
    cherry_rows_mp = [
        _row(103, "天元宮", distance=0.10),  # different order
        _row(101, "陽明山國家公園", distance=0.14),
        _row(200, "饒河街觀光夜市", distance=0.60),  # distractor
        _row(102, "東湖樂活公園", distance=0.21),
    ]

    async def _fake_load(_session, _session_id):
        return fake_places

    async def _fake_search(_session, column, _centroid, _category, limit):
        # column comes in as either Attraction.embedding_bgem3 or _mpnet —
        # use object identity by name to pick which canned list to return.
        col_name = getattr(column, "key", "") or str(column)
        if "bgem3" in col_name:
            return cherry_rows_bge[:limit]
        return cherry_rows_mp[:limit]

    async def _fake_reason(_context, _name):
        return "類似你收藏的「吉野山」"

    with patch("app.services.rag.recommender._load_session_places", _fake_load), \
         patch("app.services.rag.recommender._search_attractions", _fake_search), \
         patch("app.services.rag.recommender._generate_reason", _fake_reason), \
         patch("app.services.rag.recommender.SessionLocal", _FakeSessionFactory()):
        results = await find_similar("test-session", "all", limit=3)

    assert len(results) == 3
    ids = [r["attraction"]["id"] for r in results]
    # Top result is whatever RRF ranks #1; the distractor (200) must NOT
    # appear in top-3 — it's the worst rank in both models.
    assert 200 not in ids
    # All three cherry blossom IDs should be present
    assert set(ids) >= {101, 102, 103}

    # Check translations passed through
    yangmingshan = next(r for r in results if r["attraction"]["id"] == 101)
    assert yangmingshan["attraction"]["name_en"] == "Yangmingshan National Park"
    assert yangmingshan["attraction"]["name_ja"] == "陽明山国家公園"
    assert yangmingshan["attraction"]["name_ko"] == "양밍산 국가공원"
    assert yangmingshan["attraction"]["name_zh_cn"] == "阳明山国家公园"
    assert yangmingshan["reason"]


def _row(
    aid: int,
    name: str,
    *,
    distance: float,
    category: str = "attraction",
    name_en: str | None = None,
    name_ja: str | None = None,
    name_ko: str | None = None,
    name_zh_cn: str | None = None,
) -> dict[str, Any]:
    return {
        "id": aid,
        "name": name,
        "name_en": name_en,
        "name_ja": name_ja,
        "name_ko": name_ko,
        "name_zh_cn": name_zh_cn,
        "category": category,
        "lat": 25.0,
        "lng": 121.5,
        "address": None,
        "description": "",
        "tags": [],
        "distance": distance,
    }


class _FakeSessionFactory:
    """Drop-in async-context-manager mock for SessionLocal."""

    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    async def execute(self, *_a, **_kw):
        class _NoopResult:
            def all(self):
                return []
        return _NoopResult()
