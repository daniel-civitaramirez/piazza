"""Reminder business logic."""

from __future__ import annotations

import re
import uuid
import zoneinfo
from datetime import datetime, timedelta, timezone

import dateparser
import structlog
from dateutil.rrule import rrulestr
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError, ReminderError
from piazza.db.models.group import Group
from piazza.db.models.reminder import Reminder
from piazza.db.repositories import note as note_repo
from piazza.db.repositories import reminder as reminder_repo

logger = structlog.get_logger()


# ---------- Private helpers ----------


def _build_reminder_note(message: str, trigger_at: datetime) -> str:
    """Build a readable knowledge-base note from a reminder."""
    time_str = trigger_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"{message} — {time_str}"


def _resolve_tz(tz: str) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(tz)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        return zoneinfo.ZoneInfo("UTC")


def _validate_rrule(rule: str, tz: str = "UTC") -> None:
    """Validate an iCalendar RRULE string. Raises ReminderError if invalid."""
    try:
        rrulestr(rule, dtstart=datetime.now(_resolve_tz(tz)))
    except (ValueError, TypeError) as exc:
        raise ReminderError(
            f"Couldn't understand the recurrence rule: _{rule}_."
        ) from exc


def next_occurrence(rule: str, after: datetime, tz: str = "UTC") -> datetime | None:
    """Return the next occurrence of the rule strictly after `after`, or None if exhausted.

    BYHOUR/BYMINUTE in the rule are interpreted in `tz`. The returned datetime
    is normalized to UTC for storage.
    """
    zone = _resolve_tz(tz)
    local_after = after.astimezone(zone) if after.tzinfo else after.replace(tzinfo=zone)
    nxt = rrulestr(rule, dtstart=local_after).after(local_after, inc=False)
    if nxt is None:
        return None
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=zone)
    return nxt.astimezone(timezone.utc)


def occurrences_between(
    rule: str, start: datetime, end: datetime, tz: str = "UTC"
) -> list[datetime]:
    """Return rule occurrences strictly after `start` and at-or-before `end`, in UTC."""
    zone = _resolve_tz(tz)
    local_start = start.astimezone(zone) if start.tzinfo else start.replace(tzinfo=zone)
    local_end = end.astimezone(zone) if end.tzinfo else end.replace(tzinfo=zone)
    rule_set = rrulestr(rule, dtstart=local_start)
    out: list[datetime] = []
    for occ in rule_set.between(local_start, local_end, inc=False):
        if occ.tzinfo is None:
            occ = occ.replace(tzinfo=zone)
        out.append(occ.astimezone(timezone.utc))
    return out


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
    datetime_raw: str | None,
    tz: str = "UTC",
    recurrence: str | None = None,
) -> Reminder:
    """Parse time, create reminder, return the Reminder model.

    For recurring reminders, `datetime_raw` is optional — if omitted, the first
    fire time is derived from the RRULE.
    """
    if recurrence:
        _validate_rrule(recurrence, tz)

    if datetime_raw:
        trigger_at = parse_time(datetime_raw, tz)
    elif recurrence:
        next_at = next_occurrence(recurrence, datetime.now(timezone.utc), tz)
        if next_at is None:
            raise ReminderError(
                f"Recurrence rule has no future occurrences: _{recurrence}_."
            )
        trigger_at = next_at
    else:
        raise ReminderError(
            "A reminder needs either a time or a recurrence rule."
        )

    reminder = await reminder_repo.create_reminder(
        session, group_id, created_by, message, trigger_at,
        recurrence=recurrence,
    )

    # Auto-note for knowledge base
    note_content = _build_reminder_note(message, trigger_at)
    await note_repo.create_note(
        session, group_id, created_by,
        content=note_content, tag=message,
    )

    await session.commit()
    return reminder


async def list_reminders(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Reminder]:
    """Return active reminders (may be empty)."""
    return await reminder_repo.get_active_reminders(session, group_id)


async def cancel_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> Reminder:
    """Cancel a reminder by its list number. Raises NotFoundError."""
    reminder = await reminder_repo.cancel_reminder(session, group_id, number)
    if reminder is None:
        active = await reminder_repo.get_active_reminders(session, group_id)
        raise NotFoundError("reminder", number=number, total=len(active))
    await session.commit()
    return reminder


async def cancel_by_message(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> Reminder | list[Reminder]:
    """Cancel a reminder by matching its message text.

    Returns single Reminder on success, or list[Reminder] for ambiguous matches.
    Raises NotFoundError when no matches.
    """
    matches = await reminder_repo.find_active_reminders_by_message(
        session, group_id, query
    )
    if not matches:
        raise NotFoundError("reminder", query=query)
    if len(matches) > 1:
        return matches[:5]

    reminder = matches[0]
    reminder.status = "cancelled"
    await session.flush()
    await session.commit()
    return reminder


async def snooze(
    session: AsyncSession, reminder_id: uuid.UUID, duration_str: str
) -> Reminder:
    """Snooze a reminder by a duration string."""
    delta = parse_snooze_duration(duration_str)
    now = datetime.now(timezone.utc)
    new_trigger = now + delta
    reminder = await reminder_repo.snooze_reminder(session, reminder_id, new_trigger)
    await session.commit()
    return reminder


async def snooze_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int, duration_str: str
) -> Reminder:
    """Snooze the Nth active reminder. Raises NotFoundError."""
    reminders = await reminder_repo.get_active_reminders(session, group_id)
    if number < 1 or number > len(reminders):
        raise NotFoundError("reminder", number=number, total=len(reminders))

    reminder = reminders[number - 1]
    return await snooze(session, reminder.id, duration_str)


async def snooze_by_message(
    session: AsyncSession, group_id: uuid.UUID, query: str, duration_str: str
) -> Reminder | list[Reminder]:
    """Snooze a reminder by matching its message text.

    Returns single Reminder on success, or list[Reminder] for ambiguous matches.
    Raises NotFoundError when no matches.
    """
    matches = await reminder_repo.find_active_reminders_by_message(
        session, group_id, query
    )
    if not matches:
        raise NotFoundError("reminder", query=query)
    if len(matches) > 1:
        return matches[:5]

    return await snooze(session, matches[0].id, duration_str)


async def set_group_timezone(
    session: AsyncSession, group_id: uuid.UUID, timezone_str: str
) -> str:
    """Validate and set the group timezone. Returns timezone name or raises ReminderError."""
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(timezone_str)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        raise ReminderError(f"Unknown timezone: {timezone_str}")

    from sqlalchemy import select
    result = await session.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise ReminderError("Group not found")

    group.timezone = timezone_str
    await session.commit()
    return timezone_str
