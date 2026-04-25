"""Line bot 事件處理 (spec M3.1).

職責邊界：
  - 接收 Line webhook event，分流到 reels / 文字 / 圖片
  - 呼叫 M2 (process_reels_url / process_image_bytes) 取結構化資料
  - 呼叫 geocoding 取座標、呼叫 embedder 算 embedding
  - 寫入 places table
  - hotel category 觸發 M4 fire-and-forget 驗證
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass

from linebot.v3.messaging import (
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    ImageMessageContent,
    MessageEvent,
    TextMessageContent,
)
from sqlalchemy import update

from app.config import settings
from app.database import SessionLocal
from app.models.place import Place
from app.services.embedder import embed
from app.services.geocoding import GeocodingError, geocode
from app.services.hotel.matcher import match_hotel
from app.services.media import (
    DownloadError,
    ExtractedContent,
    process_image_bytes,
    process_reels_url,
)

log = logging.getLogger(__name__)

IG_URL_PATTERN = re.compile(
    r"https?://(www\.)?(instagram\.com|instagr\.am)/reel[s]?/[\w-]+"
)

_CATEGORY_LABELS = {
    "food": "🍽️ 美食",
    "attraction": "🏛️ 景點",
    "hotel": "🏨 住宿",
}


@dataclass
class LineClients:
    """Webhook 啟動時建立，丟給每個 handler 用。"""

    api: AsyncMessagingApi
    blob: AsyncMessagingApiBlob


def get_session_id(user_id: str) -> str:
    """sha256(user_id) 的前 16 碼 — 不儲存真實 user_id。"""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# event dispatch
# ---------------------------------------------------------------------------

async def handle_event(event: MessageEvent, clients: LineClients) -> None:
    """Top-level 分流。永遠不向上拋例外（fire-and-forget context）。"""
    try:
        if not isinstance(event, MessageEvent):
            return

        source = getattr(event, "source", None)
        user_id = getattr(source, "user_id", None) if source else None
        if not user_id:
            return
        session_id = get_session_id(user_id)
        reply_token = event.reply_token
        message = event.message

        if isinstance(message, TextMessageContent):
            text = (message.text or "").strip()
            url_match = IG_URL_PATTERN.search(text)
            if url_match:
                await handle_reels_url(
                    url_match.group(0), reply_token, session_id, clients.api
                )
            elif text:
                await handle_plain_text(text, reply_token, session_id, clients.api)
            else:
                await _reply(clients.api, reply_token, "請輸入地點名稱或貼上 IG Reels 連結。")
        elif isinstance(message, ImageMessageContent):
            await handle_image(message.id, reply_token, session_id, clients)
        else:
            await _reply(
                clients.api,
                reply_token,
                "目前支援：IG Reels 連結、圖片、地點名稱文字",
            )
    except Exception:
        log.exception("handle_event failed")


# ---------------------------------------------------------------------------
# IG Reels URL
# ---------------------------------------------------------------------------

async def handle_reels_url(
    url: str, reply_token: str, session_id: str, line_api: AsyncMessagingApi
) -> None:
    try:
        extracted = await process_reels_url(url)
    except DownloadError as e:
        log.warning("reels download failed: %s", e)
        await _reply(line_api, reply_token, "⚠️ 無法下載此影片，請確認帳號是否公開")
        return
    except Exception:
        log.exception("process_reels_url crashed")
        await _reply(line_api, reply_token, "⚠️ 影片處理失敗，請稍後再試")
        return

    await _persist_and_reply(
        extracted=extracted,
        reply_token=reply_token,
        session_id=session_id,
        line_api=line_api,
        source_type="reels_url",
        source_url=url,
    )


# ---------------------------------------------------------------------------
# 純文字 — 直接當地點名稱
# ---------------------------------------------------------------------------

async def handle_plain_text(
    text: str, reply_token: str, session_id: str, line_api: AsyncMessagingApi
) -> None:
    extracted = ExtractedContent(
        name=text,
        category="attraction",  # 純文字無從判斷類型，預設景點
        description="",
        address_hint="",
        caption="",
        confidence=1.0,
    )
    await _persist_and_reply(
        extracted=extracted,
        reply_token=reply_token,
        session_id=session_id,
        line_api=line_api,
        source_type="text",
        source_url=None,
    )


# ---------------------------------------------------------------------------
# 圖片
# ---------------------------------------------------------------------------

async def handle_image(
    message_id: str, reply_token: str, session_id: str, clients: LineClients
) -> None:
    try:
        raw = await clients.blob.get_message_content(message_id)
        image_bytes = bytes(raw)
    except Exception:
        log.exception("download image content failed")
        await _reply(clients.api, reply_token, "⚠️ 無法取得圖片，請稍後再試")
        return

    try:
        extracted = await process_image_bytes(image_bytes)
    except Exception:
        log.exception("process_image_bytes crashed")
        await _reply(clients.api, reply_token, "⚠️ 圖片辨識失敗，請稍後再試")
        return

    await _persist_and_reply(
        extracted=extracted,
        reply_token=reply_token,
        session_id=session_id,
        line_api=clients.api,
        source_type="image",
        source_url=None,
    )


# ---------------------------------------------------------------------------
# 共用流程：confidence check → geocode → embed → INSERT → reply
# ---------------------------------------------------------------------------

async def _persist_and_reply(
    *,
    extracted: ExtractedContent,
    reply_token: str,
    session_id: str,
    line_api: AsyncMessagingApi,
    source_type: str,
    source_url: str | None,
) -> None:
    if extracted.confidence < 0.5 or not extracted.name:
        await _reply(line_api, reply_token, "🤔 無法辨識地點，請直接輸入地點名稱")
        return

    try:
        lat, lng = await geocode(extracted.name, extracted.address_hint)
    except GeocodingError as e:
        log.info("geocoding miss: %s", e)
        await _reply(
            line_api, reply_token, f"找不到「{extracted.name}」的位置，請確認地點名稱"
        )
        return

    embed_text = f"{extracted.name}。{extracted.category}。{extracted.description}"
    try:
        embedding = await embed(embed_text)
    except Exception:
        log.exception("embed failed; inserting without vector")
        embedding = None

    place = Place(
        user_session_id=session_id,
        name=extracted.name,
        category=extracted.category,
        lat=lat,
        lng=lng,
        address=None,
        description=extracted.description or None,
        source_type=source_type,
        source_url=source_url,
        reels_caption=extracted.caption or None,
        embedding=embedding,
        hotel_legal_status=None,
        hotel_match_id=None,
    )

    async with SessionLocal() as session:
        session.add(place)
        await session.commit()
        await session.refresh(place)

    if extracted.category == "hotel":
        asyncio.create_task(
            _verify_hotel_async(place.id, extracted.name, lat, lng)
        )

    label = _CATEGORY_LABELS.get(extracted.category, "📍 地點")
    msg = (
        f"✅ 已加入「{extracted.name}」！\n"
        f"類型：{label}\n"
        f"📍 查看地圖：{settings.WEB_APP_URL}?session={session_id}"
    )
    await _reply(line_api, reply_token, msg)


# ---------------------------------------------------------------------------
# Hotel fire-and-forget 驗證 (M4)
# ---------------------------------------------------------------------------

async def _verify_hotel_async(
    place_id: int, name: str, lat: float, lng: float
) -> None:
    """呼叫 M4 比對，把結果寫回 places。任何例外只 log，不上拋。"""
    try:
        result = await match_hotel(name, lat, lng)
    except NotImplementedError:
        log.info("match_hotel not implemented yet; skipping verification")
        return
    except Exception:
        log.exception("match_hotel failed for place_id=%s", place_id)
        return

    try:
        match_id = None
        if result.match and isinstance(result.match, dict):
            match_id = result.match.get("id")
        async with SessionLocal() as session:
            await session.execute(
                update(Place)
                .where(Place.id == place_id)
                .values(
                    hotel_legal_status=result.status,
                    hotel_match_id=match_id,
                )
            )
            await session.commit()
    except Exception:
        log.exception("write hotel verification failed for place_id=%s", place_id)


# ---------------------------------------------------------------------------
# Line reply helper
# ---------------------------------------------------------------------------

async def _reply(api: AsyncMessagingApi, reply_token: str, text: str) -> None:
    try:
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    except Exception:
        log.exception("line reply_message failed")
