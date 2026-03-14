"""Tests for itinerary business logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from piazza.db.repositories import itinerary as queries
from piazza.tools.itinerary.formatter import (
    format_full_itinerary,
    format_item_confirmation,
)
from piazza.tools.itinerary.service import add_from_items, delete_item, list_itinerary

# ---------- add_from_items ----------


class TestAddFromItems:
    @pytest.mark.asyncio
    async def test_add_single_item(self, db_session, sample_group):
        result = await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [{"title": "Flight BA247", "item_type": "flight", "start_at": "2025-03-15T11:00:00"}],
        )
        assert "Flight BA247" in result
        assert "Added" in result

    @pytest.mark.asyncio
    async def test_add_multiple_items(self, db_session, sample_group):
        result = await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [
                {"title": "Flight BA247", "item_type": "flight"},
                {"title": "Hotel Arts", "item_type": "hotel", "location": "Barcelona"},
            ],
        )
        assert "Flight BA247" in result
        assert "Hotel Arts" in result

    @pytest.mark.asyncio
    async def test_add_item_with_invalid_date_still_works(self, db_session, sample_group):
        result = await add_from_items(
            db_session, sample_group.group_id, sample_group.alice.id,
            [{"title": "Beach day", "start_at": "not-a-date"}],
        )
        assert "Beach day" in result

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
        assert "No itinerary items" in result

    @pytest.mark.asyncio
    async def test_items_grouped_by_day(self, db_session, sample_group):
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
        assert "March 15" in result
        assert "March 16" in result
        assert "Morning flight" in result
        assert "Museum" in result

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


# ---------- Formatting ----------


class TestFormatting:
    def _make_item(self, item_type: str, title: str, start_at=None, location=None):
        """Create a mock ItineraryItem-like object."""
        from unittest.mock import MagicMock
        item = MagicMock()
        item.item_type = item_type
        item.title = title
        item.start_at = start_at
        item.end_at = None
        item.location = location
        return item

    def test_flight_emoji(self):
        item = self._make_item("flight", "BA247", datetime(2025, 3, 15, 11, 0))
        result = format_item_confirmation([item])
        assert "\u2708" in result  # airplane

    def test_hotel_emoji(self):
        item = self._make_item("hotel", "Hotel Arts", datetime(2025, 3, 15, 15, 0))
        result = format_item_confirmation([item])
        assert "\U0001f3e8" in result  # hotel

    def test_restaurant_emoji(self):
        item = self._make_item("restaurant", "La Piazza", datetime(2025, 3, 15, 20, 0))
        result = format_item_confirmation([item])
        assert "\U0001f37d" in result  # fork and knife with plate

    def test_full_itinerary_day_headers(self):
        item = self._make_item("flight", "BA247", datetime(2025, 3, 15, 11, 0))
        result = format_full_itinerary([item])
        assert "*" in result  # WhatsApp bold markers
        assert "March 15" in result

    def test_empty_itinerary(self):
        result = format_full_itinerary([])
        assert "No itinerary items" in result


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
        assert "Removed" in result

    @pytest.mark.asyncio
    async def test_delete_partial_match(self, db_session, sample_group):
        await queries.create_item(
            db_session, sample_group.group_id,
            "hotel", "Hotel Arts Barcelona",
        )
        await db_session.flush()

        result = await delete_item(db_session, sample_group.group_id, "Hotel Arts")
        assert "Removed" in result

    @pytest.mark.asyncio
    async def test_delete_multiple_matches_disambiguation(self, db_session, sample_group):
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
        assert "Multiple items" in result or "Which one" in result

    @pytest.mark.asyncio
    async def test_delete_no_match(self, db_session, sample_group):
        result = await delete_item(db_session, sample_group.group_id, "nonexistent")
        assert "not found" in result.lower() or "No itinerary" in result
