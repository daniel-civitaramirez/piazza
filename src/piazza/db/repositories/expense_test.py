"""Tests for expense repository."""

from __future__ import annotations

import pytest

from piazza.db.repositories.expense import (
    create_expense,
    create_expense_participants,
    create_settlement,
    delete_last_expense,
    get_expense_shares,
    get_expenses,
    get_settlements,
)


class TestCreateExpense:
    @pytest.mark.asyncio
    async def test_creates_record(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
        )
        assert expense.amount_cents == 3000
        assert expense.currency == "EUR"
        assert expense.description == "dinner"
        assert expense.is_deleted is False


class TestCreateExpenseParticipants:
    @pytest.mark.asyncio
    async def test_creates_shares(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            2000, "EUR", "taxi",
        )
        await create_expense_participants(
            db_session, expense.id,
            [(sample_group.alice.id, 1000), (sample_group.bob.id, 1000)],
        )
        shares = await get_expense_shares(db_session, sample_group.group_id)
        assert len(shares) == 2


class TestGetExpenses:
    @pytest.mark.asyncio
    async def test_excludes_deleted(self, db_session, sample_group):
        e1 = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            1000, "EUR", "first",
        )
        await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            2000, "EUR", "second",
        )
        e1.is_deleted = True
        await db_session.flush()

        expenses = await get_expenses(db_session, sample_group.group_id)
        assert len(expenses) == 1
        assert expenses[0].description == "second"

    @pytest.mark.asyncio
    async def test_ordered_most_recent_first(self, db_session, sample_group):
        e1 = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            1000, "EUR", "first",
        )
        e2 = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            2000, "EUR", "second",
        )
        # Ensure distinct timestamps for deterministic ordering
        from datetime import datetime, timezone

        e1.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        e2.created_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        await db_session.flush()

        expenses = await get_expenses(db_session, sample_group.group_id)
        assert expenses[0].description == "second"


class TestDeleteLastExpense:
    @pytest.mark.asyncio
    async def test_soft_deletes(self, db_session, sample_group):
        await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            1000, "EUR", "lunch",
        )
        deleted = await delete_last_expense(db_session, sample_group.group_id)
        assert deleted is not None
        assert deleted.is_deleted is True

    @pytest.mark.asyncio
    async def test_empty_returns_none(self, db_session, sample_group):
        result = await delete_last_expense(db_session, sample_group.group_id)
        assert result is None


class TestGetExpenseShares:
    @pytest.mark.asyncio
    async def test_returns_tuples(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            2000, "EUR", "taxi",
        )
        await create_expense_participants(
            db_session, expense.id,
            [(sample_group.alice.id, 1000), (sample_group.bob.id, 1000)],
        )
        shares = await get_expense_shares(db_session, sample_group.group_id)
        assert len(shares) == 2
        payer_ids = {s[0] for s in shares}
        assert sample_group.alice.id in payer_ids


class TestSettlements:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session, sample_group):
        await create_settlement(
            db_session, sample_group.group_id,
            sample_group.bob.id, sample_group.alice.id, 500,
        )
        settlements = await get_settlements(db_session, sample_group.group_id)
        assert len(settlements) == 1
        assert settlements[0].amount_cents == 500
