"""Reminder arq cron tasks."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.repositories import reminder as reminder_repo

logger = structlog.get_logger()


async def fire_reminders(
    session: AsyncSession,
) -> list[tuple[str, str]]:
    """Check for due reminders and fire them.

    Returns list of (group_wa_jid, message_text) payloads to send.
    Does not send messages directly — caller dispatches.
    """
    now = datetime.now(timezone.utc)
    due = await reminder_repo.get_due_reminders(session, now)

    payloads: list[tuple[str, str]] = []

    for reminder in due:
        group = reminder.group
        group_jid = group.wa_jid if group else ""
        text = f"⏰ {reminder.message}"

        payloads.append((group_jid, text))
        await reminder_repo.update_reminder_status(session, reminder.id, "fired")

    if payloads:
        await session.commit()
        logger.info("reminders_fired", count=len(payloads))

    return payloads
