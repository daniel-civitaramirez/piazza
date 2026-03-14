"""Status reporting handler."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.repositories.stats import get_group_stats
from piazza.tools.schemas import Entities


async def handle_status(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    entities: Entities,
) -> str:
    stats = await get_group_stats(session, group_id)
    return (
        f"*Group Status*\n\n"
        f"{stats.expense_count} expenses logged ({stats.total_amount_display} total)\n"
        f"{stats.unsettled_balance_count} unsettled balances\n"
        f"{stats.active_reminder_count} active reminders\n"
        f"{stats.itinerary_item_count} itinerary items\n"
        f"{stats.note_count} saved notes"
    )
