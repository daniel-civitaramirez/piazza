"""Reminder intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError, ReminderError
from piazza.db.models.reminder import Reminder
from piazza.db.repositories.group import get_group
from piazza.tools.reminders import service
from piazza.tools.responses import (
    Action,
    Entity,
    Reason,
    ambiguous_response,
    empty_response,
    error_response,
    list_response,
    not_found_response,
    ok_response,
)
from piazza.tools.schemas import Entities

# ---------- Private helpers ----------


async def _get_group_tz(session: AsyncSession, group_id: uuid.UUID) -> str:
    group = await get_group(session, group_id)
    return group.timezone if group else "UTC"


def _reminder_to_dict(reminder: Reminder, number: int | None = None) -> dict:
    """Convert a Reminder model to a structured dict."""
    d: dict = {
        "message": reminder.message,
        "trigger_at": reminder.trigger_at.isoformat(),
    }
    if number is not None:
        d["number"] = number
    return d


def _not_found_from_exc(exc: NotFoundError) -> dict:
    return not_found_response(
        exc.entity,
        number=exc.number,
        total=exc.total,
        query=exc.query,
    )


def _ambiguous_response(matches: list[Reminder]) -> dict:
    return ambiguous_response(
        Entity.REMINDER,
        [_reminder_to_dict(r, i) for i, r in enumerate(matches, 1)],
    )


# ---------- Public handlers ----------


async def handle_reminder_set(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Set a new reminder."""
    if not entities.description:
        return error_response(Reason.MISSING_DESCRIPTION, entity=Entity.REMINDER)
    if not entities.datetime_raw:
        return error_response(Reason.MISSING_TIME)

    tz = await _get_group_tz(session, group_id)
    try:
        reminder = await service.set_reminder(
            session, group_id, sender_id,
            entities.description, entities.datetime_raw, tz,
        )
    except ReminderError:
        return error_response(Reason.UNPARSEABLE_TIME, raw=entities.datetime_raw)

    return ok_response(
        Action.SET_REMINDER,
        message=reminder.message,
        trigger_at=reminder.trigger_at.isoformat(),
    )


async def handle_reminder_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """List active reminders."""
    reminders = await service.list_reminders(session, group_id)
    if not reminders:
        return empty_response(Entity.REMINDERS)

    return list_response(
        Entity.REMINDERS,
        [_reminder_to_dict(r, i) for i, r in enumerate(reminders, 1)],
    )


async def handle_reminder_cancel(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Cancel a reminder by number or by matching message text."""
    try:
        if entities.item_number is not None:
            reminder = await service.cancel_by_number(
                session, group_id, entities.item_number
            )
            return ok_response(
                Action.CANCEL_REMINDER,
                message=reminder.message,
                trigger_at=reminder.trigger_at.isoformat(),
            )

        if entities.description:
            result = await service.cancel_by_message(
                session, group_id, entities.description
            )
            if isinstance(result, list):
                return _ambiguous_response(result)
            return ok_response(
                Action.CANCEL_REMINDER,
                message=result.message,
                trigger_at=result.trigger_at.isoformat(),
            )
    except NotFoundError as exc:
        return _not_found_from_exc(exc)

    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.REMINDER)


async def handle_reminder_snooze(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Snooze a reminder by number or message text, with a duration."""
    duration = entities.datetime_raw
    if not duration:
        return error_response(Reason.MISSING_DURATION)

    try:
        if entities.item_number is not None:
            reminder = await service.snooze_by_number(
                session, group_id, entities.item_number, duration
            )
            return ok_response(
                Action.SNOOZE_REMINDER,
                message=reminder.message,
                trigger_at=reminder.trigger_at.isoformat(),
            )

        if entities.description:
            result = await service.snooze_by_message(
                session, group_id, entities.description, duration
            )
            if isinstance(result, list):
                return _ambiguous_response(result)
            return ok_response(
                Action.SNOOZE_REMINDER,
                message=result.message,
                trigger_at=result.trigger_at.isoformat(),
            )
    except NotFoundError as exc:
        return _not_found_from_exc(exc)
    except ReminderError:
        return error_response(Reason.UNPARSEABLE_DURATION, raw=duration)

    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.REMINDER)


async def handle_set_timezone(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Set the group timezone."""
    tz_str = entities.description or ""
    try:
        timezone_name = await service.set_group_timezone(session, group_id, tz_str)
    except ReminderError:
        return error_response(Reason.INVALID_TIMEZONE, raw=tz_str)

    return ok_response(Action.SET_TIMEZONE, timezone=timezone_name)
