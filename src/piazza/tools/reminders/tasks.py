"""Reminder arq cron tasks."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.repositories import reminder as reminder_repo
from piazza.tools.reminders.service import next_occurrence, occurrences_between

logger = structlog.get_logger()


async def fire_reminders(
    session: AsyncSession,
) -> list[tuple[str, str]]:
    """Check for due reminders and fire them.

    Returns list of (group_wa_jid, message_text) payloads to send.
    Does not send messages directly — caller dispatches.

    Recurring reminders (with a recurrence rule) backfill any occurrences
    that passed while the worker was down (one payload per missed
    occurrence), then are rescheduled to the next future occurrence. One-time
    reminders are marked fired.
    """
    now = datetime.now(timezone.utc)
    due = await reminder_repo.get_due_reminders(session, now)

    payloads: list[tuple[str, str]] = []

    for reminder in due:
        group = reminder.group
        group_jid = group.wa_jid if group else ""
        tz = group.timezone if group and group.timezone else "UTC"
        text = f"⏰ {reminder.message}"

        if reminder.recurrence:
            scheduled = reminder.trigger_at
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            # The originally-scheduled fire, plus any extra occurrences that
            # passed while the worker was down.
            fire_count = 1 + len(
                occurrences_between(reminder.recurrence, scheduled, now, tz)
            )
            for _ in range(fire_count):
                payloads.append((group_jid, text))

            next_at = next_occurrence(reminder.recurrence, now, tz)
            if next_at is not None:
                await reminder_repo.update_reminder_status(
                    session, reminder.id, "active", next_trigger_at=next_at
                )
            else:
                await reminder_repo.update_reminder_status(session, reminder.id, "fired")
        else:
            payloads.append((group_jid, text))
            await reminder_repo.update_reminder_status(session, reminder.id, "fired")

    if payloads:
        await session.commit()
        logger.info("reminders_fired", count=len(payloads))

    return payloads
