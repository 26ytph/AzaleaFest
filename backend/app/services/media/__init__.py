"""M2 公開介面 — M3 import 的唯一入口 (spec M2.1).

實作見 downloader.py / extractor.py / vision.py。
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ExtractedContent:
    name: str           # 地點名稱
    category: str       # 'food' | 'attraction' | 'hotel'
    description: str    # 50 字以內
    address_hint: str   # 地址線索，可為空字串
    caption: str        # yt-dlp info_dict['description']，原始 caption
    confidence: float   # 0.0–1.0


class DownloadError(Exception):
    """yt-dlp 下載失敗（私人帳號、地區限制等）"""


# Imports placed after the symbols above so submodules can `from . import
# DownloadError` without hitting a circular import.
from .downloader import download_reels  # noqa: E402
from .extractor import extract_keyframe, read_image_bytes  # noqa: E402
from .vision import vision_extract  # noqa: E402


def _safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


async def process_reels_url(url: str) -> ExtractedContent:
    """M3 呼叫的唯一入口（IG Reels URL）。

    DownloadError 會直接往上拋，由 M3 catch。其他例外（vision、檔案 IO）
    也會往上傳遞，但 try/finally 保證 /tmp 暫存檔被清掉。
    """
    video_path, caption = await download_reels(url)
    frame_path: str | None = None
    try:
        frame_path = extract_keyframe(video_path, second=3)
        img_bytes = read_image_bytes(frame_path)
        extracted = await vision_extract(img_bytes, caption)
    finally:
        _safe_remove(video_path)
        _safe_remove(frame_path)

    return ExtractedContent(caption=caption, **extracted)


async def process_image_bytes(image_bytes: bytes) -> ExtractedContent:
    """M3 呼叫的唯一入口（使用者上傳圖片）。"""
    extracted = await vision_extract(image_bytes, caption="")
    return ExtractedContent(caption="", **extracted)
