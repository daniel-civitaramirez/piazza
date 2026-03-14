"""Capabilities database queries (group stats)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.models.expense import Expense, ExpenseParticipant
from piazza.db.models.itinerary import ItineraryItem
from piazza.db.models.note import Note
from piazza.db.models.reminder import Reminder


@dataclass
class GroupStats:
    expense_count: int = 0
    total_amount_cents: int = 0
    unsettled_balance_count: int = 0
    active_reminder_count: int = 0
    itinerary_item_count: int = 0
    note_count: int = 0

    @property
    def total_amount_display(self) -> str:
        return f"{self.total_amount_cents / 100:.2f}"


async def get_group_stats(session: AsyncSession, group_id: uuid.UUID) -> GroupStats:
    """Return aggregate stats for a group."""
    # Expense count and total
    expense_row = (
        await session.execute(
            select(
                func.count(Expense.id),
                func.coalesce(func.sum(Expense.amount_cents), 0),
            ).where(Expense.group_id == group_id, Expense.is_deleted == False)  # noqa: E712
        )
    ).one()
    expense_count = expense_row[0]
    total_amount_cents = expense_row[1]

    # Unsettled balances: count of distinct members who appear in expense_participants
    # for non-deleted expenses (simplified — counts active participants)
    unsettled_row = (
        await session.execute(
            select(func.count(func.distinct(ExpenseParticipant.member_id))).where(
                ExpenseParticipant.expense_id.in_(
                    select(Expense.id).where(
                        Expense.group_id == group_id, Expense.is_deleted == False  # noqa: E712
                    )
                )
            )
        )
    ).scalar_one()
    unsettled_balance_count = unsettled_row or 0

    # Active reminders
    active_reminders = (
        await session.execute(
            select(func.count(Reminder.id)).where(
                Reminder.group_id == group_id, Reminder.status == "active"
            )
        )
    ).scalar_one()

    # Itinerary items
    itinerary_count = (
        await session.execute(
            select(func.count(ItineraryItem.id)).where(
                ItineraryItem.group_id == group_id
            )
        )
    ).scalar_one()

    # Notes
    note_count = (
        await session.execute(
            select(func.count(Note.id)).where(
                Note.group_id == group_id
            )
        )
    ).scalar_one()

    return GroupStats(
        expense_count=expense_count,
        total_amount_cents=total_amount_cents,
        unsettled_balance_count=unsettled_balance_count,
        active_reminder_count=active_reminders or 0,
        itinerary_item_count=itinerary_count or 0,
        note_count=note_count or 0,
    )
