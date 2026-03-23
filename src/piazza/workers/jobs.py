"""arq worker settings and cron configuration."""

from __future__ import annotations

import asyncio
import random

import structlog
from arq import cron
from arq.connections import RedisSettings

from piazza.config.settings import settings
from piazza.core.exceptions import GENERIC_ERROR_RESPONSE, WhatsAppSendError

logger = structlog.get_logger()


# ---------- Helpers ----------


def redis_settings() -> RedisSettings:
    """Build arq RedisSettings from app settings."""
    from urllib.parse import urlparse

    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=settings.redis_password or parsed.password or None,
    )


# ---------- Job functions ----------


async def process_message_job(ctx: dict, raw_message: dict) -> str:
    """arq job wrapper for message processing.

    Deserializes the message, runs the pipeline, sends the response via WhatsApp,
    and logs both the inbound message and bot response to message_log.
    Guarantees a response is attempted even when the pipeline fails.
    """
    from piazza.db.engine import AsyncSessionFactory
    from piazza.db.repositories import message_log as message_log_repo
    from piazza.db.repositories.group import get_or_create_group
    from piazza.db.repositories.member import get_or_create_member
    from piazza.messaging.whatsapp import client
    from piazza.messaging.whatsapp.schemas import Message
    from piazza.workers.process_message import process_message

    message = Message(**raw_message)
    redis = ctx.get("redis")

    # Send typing indicator before processing (best-effort)
    await client.send_typing(message.group_jid)

    # Small random delay to feel more human (1-3 seconds)
    await asyncio.sleep(random.uniform(1.0, 3.0))

    try:
        async with AsyncSessionFactory() as session:
            response = await process_message(message, session, redis)
    except Exception:
        logger.exception(
            "process_message_job_error", group_jid=message.group_jid
        )
        response = GENERIC_ERROR_RESPONSE

    # Attempt delivery; if send_text raises after retries, log it
    wa_message_id: str | None = None
    try:
        wa_message_id = await client.send_text(message.group_jid, response)
    except WhatsAppSendError:
        logger.error(
            "message_delivery_failed",
            group_jid=message.group_jid,
            response_length=len(response),
        )

    # Log both user message and bot response to message_log (best-effort)
    try:
        async with AsyncSessionFactory() as session:
            group, _ = await get_or_create_group(session, message.group_jid)
            member = await get_or_create_member(
                session, group.id, message.sender_jid, message.sender_name
            )
            await message_log_repo.create_entry(
                session,
                group_id=group.id,
                member_id=member.id,
                role="user",
                content=message.text,
                wa_message_id=message.message_id,
            )
            await message_log_repo.create_entry(
                session,
                group_id=group.id,
                member_id=None,
                role="assistant",
                content=response,
                wa_message_id=wa_message_id,
            )
            await session.commit()
    except Exception:
        logger.exception("message_log_error", group_jid=message.group_jid)

    return response


async def fire_reminders_job(ctx: dict) -> int:
    """arq cron job to fire due reminders."""
    from piazza.db.engine import AsyncSessionFactory
    from piazza.messaging.whatsapp import client
    from piazza.tools.reminders.tasks import fire_reminders

    try:
        async with AsyncSessionFactory() as session:
            payloads = await fire_reminders(session)
    except Exception:
        logger.exception("fire_reminders_db_error")
        return 0

    sent = 0
    for group_jid, text in payloads:
        try:
            await client.send_text(group_jid, text)
            sent += 1
        except Exception:
            logger.exception("reminder_send_failed", group_jid=group_jid)

    return sent


# ---------- Worker configuration ----------


class WorkerSettings:
    functions = [process_message_job]
    redis_settings = redis_settings()
    max_jobs = 10
    job_timeout = 30
    retry_jobs = False  # Handlers have DB side effects; retry in-job instead
    max_tries = 1

    cron_jobs = [
        cron(fire_reminders_job, second={0, 30}),  # Every 30 seconds
    ]
