"""FastAPI webhook endpoint for Evolution API."""

from __future__ import annotations

import hashlib
import hmac

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, Request, Response

from piazza.config.settings import settings
from piazza.core.exceptions import GENERIC_ERROR_RESPONSE
from piazza.messaging.whatsapp.group_sync import (
    handle_group_participants_update,
    handle_group_upsert,
    learn_display_name,
)
from piazza.messaging.whatsapp.parser import extract_sender_info, parse_webhook

logger = structlog.get_logger()

router = APIRouter()


def verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature from Evolution API."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _fallback_process(raw_message: dict) -> None:
    """Process a message in-process when arq is unavailable (degraded mode)."""
    from piazza.db.engine import AsyncSessionFactory
    from piazza.messaging.whatsapp import client
    from piazza.messaging.whatsapp.schemas import Message
    from piazza.workers.process_message import process_message

    message = Message(**raw_message)
    try:
        await client.send_typing(message.group_jid)
        async with AsyncSessionFactory() as session:
            response = await process_message(message, session, redis=None)
    except Exception:
        logger.exception("fallback_process_error")
        response = GENERIC_ERROR_RESPONSE

    try:
        await client.send_text(message.group_jid, response)
    except Exception:
        logger.exception("fallback_send_failed")


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: str | None = Header(None, alias="x-webhook-signature"),
) -> Response:
    """Receive Evolution API webhook events.

    Always returns 200 to prevent Evolution API retries.
    """
    body = await request.body()

    # HMAC verification (if webhook_secret is configured)
    if settings.webhook_secret:
        if not x_webhook_signature:
            logger.warning("webhook_missing_signature")
            return Response(status_code=200)

        if not verify_hmac(body, x_webhook_signature, settings.webhook_secret):
            logger.warning("webhook_invalid_signature")
            return Response(status_code=200)

    raw: dict = await request.json()
    event = raw.get("event", "")
    logger.debug("webhook_raw_event", event=event, keys=list(raw.keys()))

    if event == "messages.upsert":
        # Learn display name from every group message (lightweight, before mention gate)
        sender_info = extract_sender_info(raw, settings.bot_jid)
        if sender_info:
            background_tasks.add_task(learn_display_name, *sender_info)

        # Full pipeline only for @mentioned / reply-to-bot messages
        message = parse_webhook(raw, settings.bot_jid)
        if message is None:
            return Response(status_code=200)

        # Enqueue for async processing
        arq_pool = request.app.state.arq_pool
        if arq_pool is None:
            logger.warning("webhook_no_arq_pool_fallback")
            background_tasks.add_task(_fallback_process, message.model_dump())
            return Response(status_code=200)

        await arq_pool.enqueue_job("process_message_job", message.model_dump())
        logger.info("webhook_enqueued")

    elif event == "groups.upsert":
        background_tasks.add_task(handle_group_upsert, raw)

    elif event in ("group-participants.update", "group.participants.update"):
        background_tasks.add_task(handle_group_participants_update, raw)

    else:
        logger.debug("webhook_ignored_event", webhook_event=event)

    return Response(status_code=200)
