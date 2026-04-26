"""Tests for expense repository."""

from __future__ import annotations

import pytest

from piazza.db.repositories.expense import (
    create_expense,
    create_expense_participants,
    create_settlement,
    find_expenses_by_description,
    get_expense_shares,
    get_expenses,
    get_settlements,
    update_description,
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


class TestFindExpensesByDescription:
    @pytest.mark.asyncio
    async def test_exact_substring(self, db_session, sample_group):
        await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "dentist appointment",
        )
        results = await find_expenses_by_description(
            db_session, sample_group.group_id, "dentist"
        )
        assert len(results) == 1
        assert results[0].description == "dentist appointment"

    @pytest.mark.asyncio
    async def test_fuzzy_typo(self, db_session, sample_group):
        await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "dentist appointment",
        )
        results = await find_expenses_by_description(
            db_session, sample_group.group_id, "dentst"
        )
        assert len(results) == 1
        assert results[0].description == "dentist appointment"

    @pytest.mark.asyncio
    async def test_no_match_below_threshold(self, db_session, sample_group):
        await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "dentist appointment",
        )
        results = await find_expenses_by_description(
            db_session, sample_group.group_id, "qwertyz"
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_excludes_deleted(self, db_session, sample_group):
        e = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "dentist",
        )
        e.is_deleted = True
        await db_session.flush()
        results = await find_expenses_by_description(
            db_session, sample_group.group_id, "dentist"
        )
        assert results == []


class TestUpdateDescription:
    @pytest.mark.asyncio
    async def test_round_trip(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
        )
        await update_description(db_session, expense, "fancy dinner")
        # In-memory plaintext is updated
        assert expense.description == "fancy dinner"

        # Fresh fetch decrypts to the new value (verifies the ciphertext is correct)
        db_session.expunge(expense)
        refetched = (await get_expenses(db_session, sample_group.group_id))[0]
        assert refetched.description == "fancy dinner"

    @pytest.mark.asyncio
    async def test_set_to_none(self, db_session, sample_group):
        expense = await create_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
        )
        await update_description(db_session, expense, None)
        assert expense.description is None
        db_session.expunge(expense)
        refetched = (await get_expenses(db_session, sample_group.group_id))[0]
        assert refetched.description is None


class TestSettlements:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session, sample_group):
        await create_settlement(
            db_session, sample_group.group_id,
            sample_group.bob.id, sample_group.alice.id, 500, "EUR",
        )
        settlements = await get_settlements(db_session, sample_group.group_id)
        assert len(settlements) == 1
        assert settlements[0].amount_cents == 500
        assert settlements[0].currency == "EUR"

    @pytest.mark.asyncio
    async def test_currency_persisted(self, db_session, sample_group):
        await create_settlement(
            db_session, sample_group.group_id,
            sample_group.bob.id, sample_group.alice.id, 2200, "USD",
        )
        settlements = await get_settlements(db_session, sample_group.group_id)
        assert settlements[0].currency == "USD"
