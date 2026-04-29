"""Reminder database queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from rapidfuzz import fuzz, process, utils
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
    recurrence: str | None = None,
) -> Reminder:
    """Create a new reminder."""
    key = _key()
    reminder = Reminder(
        group_id=group_id,
        created_by=created_by,
        message=encrypt(message, key),  # type: ignore[assignment]
        trigger_at=trigger_at,
        status="active",
        recurrence=recurrence,
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
    """Find active reminders fuzzy-matching message, ranked best-first."""
    reminders = await get_active_reminders(session, group_id)
    matches = process.extract(
        query,
        [r.message for r in reminders],
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        score_cutoff=70,
        limit=5,
    )
    return [reminders[idx] for _, _, idx in matches]


async def cancel_active_reminder(
    session: AsyncSession, reminder_id: uuid.UUID
) -> bool:
    """Cancel a reminder iff it's still active. Returns True on success.

    Guarded by `status='active'` to avoid clobbering a row the cron just
    fired or another caller just cancelled.
    """
    result = await session.execute(
        update(Reminder)
        .where(Reminder.id == reminder_id, Reminder.status == "active")
        .values(status="cancelled")
    )
    await session.flush()
    return result.rowcount > 0


async def cancel_reminder(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> Reminder | None:
    """Cancel the Nth active reminder (1-indexed) for a group."""
    reminders = await get_active_reminders(session, group_id)
    if number < 1 or number > len(reminders):
        return None

    reminder = reminders[number - 1]
    if not await cancel_active_reminder(session, reminder.id):
        return None
    reminder.status = "cancelled"
    return reminder


async def update_active_reminder(
    session: AsyncSession,
    reminder_id: uuid.UUID,
    *,
    new_trigger_at: datetime | None = None,
    new_message: str | None = None,
) -> bool:
    """Update an active reminder's trigger_at and/or message. Returns True on success.

    Guarded by status='active'; ignores fired/cancelled rows so an update
    can't accidentally resurrect them.
    """
    values: dict = {}
    if new_trigger_at is not None:
        values["trigger_at"] = new_trigger_at
    if new_message is not None:
        values["message"] = encrypt(new_message, _key())
    if not values:
        return False

    result = await session.execute(
        update(Reminder)
        .where(Reminder.id == reminder_id, Reminder.status == "active")
        .values(**values)
    )
    await session.flush()
    return result.rowcount > 0


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
