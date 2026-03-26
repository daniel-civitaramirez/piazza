"""Reminder database queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from piazza.config.settings import settings
from piazza.core.encryption import decrypt, encrypt, set_decrypted
from piazza.db.models.reminder import Reminder


def _key() -> bytes:
    return settings.encryption_key_bytes


async def create_reminder(
    session: AsyncSession,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    message: str,
    trigger_at: datetime,
) -> Reminder:
    """Create a new reminder."""
    key = _key()
    reminder = Reminder(
        group_id=group_id,
        created_by=created_by,
        message=encrypt(message, key),  # type: ignore[assignment]
        trigger_at=trigger_at,
        status="active",
    )
    session.add(reminder)
    await session.flush()
    set_decrypted(reminder, "message", message)
    return reminder


async def get_active_reminders(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Reminder]:
    """Get all active reminders for a group, ordered by trigger_at."""
    result = await session.execute(
        select(Reminder)
        .where(Reminder.group_id == group_id, Reminder.status == "active")
        .order_by(Reminder.trigger_at)
    )
    reminders = list(result.scalars().all())
    key = _key()
    for r in reminders:
        set_decrypted(r, "message", decrypt(r.message, key))
    return reminders


async def get_due_reminders(
    session: AsyncSession, now: datetime
) -> list[Reminder]:
    """Get all reminders that are due (trigger_at <= now and active)."""
    result = await session.execute(
        select(Reminder)
        .options(selectinload(Reminder.group))
        .where(Reminder.trigger_at <= now, Reminder.status == "active")
    )
    reminders = list(result.scalars().all())
    key = _key()
    for r in reminders:
        set_decrypted(r, "message", decrypt(r.message, key))
    return reminders


async def find_active_reminders_by_message(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> list[Reminder]:
    """Find active reminders whose message matches query (case-insensitive)."""
    reminders = await get_active_reminders(session, group_id)
    return [
        r for r in reminders
        if query.lower() in r.message.lower()  # type: ignore[union-attr]
    ]


async def cancel_reminder(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> Reminder | None:
    """Cancel the Nth active reminder (1-indexed) for a group."""
    reminders = await get_active_reminders(session, group_id)
    if number < 1 or number > len(reminders):
        return None

    reminder = reminders[number - 1]
    reminder.status = "cancelled"
    await session.flush()
    return reminder


async def snooze_reminder(
    session: AsyncSession, reminder_id: uuid.UUID, new_trigger_at: datetime
) -> Reminder:
    """Snooze a reminder to a new time."""
    result = await session.execute(
        select(Reminder).where(Reminder.id == reminder_id)
    )
    reminder = result.scalar_one()
    reminder.trigger_at = new_trigger_at
    reminder.status = "active"
    await session.flush()
    set_decrypted(reminder, "message", decrypt(reminder.message, _key()))
    return reminder


async def update_reminder_status(
    session: AsyncSession,
    reminder_id: uuid.UUID,
    status: str,
    next_trigger_at: datetime | None = None,
) -> None:
    """Update a reminder's status and optionally its next trigger time."""
    values: dict = {"status": status}
    if next_trigger_at is not None:
        values["trigger_at"] = next_trigger_at

    await session.execute(
        update(Reminder).where(Reminder.id == reminder_id).values(**values)
    )
    await session.flush()
