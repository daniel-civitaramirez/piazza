"""Reminder intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.models.group import Group
from piazza.tools.reminders import service
from piazza.tools.schemas import Entities


async def _get_group_tz(session: AsyncSession, group_id: uuid.UUID) -> str:
    result = await session.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    return group.timezone if group else "UTC"


async def handle_reminder_set(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Set a new reminder."""
    if not entities.datetime_raw and not entities.description:
        return "Please specify a reminder. Example: _@Piazza remind us: meeting tomorrow 9am_"

    message = entities.description or "Reminder"
    datetime_raw = entities.datetime_raw or ""
    if not datetime_raw:
        return "Please include a time. Example: _tomorrow at 6am_ or _in 2 hours_"

    tz = await _get_group_tz(session, group_id)
    return await service.set_reminder(
        session, group_id, sender_id, message, datetime_raw, tz
    )


async def handle_reminder_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """List active reminders."""
    return await service.list_reminders(session, group_id)


async def handle_reminder_cancel(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Cancel a reminder by number or by matching message text."""
    if entities.reminder_number is not None:
        return await service.cancel_by_number(session, group_id, entities.reminder_number)

    if entities.description:
        return await service.cancel_by_message(session, group_id, entities.description)

    return (
        "Please specify which reminder to cancel. "
        "Example: _cancel reminder #1_ or _cancel the dentist reminder_"
    )


async def handle_reminder_snooze(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Snooze a reminder by number or message text, with a duration."""
    duration = entities.datetime_raw
    if not duration:
        return "Please specify a snooze duration. Example: _snooze #2 1h_ or _snooze dentist 30m_"

    if entities.reminder_number is not None:
        return await service.snooze_by_number(
            session, group_id, entities.reminder_number, duration
        )

    if entities.description:
        return await service.snooze_by_message(
            session, group_id, entities.description, duration
        )

    return (
        "Please specify which reminder to snooze. "
        "Example: _snooze #2 1h_ or _snooze the dentist reminder 30m_"
    )


async def handle_set_timezone(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Set the group timezone."""
    tz = entities.description or ""
    if not tz:
        return "Please specify a timezone. Example: _@Piazza set timezone Europe/Paris_"
    return await service.set_group_timezone(session, group_id, tz)
