"""Message log database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from piazza.config.settings import settings
from piazza.core.encryption import decrypt, encrypt, set_decrypted
from piazza.db.models.message_log import MessageLog


def _key() -> bytes:
    return settings.encryption_key_bytes


async def create_entry(
    session: AsyncSession,
    group_id: uuid.UUID,
    role: str,
    content: str,
    member_id: uuid.UUID | None = None,
    wa_message_id: str | None = None,
) -> MessageLog:
    """Log a message (user or assistant) to the conversation history."""
    key = _key()
    entry = MessageLog(
        group_id=group_id,
        member_id=member_id,
        role=role,
        content=encrypt(content, key),  # type: ignore[assignment]
        wa_message_id=wa_message_id,
    )
    session.add(entry)
    await session.flush()
    set_decrypted(entry, "content", content)
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
    key = _key()
    for msg in rows:
        set_decrypted(msg, "content", decrypt(msg.content, key))
        if msg.member:
            set_decrypted(msg.member, "display_name", decrypt(msg.member.display_name, key))
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
    msg = result.scalar_one_or_none()
    if msg is not None:
        key = _key()
        set_decrypted(msg, "content", decrypt(msg.content, key))
        if msg.member:
            set_decrypted(msg.member, "display_name", decrypt(msg.member.display_name, key))
    return msg


async def delete_old_entries(
    session: AsyncSession, group_id: uuid.UUID, keep: int
) -> int:
    """Delete messages beyond the `keep` most recent for a group.

    Returns the number of rows deleted.
    """
    keep_ids = (
        select(MessageLog.id)
        .where(MessageLog.group_id == group_id)
        .order_by(MessageLog.created_at.desc())
        .limit(keep)
    ).scalar_subquery()
    result = await session.execute(
        delete(MessageLog).where(
            MessageLog.group_id == group_id,
            MessageLog.id.not_in(keep_ids),
        )
    )
    return result.rowcount
