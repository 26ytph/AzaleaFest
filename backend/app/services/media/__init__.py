"""M2 公開介面 — M3 import 的唯一入口 (spec M2.1).

實作見 downloader.py / extractor.py / vision.py。
"""
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


async def process_reels_url(url: str) -> ExtractedContent:
    """M3 呼叫的唯一入口（IG Reels URL）"""
    raise NotImplementedError


async def process_image_bytes(image_bytes: bytes) -> ExtractedContent:
    """M3 呼叫的唯一入口（使用者上傳圖片）"""
    raise NotImplementedError
