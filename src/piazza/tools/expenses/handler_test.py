"""Tests for expense intent handlers."""

from __future__ import annotations

from decimal import Decimal

import pytest

from piazza.core.fx import set_fx_provider
from piazza.tools.expenses import handler, service
from piazza.tools.schemas import Entities


class _FxStub:
    """A 1 USD = 0.5 EUR (USD->EUR halves, EUR->USD doubles) FX stub."""

    async def convert(self, cents, from_c, to_c):
        if from_c == to_c:
            return cents, Decimal(1)
        if from_c == "USD" and to_c == "EUR":
            return cents // 2, Decimal("0.5")
        if from_c == "EUR" and to_c == "USD":
            return cents * 2, Decimal(2)
        raise AssertionError(f"unexpected pair {from_c}->{to_c}")


@pytest.fixture
def fx_stub():
    set_fx_provider(_FxStub())  # type: ignore[arg-type]
    yield
    set_fx_provider(None)


def _shares_for_even(ids, amount_cents):
    """Helper: build even shares for seeding expenses via service."""
    from piazza.tools.expenses.service import calculate_even_split

    splits = calculate_even_split(amount_cents, len(ids))
    return list(zip(ids, splits))


class TestHandleExpenseAdd:
    @pytest.mark.asyncio
    async def test_sender_as_payer(self, db_session, sample_group):
        """Default case: sender pays, paid_by set to sender's name."""
        entities = Entities(
            amount=30.0, paid_by="Alice", description="coffee",
            participants=[{"name": "Bob", "amount": 15.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "add_expense"
        assert result["payer"] == "Alice"
        assert result["description"] == "coffee"

    @pytest.mark.asyncio
    async def test_third_party_payer(self, db_session, sample_group):
        """Someone other than the sender paid."""
        entities = Entities(
            amount=60.0, paid_by="Bob", description="dinner",
            participants=[{"name": "Alice", "amount": 20.0}, {"name": "Charlie", "amount": 20.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["payer"] == "Bob"

    @pytest.mark.asyncio
    async def test_third_party_payer_sender_excluded(self, db_session, sample_group):
        """Sender is excluded from split when not in participants."""
        entities = Entities(
            amount=100.0, paid_by="Bob", description="supplies",
            participants=[{"name": "Charlie", "amount": 50.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["payer"] == "Bob"
        share_names = [s["name"] for s in result["shares"]]
        assert "Alice" not in share_names

    @pytest.mark.asyncio
    async def test_unknown_payer_returns_error(self, db_session, sample_group):
        """Unknown payer name returns error with member list."""
        entities = Entities(
            amount=50.0, paid_by="Zara", description="dinner",
            participants=[{"name": "Bob", "amount": 25.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "payer_not_found"
        assert result["name"] == "Zara"

    @pytest.mark.asyncio
    async def test_paid_by_fallback_to_sender(self, db_session, sample_group):
        """When paid_by is not set, falls back to sender."""
        entities = Entities(
            amount=30.0, description="coffee",
            participants=[{"name": "Bob", "amount": 15.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["payer"] == "Alice"

    @pytest.mark.asyncio
    async def test_custom_split(self, db_session, sample_group):
        """Custom amounts per participant."""
        entities = Entities(
            amount=90.0, paid_by="Alice", description="dinner",
            participants=[
                {"name": "Bob", "amount": 25.0},
                {"name": "Charlie", "amount": 10.0},
            ],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        shares_by_name = {s["name"]: s["amount_cents"] for s in result["shares"]}
        assert shares_by_name["Alice"] == 5500  # payer share = 9000 - 3500
        assert shares_by_name["Bob"] == 2500
        assert shares_by_name["Charlie"] == 1000

    @pytest.mark.asyncio
    async def test_participant_amounts_exceed_total(self, db_session, sample_group):
        """Participant amounts exceeding total returns error."""
        entities = Entities(
            amount=50.0, paid_by="Alice", description="dinner",
            participants=[
                {"name": "Bob", "amount": 30.0},
                {"name": "Charlie", "amount": 30.0},
            ],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "participants_exceed_total"

    @pytest.mark.asyncio
    async def test_decimal_safe_rounding(self, db_session, sample_group):
        """Custom split with values that drift under IEEE-754 still sums correctly."""
        # 0.1 + 0.2 in float = 0.30000000000000004; total 0.30 must work cleanly
        entities = Entities(
            amount=0.30, paid_by="Alice", description="rounding probe",
            participants=[
                {"name": "Bob", "amount": 0.10},
                {"name": "Charlie", "amount": 0.20},
            ],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        shares_by_name = {s["name"]: s["amount_cents"] for s in result["shares"]}
        assert shares_by_name == {"Alice": 0, "Bob": 10, "Charlie": 20}

    @pytest.mark.asyncio
    async def test_payer_in_participants_is_folded(self, db_session, sample_group):
        """An explicit payer entry is folded into the residual, not double-counted."""
        entities = Entities(
            amount=100.0, paid_by="Alice", description="hotel",
            participants=[
                {"name": "Alice", "amount": 40.0},
                {"name": "Bob", "amount": 60.0},
            ],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        shares_by_name = {s["name"]: s["amount_cents"] for s in result["shares"]}
        # Alice's explicit 40 was dropped; her share is the residual = 100 - 60 = 40
        assert shares_by_name == {"Alice": 4000, "Bob": 6000}

    @pytest.mark.asyncio
    async def test_currency_normalized_on_add(self, db_session, sample_group):
        entities = Entities(
            amount=20.0, currency="usd", paid_by="Alice", description="coffee",
            participants=[{"name": "Bob", "amount": 10.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_invalid_currency_on_add(self, db_session, sample_group):
        entities = Entities(
            amount=20.0, currency="dollars", paid_by="Alice", description="coffee",
            participants=[{"name": "Bob", "amount": 10.0}],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "invalid_currency"

    @pytest.mark.asyncio
    async def test_solo_expense(self, db_session, sample_group):
        """Empty participants — payer bears full cost."""
        entities = Entities(
            amount=20.0, paid_by="Alice", description="coffee",
            participants=[],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["amount_cents"] == 2000


class TestHandleExpenseSettle:
    @pytest.mark.asyncio
    async def test_settle_with_amount_records_payment(self, db_session, sample_group):
        """Entities with amount + participant records a settlement."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )

        entities = Entities(amount=10.0, participants=["Alice"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "settle_expense"
        assert result["payer"] == "Bob"
        assert result["payee"] == "Alice"

    @pytest.mark.asyncio
    async def test_settle_missing_amount_returns_error(self, db_session, sample_group):
        """No amount returns an error."""
        entities = Entities(participants=["Alice"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_amount"

    @pytest.mark.asyncio
    async def test_settle_negative_amount_returns_error(self, db_session, sample_group):
        """Negative amount returns an error."""
        entities = Entities(amount=-10.0, participants=["Alice"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "negative_amount"

    @pytest.mark.asyncio
    async def test_settle_missing_participant_returns_error(self, db_session, sample_group):
        """Amount present but no payee name returns an error."""
        entities = Entities(amount=40.0)
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_settlement_payee"

    @pytest.mark.asyncio
    async def test_settle_unknown_participant_returns_error(self, db_session, sample_group):
        """Unresolvable payee name returns an error."""
        entities = Entities(amount=40.0, participants=["Zara"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "payee_not_found"
        assert result["name"] == "Zara"

    @pytest.mark.asyncio
    async def test_settle_with_dict_participant(self, db_session, sample_group):
        """LLM occasionally passes the dict shape; must still resolve the payee."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )

        entities = Entities(amount=10.0, participants=[{"name": "Alice"}])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "ok"
        assert result["payee"] == "Alice"

    @pytest.mark.asyncio
    async def test_settle_dict_participant_without_name(self, db_session, sample_group):
        """A dict participant with no name field is rejected cleanly."""
        entities = Entities(amount=10.0, participants=[{"amount": 10.0}])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_settlement_payee"

    @pytest.mark.asyncio
    async def test_settle_normalizes_currency_case(self, db_session, sample_group):
        """Lowercase / mixed-case currency input is normalized to uppercase."""
        entities = Entities(amount=10.0, currency="usd", participants=["Alice"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "ok"
        assert result["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_settle_invalid_currency_returns_error(self, db_session, sample_group):
        entities = Entities(amount=10.0, currency="dollars", participants=["Alice"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "invalid_currency"

    @pytest.mark.asyncio
    async def test_settle_with_currency(self, db_session, sample_group):
        """Settlement respects the currency entity."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "USD", "hotel",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                5000,
            ),
        )

        entities = Entities(amount=25.0, currency="USD", participants=["Alice"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert result["status"] == "ok"
        assert result["currency"] == "USD"


class TestHandleExpenseUpdate:
    @pytest.mark.asyncio
    async def test_update_amount(self, db_session, sample_group):
        """Update expense amount without participants — shares unchanged."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(description="dinner", amount=40.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "update_expense"
        assert any(c["field"] == "amount" and c["new_cents"] == 4000 for c in result["changes"])

    @pytest.mark.asyncio
    async def test_update_description(self, db_session, sample_group):
        """Rename an expense."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(description="dinner", new_description="fancy dinner")
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        desc_changes = [c for c in result["changes"] if c["field"] == "description"]
        assert desc_changes and desc_changes[0]["new"] == "fancy dinner"

    @pytest.mark.asyncio
    async def test_update_payer(self, db_session, sample_group):
        """Change who paid for an expense."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(description="dinner", paid_by="Bob")
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert any(c["field"] == "payer" and c["new"] == "Bob" for c in result["changes"])

    @pytest.mark.asyncio
    async def test_update_participants_custom_split(self, db_session, sample_group):
        """Change split with custom amounts."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(
            description="dinner",
            participants=[{"name": "Bob", "amount": 20.0}, {"name": "Charlie", "amount": 10.0}],
        )
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert any(c["field"] == "shares" for c in result["changes"])

    @pytest.mark.asyncio
    async def test_update_no_match(self, db_session, sample_group):
        """No matching expense returns error."""
        entities = Entities(description="nonexistent", amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_update_ambiguous(self, db_session, sample_group):
        """Multiple matching expenses returns disambiguation."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            2000, "EUR", "dinner at La Piazza",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                2000,
            ),
        )
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner at El Bulli",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(description="dinner", amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ambiguous"
        assert len(result["matches"]) == 2

    @pytest.mark.asyncio
    async def test_update_nothing_to_change(self, db_session, sample_group):
        """Description only with no changes returns error."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(description="dinner")
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "nothing_to_update"

    @pytest.mark.asyncio
    async def test_update_by_number(self, db_session, sample_group):
        """Update expense identified by item_number."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(item_number=1, amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "update_expense"

    @pytest.mark.asyncio
    async def test_update_by_number_out_of_range(self, db_session, sample_group):
        """Out-of-range item_number returns error."""
        entities = Entities(item_number=99, amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_update_currency_normalized(self, db_session, sample_group):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )
        entities = Entities(description="dinner", currency="usd", amount=30.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_update_invalid_currency(self, db_session, sample_group):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )
        entities = Entities(description="dinner", currency="dollars")
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "invalid_currency"

    @pytest.mark.asyncio
    async def test_update_no_identifier(self, db_session, sample_group):
        """Neither item_number nor description returns error."""
        entities = Entities(amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"


class TestHandleExpenseDeleteByNumber:
    @pytest.mark.asyncio
    async def test_delete_by_number(self, db_session, sample_group):
        """Delete expense identified by item_number."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id],
                3000,
            ),
        )

        entities = Entities(item_number=1)
        result = await handler.handle_expense_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "delete_expense"
        assert result["description"] == "dinner"

    @pytest.mark.asyncio
    async def test_delete_by_number_out_of_range(self, db_session, sample_group):
        """Out-of-range item_number returns error."""
        entities = Entities(item_number=99)
        result = await handler.handle_expense_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_delete_no_identifier(self, db_session, sample_group):
        """Neither item_number nor description returns error."""
        entities = Entities()
        result = await handler.handle_expense_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"


class TestHandleExpenseBalanceFx:
    @pytest.mark.asyncio
    async def test_default_view_returns_per_currency(self, db_session, sample_group):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 3000,
            ),
        )
        result = await handler.handle_expense_balance(
            db_session, sample_group.group_id, sample_group.alice.id, Entities()
        )
        assert result["status"] == "ok"
        assert "EUR" in result["debts_by_currency"]
        assert result.get("converted") is None

    @pytest.mark.asyncio
    async def test_converted_view_with_fx(self, db_session, sample_group, fx_stub):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            10000, "EUR", "hotel",
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
        entities = Entities(currency="eur")
        result = await handler.handle_expense_balance(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["converted"]["currency"] == "EUR"
        debts = result["converted"]["debts"]
        assert debts == [{"debtor": "Bob", "creditor": "Alice", "amount_cents": 2500}]

    @pytest.mark.asyncio
    async def test_converted_view_without_fx_falls_back(self, db_session, sample_group):
        # No fx_stub fixture: get_fx_provider() raises, handler degrades gracefully.
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "lunch",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 3000,
            ),
        )
        set_fx_provider(None)
        result = await handler.handle_expense_balance(
            db_session, sample_group.group_id, sample_group.alice.id,
            Entities(currency="USD"),
        )
        assert result["status"] == "ok"
        assert result["fx_unavailable"] is True
        assert result["requested_currency"] == "USD"
        assert "EUR" in result["debts_by_currency"]

    @pytest.mark.asyncio
    async def test_invalid_currency_returns_error(self, db_session, sample_group):
        result = await handler.handle_expense_balance(
            db_session, sample_group.group_id, sample_group.alice.id,
            Entities(currency="dollars"),
        )
        assert result["status"] == "error"
        assert result["reason"] == "invalid_currency"


class TestHandleExpenseUpdateCurrencyConversion:
    @pytest.mark.asyncio
    async def test_currency_only_update_converts(self, db_session, sample_group, fx_stub):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            10000, "EUR", "hotel",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 10000,
            ),
        )
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id,
            Entities(description="hotel", currency="USD"),
        )
        assert result["status"] == "ok"
        assert result["currency"] == "USD"
        assert result["amount_cents"] == 20000  # EUR->USD doubled by stub
        assert any(c["field"] == "amount" and c.get("converted_from") == "EUR"
                   for c in result["changes"])

    @pytest.mark.asyncio
    async def test_currency_only_update_without_fx_returns_error(
        self, db_session, sample_group
    ):
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "taxi",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 5000,
            ),
        )
        set_fx_provider(None)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id,
            Entities(description="taxi", currency="USD"),
        )
        assert result["status"] == "error"
        assert result["reason"] == "fx_unavailable"

    @pytest.mark.asyncio
    async def test_currency_and_amount_skips_fx(self, db_session, sample_group):
        # No FX wired — but caller supplies the new amount, so no conversion.
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            5000, "EUR", "taxi",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id], 5000,
            ),
        )
        set_fx_provider(None)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id,
            Entities(description="taxi", currency="USD", amount=60.0),
        )
        assert result["status"] == "ok"
        assert result["currency"] == "USD"
        assert result["amount_cents"] == 6000
