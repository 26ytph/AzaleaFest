"""Gemini 2.5 Flash vision extractor (spec M2.2)."""
from __future__ import annotations

import json

from google import genai
from google.genai import types

from app.config import settings

SYSTEM_PROMPT = """你是地點資訊提取助手。從圖片和文字中識別被拍攝的地點。
只回傳 JSON,不包含任何說明文字或 markdown 符號。"""

USER_PROMPT_TEMPLATE = """
圖片如附。
社群媒體原文(可能為空): {caption}

回傳以下 JSON(無其他文字):
{{
  "name": "地點名稱(繁體中文優先)",
  "category": "food 或 attraction 或 hotel",
  "description": "50字以內描述",
  "address_hint": "地址線索(無則空字串)",
  "confidence": 0.85
}}

判斷規則:
- confidence < 0.5: 圖片無明顯地點(純食物特寫、人物照等)
- food: 餐廳、咖啡廳、攤位、夜市
- hotel: 旅館、飯店、民宿室內
- attraction: 景點、公園、商場、其他
"""

_DEFAULT_RESULT: dict = {
    "name": "",
    "category": "attraction",
    "description": "",
    "address_hint": "",
    "confidence": 0.0,
}

_ALLOWED_KEYS = set(_DEFAULT_RESULT.keys())

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


async def vision_extract(image_bytes: bytes, caption: str) -> dict:
    """Call Gemini vision and return a normalized dict.

    Returns the default fallback dict on parse failure or empty response.
    """
    client = _get_client()

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            USER_PROMPT_TEMPLATE.format(caption=caption or ""),
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    text = (response.text or "").strip()
    if not text:
        return dict(_DEFAULT_RESULT)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return dict(_DEFAULT_RESULT)

    if not isinstance(parsed, dict):
        return dict(_DEFAULT_RESULT)

    # Merge with defaults so missing keys don't break the dataclass.
    result = dict(_DEFAULT_RESULT)
    for key in _ALLOWED_KEYS:
        if key in parsed:
            result[key] = parsed[key]
    # Coerce types defensively.
    result["name"] = str(result["name"] or "")
    result["category"] = str(result["category"] or "attraction")
    result["description"] = str(result["description"] or "")
    result["address_hint"] = str(result["address_hint"] or "")
    try:
        result["confidence"] = float(result["confidence"])
    except (TypeError, ValueError):
        result["confidence"] = 0.0
    if result["category"] not in ("food", "attraction", "hotel"):
        result["category"] = "attraction"
    return result
