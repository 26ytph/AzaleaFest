"""IG Reels downloader using yt-dlp (spec M2.2).

yt-dlp 是同步 API，用 asyncio.to_thread() 包裝避免阻塞 event loop。
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import yt_dlp

from app.config import settings

from . import DownloadError


def _stage_cookies() -> str | None:
    """Copy the configured cookies file to a writable temp path.

    yt-dlp updates the cookies file in place (Set-Cookie from IG); the host
    mount is read-only by design, so we work on a /tmp copy.
    """
    src = settings.IG_COOKIES_PATH
    if not src or not Path(src).exists():
        return None
    dst = f"/tmp/{uuid4()}-cookies.txt"
    shutil.copyfile(src, dst)
    return dst


def _download_sync(url: str) -> tuple[str, str]:
    out_template = f"/tmp/{uuid4()}.%(ext)s"
    ydl_opts = {
        # Spec calls for <=480p to keep download light, but IG sometimes only
        # serves higher resolutions; fall back to `best` if no match.
        "format": "best[height<=480]/best",
        "outtmpl": out_template,
        "quiet": True,
        "no_warnings": True,
    }
    cookies_tmp = _stage_cookies()
    if cookies_tmp:
        ydl_opts["cookiefile"] = cookies_tmp

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlp expands %(ext)s; prepare_filename gives the actual on-disk path.
            video_path = ydl.prepare_filename(info)
            caption = info.get("description") or ""
    finally:
        if cookies_tmp:
            try:
                Path(cookies_tmp).unlink(missing_ok=True)
            except OSError:
                pass

    return video_path, caption


async def download_reels(url: str) -> tuple[str, str]:
    """Download an IG Reels URL and return (video_path, caption).

    Raises DownloadError on any yt-dlp failure (private account, region
    block, network error, etc.).
    """
    try:
        return await asyncio.to_thread(_download_sync, url)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc)) from exc
    except Exception as exc:
        raise DownloadError(str(exc)) from exc
