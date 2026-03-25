"""Main message processing pipeline."""

from __future__ import annotations

import re
import time

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.agent import get_claude_agent, get_opensource_agent
from piazza.agent.base import AgentTimeoutError, AgentUnavailableError
from piazza.agent.context import AgentContext
from piazza.config.settings import settings
from piazza.core.encryption import hash_phone
from piazza.core.exceptions import (
    FLAGGED_RESPONSE,
    GENERIC_ERROR_RESPONSE,
    UNAPPROVED_GROUP_RESPONSE,
)
from piazza.db.models.injection_log import InjectionLog
from piazza.db.repositories.group import get_or_create_group
from piazza.db.repositories.member import get_active_members, get_or_create_member
from piazza.messaging.whatsapp.schemas import Message
from piazza.workers.security.guard import screen_for_injection
from piazza.workers.security.sanitizer import sanitize_input

logger = structlog.get_logger()

CB_KEY = "circuit:agent:ollama:failures"
CB_OPEN_KEY = "circuit:agent:ollama:open"


# --- Private helpers ---


def _strip_bot_mention(text: str, mentioned_jids: list[str]) -> str:
    """Remove @mention markers for mentioned JIDs from the message text."""
    result = text
    for jid in mentioned_jids:
        number = jid.split("@")[0]
        result = re.sub(rf"@{re.escape(number)}\s*", "", result)
    return result.strip()


async def _log_injection(
    session: AsyncSession,
    group_id: object,
    user_hash: str,
    layer: str,
    risk_score: float,
    snippet: str,
) -> None:
    """Log an injection-flagged message."""
    entry = InjectionLog(
        group_id=group_id,
        user_hash=user_hash,
        layer=layer,
        risk_score=risk_score,
        snippet=snippet[:100] if snippet else None,
    )
    session.add(entry)
    await session.flush()
    logger.warning(
        "injection_flagged",
        layer=layer,
        group_id=str(group_id),
        user_hash=user_hash,
        risk_score=risk_score,
    )
    await session.commit()


async def _circuit_is_open(redis: Redis | None) -> bool:
    if redis is None:
        return False
    return await redis.exists(CB_OPEN_KEY) > 0


async def _circuit_record_failure(redis: Redis) -> None:
    now = time.time()
    pipe = redis.pipeline()
    pipe.zadd(CB_KEY, {str(now): now})
    pipe.zremrangebyscore(CB_KEY, "-inf", now - settings.circuit_breaker_window)
    pipe.zcard(CB_KEY)
    results = await pipe.execute()
    failure_count = results[2]

    if failure_count >= settings.circuit_breaker_failures:
        await redis.set(CB_OPEN_KEY, "1", ex=settings.circuit_breaker_cooldown)
        logger.warning("agent_circuit_breaker_opened", failures=failure_count)


async def _run_agent(context: AgentContext, redis: Redis | None) -> str:
    """Try open-source agent first, fall back to Claude on failure."""
    if not await _circuit_is_open(redis):
        try:
            return await get_opensource_agent().run(context)
        except (AgentTimeoutError, AgentUnavailableError) as exc:
            logger.warning("opensource_agent_failed", error=str(exc))
            if redis:
                await _circuit_record_failure(redis)

    try:
        return await get_claude_agent().run(context)
    except (AgentTimeoutError, AgentUnavailableError) as exc:
        logger.exception("claude_agent_error", error=str(exc))
        return GENERIC_ERROR_RESPONSE
    except Exception:
        logger.exception("agent_unexpected_error")
        return GENERIC_ERROR_RESPONSE


# --- Main pipeline ---


async def process_message(
    message: Message,
    session: AsyncSession,
    redis: Redis | None,
) -> str:
    """Process a message through security screening and the agent pipeline."""
    start_time = time.monotonic()

    try:
        # 1. Setup
        group, _ = await get_or_create_group(session, message.group_jid)

        if group.approval_status != "approved":
            logger.info(
                "unapproved_group_rejected",
                group_id=str(group.id),
                status=group.approval_status,
            )
            return UNAPPROVED_GROUP_RESPONSE

        member = await get_or_create_member(
            session, group.id, message.sender_jid, message.sender_name,
        )
        await session.commit()

        text = _strip_bot_mention(message.text, message.mentioned_jids)

        # 2. Security: sanitize + injection screening
        sanitized, flagged_l1 = sanitize_input(text)
        if flagged_l1:
            await _log_injection(
                session, group.id, hash_phone(message.sender_jid),
                "L1", 1.0, sanitized,
            )
            return FLAGGED_RESPONSE

        screened, flagged_l2, risk = screen_for_injection(sanitized)
        if flagged_l2:
            await _log_injection(
                session, group.id, hash_phone(message.sender_jid),
                "L2", risk, sanitized,
            )
            return FLAGGED_RESPONSE

        # 3. Build agent context
        active_members = await get_active_members(session, group.id)
        context = AgentContext(
            text=screened,
            sender_name=message.sender_name,
            member_names=[m.display_name for m in active_members],
            session=session,
            group_id=group.id,
            member_id=member.id,
            reply_to_id=message.reply_to_message_id,
        )

        # 4. Run agent (open-source → Claude fallback)
        response = await _run_agent(context, redis)

    except Exception:
        logger.exception("pipeline_error")
        return GENERIC_ERROR_RESPONSE

    processing_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "message_processed",
        group_id=str(group.id),
        processing_ms=processing_ms,
    )
    return response
