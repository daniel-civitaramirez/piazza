"""arq worker settings and cron configuration."""

from __future__ import annotations

import asyncio
import random
import time

import structlog
from arq import cron
from arq.connections import RedisSettings

from piazza.config.settings import settings
from piazza.core.exceptions import GENERIC_ERROR_RESPONSE, RATE_LIMITED_RESPONSE, WhatsAppSendError

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
    await asyncio.sleep(random.uniform(settings.human_delay_min, settings.human_delay_max))

    # Per-group rate limiting
    if redis and settings.group_rate_limit_per_minute > 0:
        rate_key = f"rate:group:{message.group_jid}"
        now = time.time()
        pipe = redis.pipeline()
        pipe.zadd(rate_key, {str(now): now})
        pipe.zremrangebyscore(rate_key, "-inf", now - 60)
        pipe.zcard(rate_key)
        pipe.expire(rate_key, 60)
        results = await pipe.execute()
        if results[2] > settings.group_rate_limit_per_minute:
            logger.warning("group_rate_limited", count=results[2])
            try:
                await client.send_text(message.group_jid, RATE_LIMITED_RESPONSE)
            except WhatsAppSendError:
                pass
            return RATE_LIMITED_RESPONSE

    # Serialize processing per group to prevent race conditions
    lock = (
        redis.lock(f"lock:group:{message.group_jid}", timeout=settings.group_lock_timeout)
        if redis else None
    )
    try:
        if lock:
            acquired = await lock.acquire(blocking_timeout=settings.group_lock_wait)
            if not acquired:
                logger.warning("group_lock_timeout")
                response = GENERIC_ERROR_RESPONSE
            else:
                async with AsyncSessionFactory() as session:
                    response = await process_message(message, session, redis)
        else:
            async with AsyncSessionFactory() as session:
                response = await process_message(message, session, redis)
    except Exception:
        logger.exception("process_message_job_error")
        response = GENERIC_ERROR_RESPONSE
    finally:
        try:
            if lock and await lock.owned():
                await lock.release()
        except Exception:
            logger.warning("group_lock_release_failed")

    # Attempt delivery; if send_text raises after retries, log it
    wa_message_id: str | None = None
    try:
        wa_message_id = await client.send_text(message.group_jid, response)
    except WhatsAppSendError:
        logger.error(
            "message_delivery_failed",
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
            # Prune old messages beyond retention window (min 2x context to avoid
            # races with concurrent hydration)
            multiplier = max(settings.message_log_retention_multiplier, 2)
            keep = settings.conversation_context_limit * multiplier
            await message_log_repo.delete_old_entries(session, group.id, keep)

            await session.commit()
    except Exception:
        logger.exception("message_log_error")

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
            logger.exception("reminder_send_failed")

    return sent


# ---------- Worker configuration ----------


class WorkerSettings:
    functions = [process_message_job]
    redis_settings = redis_settings()
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    retry_jobs = False  # Handlers have DB side effects; retry in-job instead
    max_tries = 1

    cron_jobs = [
        cron(fire_reminders_job, second=settings.reminder_cron_seconds_set),
    ]
