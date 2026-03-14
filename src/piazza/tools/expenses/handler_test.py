"""Tests for expense intent handlers."""

from __future__ import annotations

import pytest

from piazza.tools.expenses import handler, service
from piazza.tools.schemas import Entities


class TestHandleExpenseAdd:
    @pytest.mark.asyncio
    async def test_sender_as_payer(self, db_session, sample_group):
        """Default case: sender pays, paid_by set to sender's name."""
        entities = Entities(
            amount=30.0, paid_by="Alice", description="coffee",
            participants=["Bob"],
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
            amount=50.0, paid_by="Bob", description="dinner",
            participants=["Alice", "Charlie"],
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
            participants=["Charlie"],
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
            participants=["Bob"],
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
            amount=30.0, description="coffee", participants=["Bob"],
        )
        result = await handler.handle_expense_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Logged" in result
        assert "Alice" in result


class TestHandleExpenseSettle:
    @pytest.mark.asyncio
    async def test_settle_with_amount_records_payment(self, db_session, sample_group):
        """Entities with amount + participant records a settlement."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
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
            [sample_group.alice.id, sample_group.bob.id, sample_group.charlie.id],
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
            [sample_group.alice.id, sample_group.bob.id],
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
        """Update expense amount recalculates shares."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            [sample_group.alice.id, sample_group.bob.id],
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
            [sample_group.alice.id, sample_group.bob.id],
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
            [sample_group.alice.id, sample_group.bob.id],
        )

        entities = Entities(description="dinner", paid_by="Bob")
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Updated" in result
        assert "Payer" in result
        assert "Bob" in result

    @pytest.mark.asyncio
    async def test_update_participants(self, db_session, sample_group):
        """Change who's in the split."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            [sample_group.alice.id, sample_group.bob.id],
        )

        # Change split to include Charlie instead of Bob
        entities = Entities(description="dinner", participants=["Charlie"])
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
            [sample_group.alice.id, sample_group.bob.id],
        )
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner at El Bulli",
            [sample_group.alice.id, sample_group.bob.id],
        )

        entities = Entities(description="dinner", amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Multiple" in result

    @pytest.mark.asyncio
    async def test_update_missing_description_returns_error(self, db_session, sample_group):
        """No description returns error."""
        entities = Entities(amount=50.0)
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "describe which expense" in result.lower()

    @pytest.mark.asyncio
    async def test_update_nothing_to_change(self, db_session, sample_group):
        """Description only with no changes returns error."""
        await service.add_expense(
            db_session, sample_group.group_id, sample_group.alice.id,
            3000, "EUR", "dinner",
            [sample_group.alice.id, sample_group.bob.id],
        )

        entities = Entities(description="dinner")
        result = await handler.handle_expense_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Nothing to update" in result
