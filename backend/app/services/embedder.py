"""M1 + M3 + M5 共用 embedding 介面 (spec M3.3).

模型: text-embedding-3-small (1536 dim)
"""


async def embed(text: str) -> list[float]:
    """單筆 embedding，供 M3 即時使用。"""
    raise NotImplementedError


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """批次 embedding，每 100 筆一批，每批 sleep(0.5)。供 M1 ingest 使用。"""
    raise NotImplementedError
