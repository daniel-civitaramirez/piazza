"""Status reporting handler."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.repositories.stats import get_group_stats
from piazza.tools.responses import Action, ok_response
from piazza.tools.schemas import Entities


async def handle_status(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    entities: Entities,
) -> dict:
    stats = await get_group_stats(session, group_id)
    return ok_response(
        Action.GET_STATUS,
        stats={
            "expense_count": stats.expense_count,
            "total_amount_cents": stats.total_amount_cents,
            "unsettled_balance_count": stats.unsettled_balance_count,
            "active_reminder_count": stats.active_reminder_count,
            "itinerary_item_count": stats.itinerary_item_count,
            "note_count": stats.note_count,
        },
    )
