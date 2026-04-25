"""Line webhook router (M3 owns). Mounted at /webhook by main.py.

POST /webhook/line
  - 從 header X-Line-Signature 驗證簽章
  - 用 WebhookParser 解析 body 為 events
  - 對每個 event asyncio.create_task(handle_event(...))
  - 永遠回 200（Line 要求）
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, Request, Response
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
)

from app.config import settings
from app.services.line_handler import LineClients, handle_event

log = logging.getLogger(__name__)

router = APIRouter()

_parser: WebhookParser | None = None
_clients: LineClients | None = None


def _get_parser() -> WebhookParser:
    global _parser
    if _parser is None:
        _parser = WebhookParser(settings.LINE_CHANNEL_SECRET)
    return _parser


def _get_clients() -> LineClients:
    global _clients
    if _clients is None:
        config = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)
        api_client = AsyncApiClient(config)
        _clients = LineClients(
            api=AsyncMessagingApi(api_client),
            blob=AsyncMessagingApiBlob(api_client),
        )
    return _clients


@router.post("/line")
async def line_webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
) -> Response:
    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")

    try:
        events = _get_parser().parse(body, x_line_signature)
    except InvalidSignatureError:
        log.warning("invalid line signature")
        return Response(status_code=200)
    except Exception:
        log.exception("line webhook parse failed")
        return Response(status_code=200)

    clients = _get_clients()
    for event in events:
        asyncio.create_task(handle_event(event, clients))

    return Response(status_code=200)
