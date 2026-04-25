"""Tests for cross-domain search handler."""

from __future__ import annotations

import pytest

from piazza.db.repositories import checklist as checklist_repo
from piazza.db.repositories import expense as expense_repo
from piazza.db.repositories import note as note_repo
from piazza.tools.schemas import Entities
from piazza.tools.search.handler import handle_search_group


class TestSearchMode:
    @pytest.mark.asyncio
    async def test_returns_grouped_results(self, db_session, sample_group):
        gid = sample_group.group_id
        alice = sample_group.alice

        await expense_repo.create_expense(
            db_session, gid, alice.id, 5000, "EUR", "dinner"
        )
        await note_repo.create_note(db_session, gid, alice.id, content="dinner spot info")
        await db_session.commit()

        result = await handle_search_group(
            db_session, gid, alice.id, Entities(description="dinner")
        )
        assert result["status"] == "list"
        assert "expenses" in result
        assert "notes" in result

    @pytest.mark.asyncio
    async def test_returns_only_matching_domains(self, db_session, sample_group):
        gid = sample_group.group_id
        alice = sample_group.alice

        await expense_repo.create_expense(
            db_session, gid, alice.id, 2000, "USD", "taxi"
        )
        await db_session.commit()

        result = await handle_search_group(
            db_session, gid, alice.id, Entities(description="taxi")
        )
        assert result["status"] == "list"
        assert "expenses" in result
        assert "reminders" not in result
        assert "itinerary" not in result
        assert "checklist" not in result
        assert "notes" not in result

    @pytest.mark.asyncio
    async def test_no_matches_returns_not_found(self, db_session, sample_group):
        result = await handle_search_group(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            Entities(description="nonexistent"),
        )
        assert result["status"] == "not_found"
        assert result["query"] == "nonexistent"


class TestListMode:
    @pytest.mark.asyncio
    async def test_returns_all_domains(self, db_session, sample_group):
        gid = sample_group.group_id
        alice = sample_group.alice

        await expense_repo.create_expense(
            db_session, gid, alice.id, 1000, "EUR", "lunch"
        )
        await note_repo.create_note(db_session, gid, alice.id, content="wifi: abc123")
        await checklist_repo.create_item(db_session, gid, alice.id, "buy milk")
        await db_session.commit()

        result = await handle_search_group(
            db_session, gid, alice.id, Entities()
        )
        assert result["status"] == "list"
        assert "expenses" in result
        assert "notes" in result
        assert "checklist" in result

    @pytest.mark.asyncio
    async def test_empty_group_returns_empty(self, db_session, sample_group):
        result = await handle_search_group(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            Entities(),
        )
        assert result["status"] == "empty"
        assert result["entity"] == "group_data"

    @pytest.mark.asyncio
    async def test_expense_summary_fields(self, db_session, sample_group):
        gid = sample_group.group_id
        alice = sample_group.alice

        await expense_repo.create_expense(
            db_session, gid, alice.id, 3000, "GBP", "museum tickets"
        )
        await db_session.commit()

        result = await handle_search_group(
            db_session, gid, alice.id, Entities()
        )
        exp = result["expenses"][0]
        assert "number" not in exp
        assert exp["description"] == "museum tickets"
        assert exp["amount_cents"] == 3000
        assert exp["currency"] == "GBP"
