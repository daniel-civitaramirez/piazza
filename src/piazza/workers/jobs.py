"""arq worker settings and cron configuration."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import structlog
from arq import cron
from arq.connections import RedisSettings

from piazza.config.settings import settings
from piazza.core.exceptions import GENERIC_ERROR_RESPONSE, RATE_LIMITED_RESPONSE, WhatsAppSendError
from piazza.core.fx import FxProvider, init_fx_provider
from piazza.db import engine as db_engine
from piazza.db.repositories import message_log as message_log_repo
from piazza.db.repositories.group import get_or_create_group
from piazza.db.repositories.member import get_or_create_member
from piazza.messaging.whatsapp import client
from piazza.messaging.whatsapp.schemas import Message
from piazza.tools.reminders.tasks import fire_reminders
from piazza.workers import process_message as process_message_module

logger = structlog.get_logger()


def redis_settings() -> RedisSettings:
    """Build arq RedisSettings from app settings."""
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=settings.redis_password or parsed.password or None,
    )


async def _on_startup(ctx: dict) -> None:
    init_fx_provider(
        FxProvider(
            api_key=settings.openexchangerates_key,
            redis=ctx.get("redis"),
            cache_ttl_seconds=settings.fx_cache_ttl_seconds,
        )
    )
    logger.info("worker_fx_provider_initialized", configured=bool(settings.openexchangerates_key))


async def process_message_job(ctx: dict, raw_message: dict) -> str:
    """arq job wrapper for message processing.

    Deserializes the message, runs the pipeline, sends the response via WhatsApp,
    and logs both the inbound message and bot response to message_log.
    Guarantees a response is attempted even when the pipeline fails.
    """
    message = Message(**raw_message)
    redis = ctx.get("redis")
    logger.info("job_started")

    async def _keep_typing() -> None:
        while True:
            await client.send_typing(message.group_jid)
            await asyncio.sleep(1.0)

    typing_task = asyncio.create_task(_keep_typing())

    try:
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
                    async with db_engine.AsyncSessionFactory() as session:
                        response = await process_message_module.process_message(
                            message, session, redis
                        )
            else:
                async with db_engine.AsyncSessionFactory() as session:
                    response = await process_message_module.process_message(
                        message, session, redis
                    )
        except Exception:
            logger.exception("process_message_job_error")
            response = GENERIC_ERROR_RESPONSE
        finally:
            try:
                if lock and await lock.owned():
                    await lock.release()
            except Exception:
                logger.warning("group_lock_release_failed")

        logger.info("job_response_ready")

        wa_message_id: str | None = None
        try:
            wa_message_id = await client.send_text(message.group_jid, response)
            logger.info("job_response_sent", wa_message_id=wa_message_id)
        except WhatsAppSendError:
            logger.error(
                "message_delivery_failed",
                response_length=len(response),
            )
    finally:
        typing_task.cancel()

    try:
        async with db_engine.AsyncSessionFactory() as session:
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
            multiplier = max(settings.message_log_retention_multiplier, 2)
            keep = settings.conversation_context_limit * multiplier
            await message_log_repo.delete_old_entries(session, group.id, keep)

            await session.commit()
    except Exception:
        logger.exception("message_log_error")

    return response


async def fire_reminders_job(ctx: dict) -> int:
    """arq cron job to fire due reminders."""
    try:
        async with db_engine.AsyncSessionFactory() as session:
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


class WorkerSettings:
    functions = [process_message_job]
    redis_settings = redis_settings()
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    retry_jobs = False
    max_tries = 1
    on_startup = _on_startup

    cron_jobs = [
        cron(fire_reminders_job, second=settings.reminder_cron_seconds_set),
    ]
