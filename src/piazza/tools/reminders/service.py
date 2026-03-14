"""Reminder business logic."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import dateparser
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import ReminderError
from piazza.db.models.group import Group
from piazza.db.repositories import note as note_repo
from piazza.db.repositories import reminder as reminder_repo

logger = structlog.get_logger()


# ---------- Private helpers ----------


def _build_reminder_note(message: str, trigger_at: datetime) -> str:
    """Build a readable knowledge-base note from a reminder."""
    time_str = trigger_at.strftime("%b %d at %H:%M UTC")
    return f"Reminder: {message} \u2014 {time_str}"


# ---------- Pure functions ----------


def parse_time(raw_expression: str, tz: str = "UTC") -> datetime:
    """Parse a natural language time expression into a UTC datetime.

    Raises ReminderError if unparseable.
    """
    parsed = dateparser.parse(
        raw_expression,
        settings={
            "TIMEZONE": tz,
            "TO_TIMEZONE": "UTC",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    if parsed is None:
        raise ReminderError(
            f"Couldn't understand the time: _{raw_expression}_. "
            "Try something like _tomorrow at 6am_ or _in 2 hours_."
        )
    return parsed


def parse_snooze_duration(duration_str: str) -> timedelta:
    """Parse a snooze duration like '1h', '30m', '2h30m'."""
    pattern = r"(?:(\d+)\s*h(?:ours?)?)?[\s,]*(?:(\d+)\s*m(?:in(?:utes?)?)?)?$"
    match = re.match(pattern, duration_str.strip(), re.IGNORECASE)
    if not match or (not match.group(1) and not match.group(2)):
        raise ReminderError(
            f"Couldn't parse duration: _{duration_str}_. Try _1h_ or _30m_."
        )
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    if hours == 0 and minutes == 0:
        raise ReminderError("Snooze duration must be at least 1 minute.")
    return timedelta(hours=hours, minutes=minutes)


# ---------- Async service functions ----------


async def set_reminder(
    session: AsyncSession,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    message: str,
    datetime_raw: str,
    tz: str = "UTC",
) -> str:
    """Parse time, create reminder, return confirmation."""
    trigger_at = parse_time(datetime_raw, tz)
    await reminder_repo.create_reminder(
        session, group_id, created_by, message, trigger_at
    )

    # Auto-note for knowledge base
    note_content = _build_reminder_note(message, trigger_at)
    await note_repo.create_note(
        session, group_id, created_by,
        content=note_content, tag=message,
    )

    await session.commit()

    formatted_time = trigger_at.strftime("%b %d at %H:%M UTC")
    return f'Reminder set: "{message}" \u2014 {formatted_time}'


async def list_reminders(
    session: AsyncSession, group_id: uuid.UUID
) -> str:
    """List active reminders as a numbered list."""
    reminders = await reminder_repo.get_active_reminders(session, group_id)
    if not reminders:
        return "No active reminders."

    lines = ["*Active Reminders*\n"]
    for i, r in enumerate(reminders, 1):
        time_str = r.trigger_at.strftime("%b %d at %H:%M UTC")
        lines.append(f"#{i} {r.message} — {time_str}")

    return "\n".join(lines)


async def cancel_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> str:
    """Cancel a reminder by its list number."""
    reminder = await reminder_repo.cancel_reminder(session, group_id, number)
    if reminder is None:
        return f"Reminder #{number} not found."
    await session.commit()
    return f'Cancelled reminder: "{reminder.message}"'


async def cancel_by_message(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> str:
    """Cancel a reminder by matching its message text."""
    matches = await reminder_repo.find_active_reminders_by_message(
        session, group_id, query
    )
    if not matches:
        return f'No active reminder matching "{query}".'
    if len(matches) > 1:
        lines = ["Multiple reminders match. Be more specific:\n"]
        for i, r in enumerate(matches[:5], 1):
            time_str = r.trigger_at.strftime("%b %d at %H:%M UTC")
            lines.append(f"#{i} {r.message} — {time_str}")
        return "\n".join(lines)

    reminder = matches[0]
    reminder.status = "cancelled"
    await session.flush()
    await session.commit()
    return f'Cancelled reminder: "{reminder.message}"'


async def snooze(
    session: AsyncSession, reminder_id: uuid.UUID, duration_str: str
) -> str:
    """Snooze a reminder by a duration string."""
    delta = parse_snooze_duration(duration_str)
    now = datetime.now(timezone.utc)
    new_trigger = now + delta
    reminder = await reminder_repo.snooze_reminder(session, reminder_id, new_trigger)
    await session.commit()

    formatted = new_trigger.strftime("%H:%M UTC")
    return f'Snoozed: "{reminder.message}" until {formatted}'


async def snooze_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int, duration_str: str
) -> str:
    """Snooze the Nth active reminder by a duration string."""
    reminders = await reminder_repo.get_active_reminders(session, group_id)
    if number < 1 or number > len(reminders):
        total = len(reminders)
        if total == 0:
            return "No active reminders to snooze."
        return f"Reminder #{number} not found. You have {total} active reminder(s)."

    reminder = reminders[number - 1]
    return await snooze(session, reminder.id, duration_str)


async def snooze_by_message(
    session: AsyncSession, group_id: uuid.UUID, query: str, duration_str: str
) -> str:
    """Snooze a reminder by matching its message text."""
    matches = await reminder_repo.find_active_reminders_by_message(
        session, group_id, query
    )
    if not matches:
        return f'No active reminder matching "{query}".'
    if len(matches) > 1:
        lines = ["Multiple reminders match. Be more specific:\n"]
        for i, r in enumerate(matches[:5], 1):
            time_str = r.trigger_at.strftime("%b %d at %H:%M UTC")
            lines.append(f"#{i} {r.message} — {time_str}")
        return "\n".join(lines)

    return await snooze(session, matches[0].id, duration_str)


async def set_group_timezone(
    session: AsyncSession, group_id: uuid.UUID, timezone_str: str
) -> str:
    """Validate and set the group timezone."""
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(timezone_str)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        return f"Unknown timezone: _{timezone_str}_. Example: _Europe/Paris_, _US/Eastern_"

    from sqlalchemy import select
    result = await session.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        return "Group not found."

    group.timezone = timezone_str
    await session.commit()
    return f"Timezone set to *{timezone_str}*"
