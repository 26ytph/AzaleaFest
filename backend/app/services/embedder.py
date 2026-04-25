"""M1 + M3 + M5 共用 embedding 介面 — 雙 model 並行版.

Models:
  - BAAI/bge-m3 (1024 dim native) — 中文長句、語意檢索
  - sentence-transformers/paraphrase-multilingual-mpnet-base-v2 (768 dim native) — 中文短語/地名

設計細節見 M1.md §9–§13。

GPU autodetect: torch.cuda.is_available() → device="cuda" else "cpu"。
本機 GPU 跑 ingest，docker 隊友 CPU 端跑 query（query 一句，CPU 也夠快）。

spec M3.3 frozen signatures `embed` / `embed_batch` 仍保留，預設指向 bge-m3，
讓只關心單一 embedding 的 caller（例如 M3 的舊版 places router）不會壞。
M3 places router 已升級成同時呼叫 bgem3 + mpnet 寫入兩欄。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_BGEM3_NAME = "BAAI/bge-m3"
_BGEM3_DIM = 1024
_MPNET_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
_MPNET_DIM = 768

# bge-m3 是 XLM-RoBERTa-large（~560M params），記憶體吃較多 → 保守 batch
_BGEM3_BATCH = 32
# mpnet-base 小很多，可以開大 batch
_MPNET_BATCH = 64

_bgem3_model: "SentenceTransformer | None" = None
_mpnet_model: "SentenceTransformer | None" = None
_device: str | None = None


def _detect_device() -> str:
    """第一次呼叫時偵測 CUDA；之後 cache。"""
    global _device
    if _device is not None:
        return _device
    try:
        import torch
        _device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        _device = "cpu"
    return _device


def _get_bgem3() -> "SentenceTransformer":
    global _bgem3_model
    if _bgem3_model is None:
        from sentence_transformers import SentenceTransformer
        _bgem3_model = SentenceTransformer(_BGEM3_NAME, device=_detect_device())
    return _bgem3_model


def _get_mpnet() -> "SentenceTransformer":
    global _mpnet_model
    if _mpnet_model is None:
        from sentence_transformers import SentenceTransformer
        _mpnet_model = SentenceTransformer(_MPNET_NAME, device=_detect_device())
    return _mpnet_model


def _encode_sync(
    model_factory: Callable[[], "SentenceTransformer"],
    texts: list[str],
    batch_size: int,
) -> list[list[float]]:
    """同步 encode；async 版本用 asyncio.to_thread 包這個避免 block event loop."""
    model = model_factory()
    arrs = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return [row.tolist() for row in arrs]


async def embed_bgem3(text: str) -> list[float]:
    """1024-dim L2-normalized bge-m3 embedding."""
    vecs = await asyncio.to_thread(_encode_sync, _get_bgem3, [text], _BGEM3_BATCH)
    return vecs[0]


async def embed_mpnet(text: str) -> list[float]:
    """768-dim L2-normalized mpnet embedding."""
    vecs = await asyncio.to_thread(_encode_sync, _get_mpnet, [text], _MPNET_BATCH)
    return vecs[0]


async def embed_batch_bgem3(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_encode_sync, _get_bgem3, texts, _BGEM3_BATCH)


async def embed_batch_mpnet(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_encode_sync, _get_mpnet, texts, _MPNET_BATCH)


# ---------- spec M3.3 frozen aliases — 預設指向 bge-m3 ----------

async def embed(text: str) -> list[float]:
    return await embed_bgem3(text)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    return await embed_batch_bgem3(texts)
