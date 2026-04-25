"""Keyframe extraction from a downloaded video file (spec M2.2)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2


def extract_keyframe(video_path: str, second: int = 3) -> str:
    """Grab the frame at `second` seconds and save it to /tmp/<uuid>.jpg.

    If the requested frame is past the end of the video, falls back to the
    last frame. Raises RuntimeError if the video can't be opened or no
    frame can be read.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target_frame = int(fps * second)
        if total_frames > 0 and target_frame >= total_frames:
            target_frame = total_frames - 1
        if target_frame < 0:
            target_frame = 0

        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        if not ret or frame is None:
            # Fallback: rewind to frame 0.
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            if not ret or frame is None:
                raise RuntimeError(f"failed to read any frame from {video_path}")

        jpg_path = f"/tmp/{uuid4()}.jpg"
        if not cv2.imwrite(jpg_path, frame):
            raise RuntimeError(f"failed to write keyframe to {jpg_path}")
        return jpg_path
    finally:
        cap.release()


def read_image_bytes(image_path: str) -> bytes:
    """Read an image file as raw bytes (used to feed Gemini Part.from_bytes)."""
    return Path(image_path).read_bytes()
