"""Tests for expense intent handlers."""

from __future__ import annotations

import pytest

from piazza.tools.expenses import handler, service
from piazza.tools.schemas import Entities


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
        assert "Logged" in result
        assert "Alice" in result
        assert "coffee" in result

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
        assert "Logged" in result
        assert "Bob" in result  # Bob is the payer

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
        assert "Logged" in result
        assert "Bob" in result
        # Alice (sender) should not be in the split
        assert "Alice" not in result

    @pytest.mark.asyncio
    async def test_third_party_payer_with_everyone(self, db_session, sample_group):
        """Third-party payer + 'everyone' includes all members."""
        entities = Entities(
            amount=90.0, paid_by="Bob", description="groceries",
            participants=["everyone"],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Logged" in result
        assert "Bob" in result

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
        assert "Could not find" in result
        assert "Zara" in result

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
        assert "Logged" in result
        assert "Alice" in result

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
        assert "Logged" in result
        # Payer share = 90 - 35 = 55
        assert "55.00" in result
        assert "25.00" in result
        assert "10.00" in result

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
        assert "more than the total" in result

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
        assert "Logged" in result
        assert "20.00" in result


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
        assert "Payment recorded" in result
        assert "Bob" in result
        assert "Alice" in result

    @pytest.mark.asyncio
    async def test_settle_without_amount_shows_suggestions(self, db_session, sample_group):
        """Bare 'settle up' (no amount) still shows suggestions."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            _shares_for_even(
                [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
                3000,
            ),
        )

        entities = Entities()
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert "pays" in result or "settled" in result.lower()

    @pytest.mark.asyncio
    async def test_settle_missing_participant_returns_error(self, db_session, sample_group):
        """Amount present but no payee name returns an error."""
        entities = Entities(amount=40.0)
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert "specify who was paid" in result.lower()

    @pytest.mark.asyncio
    async def test_settle_unknown_participant_returns_error(self, db_session, sample_group):
        """Unresolvable payee name returns an error."""
        entities = Entities(amount=40.0, participants=["Zara"])
        result = await handler.handle_expense_settle(
            db_session, sample_group.group_id, sample_group.bob.id, entities
        )
        assert "Could not find" in result
        assert "Zara" in result

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
        assert "Payment recorded" in result
        assert "$" in result


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
        assert "Updated" in result
        assert "dinner" in result
        assert "40.00" in result

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
        assert "Updated" in result
        assert "fancy dinner" in result

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
        assert "Updated" in result
        assert "Payer" in result
        assert "Bob" in result

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
        assert "Updated" in result
        assert "Split" in result

    @pytest.mark.asyncio
    async def test_update_no_match(self, db_session, sample_group):
        """No matching expense returns error."""
        entities = Entities(description="nonexistent", amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No expense" in result

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
        assert "Multiple" in result

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
        assert "Nothing to update" in result

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
        assert "Updated" in result

    @pytest.mark.asyncio
    async def test_update_by_number_out_of_range(self, db_session, sample_group):
        """Out-of-range item_number returns error."""
        entities = Entities(item_number=99, amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "not found" in result.lower() or "No expenses" in result

    @pytest.mark.asyncio
    async def test_update_no_identifier(self, db_session, sample_group):
        """Neither item_number nor description returns error."""
        entities = Entities(amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify" in result.lower()


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
        assert "Deleted" in result
        assert "dinner" in result

    @pytest.mark.asyncio
    async def test_delete_by_number_out_of_range(self, db_session, sample_group):
        """Out-of-range item_number returns error."""
        entities = Entities(item_number=99)
        result = await handler.handle_expense_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "not found" in result.lower() or "No expenses" in result

    @pytest.mark.asyncio
    async def test_delete_no_identifier(self, db_session, sample_group):
        """Neither item_number nor description returns error."""
        entities = Entities()
        result = await handler.handle_expense_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify" in result.lower()
