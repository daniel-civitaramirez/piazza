"""Message log database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from piazza.db.models.message_log import MessageLog


async def create_entry(
    session: AsyncSession,
    group_id: uuid.UUID,
    role: str,
    content: str,
    member_id: uuid.UUID | None = None,
    wa_message_id: str | None = None,
) -> MessageLog:
    """Log a message (user or assistant) to the conversation history."""
    entry = MessageLog(
        group_id=group_id,
        member_id=member_id,
        role=role,
        content=content,
        wa_message_id=wa_message_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_recent(
    session: AsyncSession,
    group_id: uuid.UUID,
    limit: int = 10,
) -> list[MessageLog]:
    """Get the most recent messages for a group, oldest first."""
    result = await session.execute(
        select(MessageLog)
        .options(joinedload(MessageLog.member))
        .where(MessageLog.group_id == group_id)
        .order_by(MessageLog.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()  # Return oldest first for chronological context
    return rows


async def get_by_wa_message_id(
    session: AsyncSession,
    wa_message_id: str,
) -> MessageLog | None:
    """Look up a message by its WhatsApp message ID (for reply-to resolution)."""
    result = await session.execute(
        select(MessageLog)
        .options(joinedload(MessageLog.member))
        .where(MessageLog.wa_message_id == wa_message_id)
    )
    return result.scalar_one_or_none()
