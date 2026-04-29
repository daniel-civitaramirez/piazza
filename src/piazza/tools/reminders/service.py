"""Reminder business logic."""

from __future__ import annotations

import uuid
import zoneinfo
from datetime import datetime, timezone

import dateparser
import structlog
from dateutil.rrule import rrulestr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.encryption import set_decrypted
from piazza.core.exceptions import NotFoundError, PastTimeError, ReminderError
from piazza.db.models.group import Group
from piazza.db.models.reminder import Reminder
from piazza.db.repositories import reminder as reminder_repo

logger = structlog.get_logger()


# ---------- Private helpers ----------


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
        if trigger_at <= datetime.now(timezone.utc):
            raise PastTimeError(
                f"_{datetime_raw}_ is already in the past."
            )
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
    if not await reminder_repo.cancel_active_reminder(session, reminder.id):
        raise NotFoundError("reminder", query=query)
    reminder.status = "cancelled"
    await session.commit()
    return reminder


async def update_reminder(
    session: AsyncSession,
    group_id: uuid.UUID,
    *,
    item_number: int | None = None,
    query: str | None = None,
    datetime_raw: str | None = None,
    new_description: str | None = None,
    tz: str = "UTC",
) -> Reminder | list[Reminder]:
    """Update an active reminder's time and/or text.

    Identification: `item_number` (1-indexed) or `query` (fuzzy match).
    Returns the updated Reminder, or list[Reminder] for ambiguous queries.
    Raises NotFoundError, PastTimeError, or ReminderError("nothing_to_update").
    """
    if not datetime_raw and not new_description:
        raise ReminderError("nothing_to_update")

    if item_number is not None:
        reminders = await reminder_repo.get_active_reminders(session, group_id)
        if item_number < 1 or item_number > len(reminders):
            raise NotFoundError("reminder", number=item_number, total=len(reminders))
        reminder = reminders[item_number - 1]
    elif query is not None:
        matches = await reminder_repo.find_active_reminders_by_message(
            session, group_id, query
        )
        if not matches:
            raise NotFoundError("reminder", query=query)
        if len(matches) > 1:
            return matches[:5]
        reminder = matches[0]
    else:
        raise ReminderError("missing_identifier")

    new_trigger: datetime | None = None
    if datetime_raw:
        new_trigger = parse_time(datetime_raw, tz)
        if new_trigger <= datetime.now(timezone.utc):
            raise PastTimeError(f"_{datetime_raw}_ is already in the past.")

    if not await reminder_repo.update_active_reminder(
        session, reminder.id,
        new_trigger_at=new_trigger,
        new_message=new_description,
    ):
        # Lost the race — cron fired or another caller cancelled it.
        raise NotFoundError("reminder")

    if new_trigger is not None:
        reminder.trigger_at = new_trigger
    if new_description is not None:
        set_decrypted(reminder, "message", new_description)

    await session.commit()
    return reminder


async def set_group_timezone(
    session: AsyncSession, group_id: uuid.UUID, timezone_str: str
) -> str:
    """Validate and set the group timezone. Returns timezone name or raises ReminderError."""
    try:
        zoneinfo.ZoneInfo(timezone_str)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        raise ReminderError(f"Unknown timezone: {timezone_str}")

    result = await session.execute(
        select(Group).where(Group.id == group_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise ReminderError("Group not found")

    group.timezone = timezone_str
    await session.commit()
    return timezone_str
