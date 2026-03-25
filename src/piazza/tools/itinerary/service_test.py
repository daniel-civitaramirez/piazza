"""Tests for itinerary business logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from piazza.core.exceptions import NotFoundError
from piazza.db.repositories import itinerary as queries
from piazza.tools.itinerary.service import add_from_items, delete_item, list_itinerary

# ---------- add_from_items ----------


class TestAddFromItems:
    @pytest.mark.asyncio
    async def test_add_single_item(self, db_session, sample_group):
        result = await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [{"title": "Flight BA247", "item_type": "flight", "start_at": "2025-03-15T11:00:00"}],
        )
        assert len(result) == 1
        assert result[0].title == "Flight BA247"
        assert result[0].item_type == "flight"

    @pytest.mark.asyncio
    async def test_add_multiple_items(self, db_session, sample_group):
        result = await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [
                {"title": "Flight BA247", "item_type": "flight"},
                {"title": "Hotel Arts", "item_type": "hotel", "location": "Barcelona"},
            ],
        )
        assert len(result) == 2
        assert result[0].title == "Flight BA247"
        assert result[1].title == "Hotel Arts"
        assert result[1].location == "Barcelona"

    @pytest.mark.asyncio
    async def test_add_item_with_invalid_date_still_works(self, db_session, sample_group):
        result = await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [{"title": "Beach day", "start_at": "not-a-date"}],
        )
        assert len(result) == 1
        assert result[0].title == "Beach day"
        assert result[0].start_at is None

    @pytest.mark.asyncio
    async def test_add_creates_knowledge_base_note(self, db_session, sample_group):
        from piazza.db.repositories import note as note_repo

        await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [{"title": "Flight BA247", "item_type": "flight"}],
        )
        notes = await note_repo.find_notes(db_session, sample_group.group_id, "Flight BA247")
        assert len(notes) >= 1


# ---------- Item creation (DB) ----------


class TestItemCreation:
    @pytest.mark.asyncio
    async def test_add_single_item(self, db_session, sample_group):
        item = await queries.create_item(
            db_session,
            sample_group.group_id,
            item_type="flight",
            title="Flight BA247",
            start_at=datetime(2025, 3, 15, 11, 0, tzinfo=timezone.utc),
            end_at=datetime(2025, 3, 15, 14, 0, tzinfo=timezone.utc),
        )
        await db_session.flush()
        assert item.item_type == "flight"
        assert item.title == "Flight BA247"

    @pytest.mark.asyncio
    async def test_add_item_all_fields(self, db_session, sample_group):
        item = await queries.create_item(
            db_session,
            sample_group.group_id,
            item_type="hotel",
            title="Hotel Arts",
            start_at=datetime(2025, 3, 15, 15, 0, tzinfo=timezone.utc),
            location="Barcelona",
            notes="Check-in at 3pm",
            metadata={"confirmation": "ABC123"},
        )
        await db_session.flush()
        assert item.location == "Barcelona"
        assert item.notes == "Check-in at 3pm"
        assert item.metadata_ == {"confirmation": "ABC123"}


# ---------- Itinerary display ----------


class TestItineraryDisplay:
    @pytest.mark.asyncio
    async def test_empty_itinerary(self, db_session, sample_group):
        result = await list_itinerary(db_session, sample_group.group_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_items_returned_in_order(self, db_session, sample_group):
        await queries.create_item(
            db_session, sample_group.group_id,
            "flight", "Morning flight",
            start_at=datetime(2025, 3, 15, 8, 0, tzinfo=timezone.utc),
        )
        await queries.create_item(
            db_session, sample_group.group_id,
            "restaurant", "Dinner",
            start_at=datetime(2025, 3, 15, 20, 0, tzinfo=timezone.utc),
        )
        await queries.create_item(
            db_session, sample_group.group_id,
            "activity", "Museum",
            start_at=datetime(2025, 3, 16, 10, 0, tzinfo=timezone.utc),
        )
        await db_session.flush()

        result = await list_itinerary(db_session, sample_group.group_id)
        assert len(result) == 3
        assert result[0].title == "Morning flight"
        assert result[1].title == "Dinner"
        assert result[2].title == "Museum"

    @pytest.mark.asyncio
    async def test_items_sorted_chronologically(self, db_session, sample_group):
        await queries.create_item(
            db_session, sample_group.group_id,
            "restaurant", "Late dinner",
            start_at=datetime(2025, 3, 15, 21, 0, tzinfo=timezone.utc),
        )
        await queries.create_item(
            db_session, sample_group.group_id,
            "flight", "Early flight",
            start_at=datetime(2025, 3, 15, 6, 0, tzinfo=timezone.utc),
        )
        await db_session.flush()

        items = await queries.get_items(db_session, sample_group.group_id)
        assert items[0].title == "Early flight"
        assert items[1].title == "Late dinner"


# ---------- Delete ----------


class TestDeleteItem:
    @pytest.mark.asyncio
    async def test_delete_exact_match(self, db_session, sample_group):
        await queries.create_item(
            db_session, sample_group.group_id,
            "hotel", "Hotel Arts",
        )
        await db_session.flush()

        result = await delete_item(db_session, sample_group.group_id, "Hotel Arts")
        assert not isinstance(result, list)
        assert result.title == "Hotel Arts"

    @pytest.mark.asyncio
    async def test_delete_partial_match(self, db_session, sample_group):
        await queries.create_item(
            db_session, sample_group.group_id,
            "hotel", "Hotel Arts Barcelona",
        )
        await db_session.flush()

        result = await delete_item(db_session, sample_group.group_id, "Hotel Arts")
        assert not isinstance(result, list)
        assert result.title == "Hotel Arts Barcelona"

    @pytest.mark.asyncio
    async def test_delete_multiple_matches_returns_list(self, db_session, sample_group):
        await queries.create_item(
            db_session, sample_group.group_id,
            "restaurant", "Dinner at La Piazza",
        )
        await queries.create_item(
            db_session, sample_group.group_id,
            "restaurant", "Dinner at El Bulli",
        )
        await db_session.flush()

        result = await delete_item(db_session, sample_group.group_id, "Dinner")
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_delete_no_match_raises(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await delete_item(db_session, sample_group.group_id, "nonexistent")
        assert exc_info.value.entity == "itinerary_item"
        assert exc_info.value.query == "nonexistent"
