"""M2 — IG Reels 媒體管線測試 (spec M2.3).

執行：
    cd backend && pytest tests/test_m2_media.py -v
或在 docker：
    docker compose run --rm backend pytest tests/test_m2_media.py -v

整合測試 (test_process_reels_url_integration) 需要 GEMINI_API_KEY，
否則自動 skip。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import cv2
import numpy as np
import pytest

from app.services.media import (
    ExtractedContent,
    process_image_bytes,
    process_reels_url,
)
from app.services.media import vision as vision_mod
from app.services.media.extractor import extract_keyframe, read_image_bytes


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_test_video(duration_seconds: float, fps: int = 30) -> str:
    """產生一段純色 mp4 給 OpenCV 測試用，回傳檔案路徑。"""
    path = f"/tmp/m2test-{uuid4()}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    width, height = 64, 64
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter failed to open — codec missing?")
    n_frames = max(1, int(round(duration_seconds * fps)))
    for i in range(n_frames):
        # 漸變顏色，避免空 frame。
        frame = np.full((height, width, 3), (i % 256, 128, 200), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def _make_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _install_fake_client(monkeypatch, response_text: str | None) -> list[dict]:
    """把 vision._client 換成 stub，記錄 call。回傳 calls list。"""
    calls: list[dict] = []

    async def fake_generate_content(**kwargs):
        calls.append(kwargs)
        return _make_response(response_text if response_text is not None else "")

    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=fake_generate_content)
        )
    )
    monkeypatch.setattr(vision_mod, "_client", fake_client)
    return calls


# ---------------------------------------------------------------------------
# extract_keyframe
# ---------------------------------------------------------------------------

def test_extract_keyframe_valid():
    video = _write_test_video(duration_seconds=5.0)
    try:
        jpg = extract_keyframe(video, second=3)
        assert Path(jpg).exists()
        assert Path(jpg).stat().st_size > 0
        # 可以被 OpenCV 讀回。
        img = cv2.imread(jpg)
        assert img is not None
        os.remove(jpg)
    finally:
        os.remove(video)


def test_extract_keyframe_short_video():
    """影片長度 < 3s，仍能取到 frame（fallback 到最後一格）。"""
    video = _write_test_video(duration_seconds=1.0)
    try:
        jpg = extract_keyframe(video, second=3)
        assert Path(jpg).exists()
        os.remove(jpg)
    finally:
        os.remove(video)


# ---------------------------------------------------------------------------
# vision_extract
# ---------------------------------------------------------------------------

async def test_vision_extract_mock(monkeypatch):
    payload = {
        "name": "鼎泰豐",
        "category": "food",
        "description": "知名小籠包",
        "address_hint": "信義路五段",
        "confidence": 0.92,
    }
    calls = _install_fake_client(monkeypatch, json.dumps(payload))

    result = await vision_mod.vision_extract(b"fakebytes", caption="信義區美食")

    assert result["name"] == "鼎泰豐"
    assert result["category"] == "food"
    assert result["confidence"] == pytest.approx(0.92)
    assert calls and calls[0]["model"] == "gemini-2.5-flash"


async def test_vision_extract_fallback(monkeypatch):
    """Gemini 回非 JSON / 空 / 雜訊 → 預設值。"""
    _install_fake_client(monkeypatch, "this is not json at all")
    result = await vision_mod.vision_extract(b"fakebytes", caption="")
    assert result == {
        "name": "",
        "category": "attraction",
        "description": "",
        "address_hint": "",
        "confidence": 0.0,
    }

    _install_fake_client(monkeypatch, "")
    result_empty = await vision_mod.vision_extract(b"fakebytes", caption="")
    assert result_empty["confidence"] == 0.0
    assert result_empty["name"] == ""


# ---------------------------------------------------------------------------
# process_image_bytes
# ---------------------------------------------------------------------------

async def test_process_image_bytes_returns_dataclass(monkeypatch):
    payload = {
        "name": "永康公園",
        "category": "attraction",
        "description": "綠地",
        "address_hint": "大安區",
        "confidence": 0.71,
    }
    _install_fake_client(monkeypatch, json.dumps(payload))

    result = await process_image_bytes(b"\x89PNG...")
    assert isinstance(result, ExtractedContent)
    assert result.caption == ""
    assert result.name == "永康公園"
    assert result.category == "attraction"


# ---------------------------------------------------------------------------
# cleanup-on-failure
# ---------------------------------------------------------------------------

async def test_cleanup_on_failure(monkeypatch):
    """vision_extract 拋出例外時，video / keyframe 暫存檔仍被清除。"""
    video_path = _write_test_video(duration_seconds=4.0)
    leaked_paths: dict[str, str] = {}

    async def fake_download(url):
        return video_path, "mock caption"

    real_extract = extract_keyframe

    def spy_extract(path, second=3):
        jpg = real_extract(path, second=second)
        leaked_paths["frame"] = jpg
        return jpg

    async def boom(_image_bytes, _caption):
        raise RuntimeError("Gemini exploded")

    # patch in the module that __init__ already imported the names from
    import app.services.media as media_pkg
    monkeypatch.setattr(media_pkg, "download_reels", fake_download)
    monkeypatch.setattr(media_pkg, "extract_keyframe", spy_extract)
    monkeypatch.setattr(media_pkg, "vision_extract", boom)

    with pytest.raises(RuntimeError, match="Gemini exploded"):
        await process_reels_url("https://instagram.com/reel/fake")

    assert not Path(video_path).exists(), "video temp file leaked"
    frame_path = leaked_paths.get("frame")
    assert frame_path is not None
    assert not Path(frame_path).exists(), "keyframe temp file leaked"


# ---------------------------------------------------------------------------
# helper sanity
# ---------------------------------------------------------------------------

def test_read_image_bytes_roundtrip(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello-bytes")
    assert read_image_bytes(str(p)) == b"hello-bytes"


# ---------------------------------------------------------------------------
# integration (needs real network + Gemini key)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="needs GEMINI_API_KEY to call real Gemini API",
)
@pytest.mark.skipif(
    not os.getenv("M2_INTEGRATION_REELS_URL"),
    reason="set M2_INTEGRATION_REELS_URL to a public Reels URL to run integration",
)
async def test_process_reels_url_integration():
    url = os.environ["M2_INTEGRATION_REELS_URL"]
    result = await process_reels_url(url)
    assert isinstance(result, ExtractedContent)
    assert result.confidence > 0.5
    assert result.category in {"food", "attraction", "hotel"}
