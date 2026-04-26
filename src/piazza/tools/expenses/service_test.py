"""Tests for expense business logic."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from piazza.core.exceptions import ExpenseError, NotFoundError
from piazza.tools.expenses import service
from piazza.tools.expenses.service import (
    calculate_balances,
    calculate_even_split,
    simplify_debts,
)


def _shares_for_even(ids, amount_cents):
    """Helper: build even shares for seeding expenses via service."""
    splits = calculate_even_split(amount_cents, len(ids))
    return list(zip(ids, splits))

# ---------- Even split math ----------


class TestEvenSplit:
    def test_45_split_3_ways(self):
        assert calculate_even_split(4500, 3) == [1500, 1500, 1500]

    def test_10_split_3_ways(self):
        assert calculate_even_split(1000, 3) == [334, 333, 333]

    def test_1_split_3_ways(self):
        assert calculate_even_split(100, 3) == [34, 33, 33]

    def test_sum_always_equals_total(self):
        for amount in [1, 7, 100, 999, 1000, 4567]:
            for n in [1, 2, 3, 5, 7]:
                shares = calculate_even_split(amount, n)
                assert sum(shares) == amount

    def test_zero_amount_raises(self):
        with pytest.raises(ExpenseError, match="positive"):
            calculate_even_split(0, 3)

    def test_negative_amount_raises(self):
        with pytest.raises(ExpenseError, match="positive"):
            calculate_even_split(-100, 3)

    def test_zero_participants_raises(self):
        with pytest.raises(ExpenseError, match="zero"):
            calculate_even_split(1000, 0)


# ---------- Balance calculation ----------


class TestBalances:
    def _ids(self, n: int) -> list[uuid.UUID]:
        return [uuid.uuid4() for _ in range(n)]

    def test_single_expense(self):
        a, b, c = self._ids(3)
        rows = [(a, a, 1000, "EUR"), (a, b, 1000, "EUR"), (a, c, 1000, "EUR")]
        balances = calculate_balances(rows, [])
        assert balances["EUR"][a] == 2000
        assert balances["EUR"][b] == -1000
        assert balances["EUR"][c] == -1000

    def test_multiple_expenses(self):
        a, b = self._ids(2)
        rows = [(a, a, 1000, "EUR"), (a, b, 1000, "EUR")]
        rows += [(b, a, 500, "EUR"), (b, b, 500, "EUR")]
        balances = calculate_balances(rows, [])
        assert balances["EUR"][a] == 500
        assert balances["EUR"][b] == -500

    def test_after_settlement(self):
        a, b = self._ids(2)
        rows = [(a, a, 500, "EUR"), (a, b, 500, "EUR")]
        settlements = [(b, a, 500, "EUR")]
        balances = calculate_balances(rows, settlements)
        assert balances["EUR"][a] == 0
        assert balances["EUR"][b] == 0

    def test_no_expenses(self):
        balances = calculate_balances([], [])
        assert balances == {}

    def test_currencies_partitioned(self):
        a, b = self._ids(2)
        rows = [
            (a, a, 1000, "EUR"), (a, b, 1000, "EUR"),
            (b, a, 500, "USD"), (b, b, 500, "USD"),
        ]
        balances = calculate_balances(rows, [])
        assert balances["EUR"] == {a: 1000, b: -1000}
        assert balances["USD"] == {a: -500, b: 500}


# ---------- Simplify debts (greedy min-flow) ----------


class TestSimplifyDebts:
    def _ids(self, n: int) -> list[uuid.UUID]:
        return [uuid.uuid4() for _ in range(n)]

    def test_simple_a_owes_b(self):
        a, b = self._ids(2)
        balances = {a: -1000, b: 1000}
        debts = simplify_debts(balances)
        assert len(debts) == 1
        debtor, creditor, amount = debts[0]
        assert debtor == a
        assert creditor == b
        assert amount == 1000

    def test_triangle_net_zero(self):
        a, b, c = self._ids(3)
        balances = {a: 0, b: 0, c: 0}
        debts = simplify_debts(balances)
        assert debts == []

    def test_complex_4_members(self):
        a, b, c, d = self._ids(4)
        balances = {a: -3000, b: -1000, c: 2000, d: 2000}
        debts = simplify_debts(balances)
        assert len(debts) <= 3
        total_transferred = sum(amt for _, _, amt in debts)
        assert total_transferred == 4000

    def test_all_settled(self):
        a, b, c = self._ids(3)
        balances = {a: 0, b: 0, c: 0}
        assert simplify_debts(balances) == []

    def test_empty_balances(self):
        assert simplify_debts({}) == []


# ---------- DB-backed service tests ----------


class TestExpenseServiceDB:
    @pytest.mark.asyncio
    async def test_list_no_expenses(self, db_session, sample_group):
        result = await service.list_expenses(db_session, sample_group.group_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_log_and_list_expense(self, db_session, sample_group):
        await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            3000, "EUR", "taxi",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )
        result = await service.list_expenses(db_session, sample_group.group_id)
        assert len(result) == 1
        assert result[0].description == "taxi"

    @pytest.mark.asyncio
    async def test_add_expense_returns_result(self, db_session, sample_group):
        """add_expense returns an ExpenseResult with payer and shares."""
        result = await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            3000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )
        assert result.payer_name == "Alice"
        assert len(result.shares) == 3

    @pytest.mark.asyncio
    async def test_balance_summary(self, db_session, sample_group):
        await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            3000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )
        result = await service.get_balances(db_session, sample_group.group_id)
        assert "EUR" in result.debts_by_currency
        eur_debts = result.debts_by_currency["EUR"]
        assert len(eur_debts) > 0
        names = {d["debtor"] for d in eur_debts} | {d["creditor"] for d in eur_debts}
        assert "Alice" in names

    @pytest.mark.asyncio
    async def test_consolidated_balance_uses_fx(self, db_session, sample_group):
        """Pass `convert_to` and the per-currency map is summed via FX."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            10000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 10000,
            ),
        )
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.bob.id,
            10000, "USD", "snacks",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 10000,
            ),
        )

        class _FxStub:
            async def convert(self, cents, from_c, to_c):
                # USD->EUR = 0.5, EUR->USD = 2
                if from_c == to_c:
                    return cents, Decimal(1)
                if from_c == "USD" and to_c == "EUR":
                    return cents // 2, Decimal("0.5")
                if from_c == "EUR" and to_c == "USD":
                    return cents * 2, Decimal(2)
                raise AssertionError(f"unexpected pair {from_c}->{to_c}")

        result = await service.get_balances(
            db_session, sample_group.group_id, convert_to="EUR", fx=_FxStub()
        )
        assert result.converted is not None
        assert result.converted["currency"] == "EUR"
        # Bob owes Alice 5000 EUR; Alice owes Bob 5000 USD = 2500 EUR.
        # Net: Bob owes Alice 2500 EUR.
        debts = result.converted["debts"]
        assert len(debts) == 1
        assert debts[0]["debtor"] == "Bob"
        assert debts[0]["creditor"] == "Alice"
        assert debts[0]["amount_cents"] == 2500

    @pytest.mark.asyncio
    async def test_balance_partitions_by_currency(self, db_session, sample_group):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 3000,
            ),
        )
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.bob.id,
            2000, "USD", "snacks",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 2000,
            ),
        )
        result = await service.get_balances(db_session, sample_group.group_id)
        assert set(result.debts_by_currency.keys()) == {"EUR", "USD"}

    @pytest.mark.asyncio
    async def test_resolve_by_number_not_found(self, db_session, sample_group):
        with pytest.raises(NotFoundError):
            await service.resolve_expense_by_number(db_session, sample_group.group_id, 99)

    @pytest.mark.asyncio
    async def test_resolve_by_description_not_found(self, db_session, sample_group):
        with pytest.raises(NotFoundError):
            await service.resolve_expense_by_description(
                db_session, sample_group.group_id, "nonexistent"
            )


class TestUpdateExpenseCurrencyConversion:
    @pytest.mark.asyncio
    async def test_currency_only_change_converts_amount(self, db_session, sample_group):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            10000, "EUR", "hotel",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 10000,
            ),
        )
        expense = (await service.list_expenses(db_session, sample_group.group_id))[0]

        class _FxStub:
            async def convert(self, cents, from_c, to_c):
                # EUR->USD at 1.10
                return int(cents * Decimal("1.10")), Decimal("1.10")

        updated, changes = await service.update_expense(
            db_session, expense, new_currency="USD", fx=_FxStub(),
        )
        assert updated.currency == "USD"
        assert updated.amount_cents == 11000
        assert any(c["field"] == "amount" and c.get("converted_from") == "EUR" for c in changes)

    @pytest.mark.asyncio
    async def test_currency_only_change_without_fx_raises(self, db_session, sample_group):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "taxi",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 5000,
            ),
        )
        expense = (await service.list_expenses(db_session, sample_group.group_id))[0]

        with pytest.raises(ExpenseError, match="FX provider required"):
            await service.update_expense(
                db_session, expense, new_currency="USD", fx=None,
            )


class TestRecordSettlement:
    @pytest.mark.asyncio
    async def test_record_settlement_creates_db_record(self, db_session, sample_group):
        """Settlement is recorded in DB and confirmation returned."""
        await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )

        result = await service.record_settlement(
            db_session,
            sample_group.group_id,
            payer_id=sample_group.bob.id,
            payee_id=sample_group.alice.id,
            amount_cents=500,
            currency="EUR",
        )
        assert result.payer_name == "Bob"
        assert result.payee_name == "Alice"
        assert result.amount_cents == 500

        from piazza.db.repositories.expense import get_settlements
        settlements = await get_settlements(db_session, sample_group.group_id)
        assert len(settlements) == 1
        assert settlements[0].amount_cents == 500

    @pytest.mark.asyncio
    async def test_record_settlement_updates_balance(self, db_session, sample_group):
        """Balance reflects the settlement payment."""
        await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            2000, "EUR", "taxi",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                2000,
            ),
        )

        result = await service.record_settlement(
            db_session,
            sample_group.group_id,
            payer_id=sample_group.bob.id,
            payee_id=sample_group.alice.id,
            amount_cents=500,
            currency="EUR",
        )
        assert result.remaining_cents > 0

    @pytest.mark.asyncio
    async def test_partial_settlement_shows_remaining(self, db_session, sample_group):
        """100 owed, pay 40, shows 60 remaining."""
        await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            10000, "EUR", "hotel",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                10000,
            ),
        )
        result = await service.record_settlement(
            db_session,
            sample_group.group_id,
            payer_id=sample_group.bob.id,
            payee_id=sample_group.alice.id,
            amount_cents=4000,
            currency="EUR",
        )
        assert result.remaining_cents == 1000

    @pytest.mark.asyncio
    async def test_full_settlement_shows_settled(self, db_session, sample_group):
        """Exact amount settles the debt completely."""
        await service.add_expense(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            2000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                2000,
            ),
        )
        result = await service.record_settlement(
            db_session,
            sample_group.group_id,
            payer_id=sample_group.bob.id,
            payee_id=sample_group.alice.id,
            amount_cents=1000,
            currency="EUR",
        )
        assert result.settled_up is True

