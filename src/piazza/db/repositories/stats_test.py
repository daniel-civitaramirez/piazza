"""Tests for stats repository."""

from __future__ import annotations

import pytest

from piazza.db.repositories.expense import create_expense, create_expense_participants
from piazza.db.repositories.stats import GroupStats, get_group_stats


class TestGroupStatsProperty:
    def test_zero(self):
        assert GroupStats(total_amount_cents=0).total_amount_display == "0.00"

    def test_round_dollars(self):
        assert GroupStats(total_amount_cents=5000).total_amount_display == "50.00"

    def test_with_cents(self):
        assert GroupStats(total_amount_cents=1234).total_amount_display == "12.34"

    def test_single_cent(self):
        assert GroupStats(total_amount_cents=1).total_amount_display == "0.01"


class TestGetGroupStats:
    @pytest.mark.asyncio
    async def test_empty_group(self, db_session, sample_group):
        stats = await get_group_stats(db_session, sample_group.group_id)
        assert stats.expense_count == 0
        assert stats.total_amount_cents == 0
        assert stats.active_reminder_count == 0
        assert stats.itinerary_item_count == 0
        assert stats.note_count == 0

    @pytest.mark.asyncio
    async def test_with_expenses(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
        )
        await create_expense_participants(
            db_session, expense.id,
            [(sample_group.alice.id, 1500), (sample_group.bob.id, 1500)],
        )
        stats = await get_group_stats(db_session, sample_group.group_id)
        assert stats.expense_count == 1
        assert stats.total_amount_cents == 3000

    @pytest.mark.asyncio
    async def test_deleted_expenses_excluded(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "deleted item",
        )
        expense.is_deleted = True
        await db_session.flush()

        stats = await get_group_stats(db_session, sample_group.group_id)
        assert stats.expense_count == 0
        assert stats.total_amount_cents == 0
