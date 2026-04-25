"""M1 + M3 + M5 共用 embedding 介面 (spec M3.3 — sentence-transformers variant).

模型: BAAI/bge-m3
- 1024 dim 原生 → 補零 padding 至 1536（schema `vector(1536)`）
- 多語強，特別是中文檢索（MTEB-zh 領先 mpnet 5-10%）
- ~2.3GB（XLM-RoBERTa-large 底），第一次下載到 /root/.cache/huggingface（compose bind mount）

Hackathon 採用本機 embedding 而非 Gemini 是因為 gemini-embedding-001 的 free-tier RPM
非常嚴（實測 5-10 RPM），跑 15k+ row 要數小時且常 throttle 失敗。本機 model 無 quota 風險。

Spec M3.3 的 signatures 不變（仍是 async）— sync inference 用 asyncio.to_thread 包裝。
換 model 時：(a) 改 _MODEL_NAME / _NATIVE_DIM；(b) 清空 attractions.embedding 與
places.embedding 全 NULL；(c) 重跑 ingest 補 embedding。embedding space 必須一致。
"""
from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "BAAI/bge-m3"
_NATIVE_DIM = 1024
_TARGET_DIM = 1536
_BATCH_SIZE = 32  # bge-m3 比 mpnet 大兩倍，記憶體吃較多，batch 縮一半

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy import + load。第一次需 30-60s 載 model（含磁碟讀取或網路下載）。"""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        # device="cpu" 確保在 container 中跑得起來（無 GPU），也避免 OS X→linux/arm64 的差異
        _model = SentenceTransformer(_MODEL_NAME, device="cpu")
    return _model


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _pad_to_target(vec: list[float]) -> list[float]:
    """{native} → 1536，後段補零。Cosine similarity 不變（補的 0 對 dot product/norm 都貢獻 0）。"""
    if len(vec) >= _TARGET_DIM:
        return vec[:_TARGET_DIM]
    return vec + [0.0] * (_TARGET_DIM - len(vec))


def _encode_sync(texts: list[str]) -> list[list[float]]:
    """同步 encode；async 版本透過 asyncio.to_thread 包這個避免 block event loop。"""
    model = _get_model()
    # normalize_embeddings=True 讓 model 直接回傳 unit vector
    arrs = model.encode(
        texts,
        batch_size=_BATCH_SIZE,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [_pad_to_target(_l2_normalize(row.tolist())) for row in arrs]


async def embed(text: str) -> list[float]:
    """單筆 embedding，供 M3 / M5 即時使用。"""
    vecs = await asyncio.to_thread(_encode_sync, [text])
    return vecs[0]


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """批次 embedding，供 M1 ingest 使用。內部 model.encode 已自帶 batch；單次呼叫即可。"""
    return await asyncio.to_thread(_encode_sync, texts)
