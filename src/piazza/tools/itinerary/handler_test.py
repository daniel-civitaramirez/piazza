"""Tests for itinerary intent handlers."""

from __future__ import annotations

import pytest

from piazza.db.repositories import itinerary as queries
from piazza.tools.itinerary import handler
from piazza.tools.schemas import Entities


class TestHandleItineraryAdd:
    @pytest.mark.asyncio
    async def test_empty_items_returns_error(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "describe what to add" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_add_single_item(self, db_session, sample_group):
        entities = Entities(items=[
            {"title": "Flight BA247", "item_type": "flight", "start_at": "2025-03-15T11:00:00"},
        ])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Flight BA247" in result
        assert "Added" in result

    @pytest.mark.asyncio
    async def test_successful_add_multiple_items(self, db_session, sample_group):
        entities = Entities(items=[
            {"title": "Flight BA247", "item_type": "flight", "start_at": "2025-03-15T11:00:00"},
            {"title": "Hotel Arts", "item_type": "hotel", "location": "Barcelona"},
        ])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Flight BA247" in result
        assert "Hotel Arts" in result

    @pytest.mark.asyncio
    async def test_add_item_with_all_fields(self, db_session, sample_group):
        entities = Entities(items=[
            {
                "title": "Dinner at La Piazza",
                "item_type": "restaurant",
                "start_at": "2025-03-15T20:00:00",
                "end_at": "2025-03-15T22:00:00",
                "location": "Barcelona",
                "notes": "Reservation under Smith",
            },
        ])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Dinner at La Piazza" in result

    @pytest.mark.asyncio
    async def test_add_item_title_only(self, db_session, sample_group):
        entities = Entities(items=[{"title": "Beach day"}])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Beach day" in result


class TestHandleItineraryShow:
    @pytest.mark.asyncio
    async def test_empty_itinerary(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_itinerary_show(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No itinerary items" in result

    @pytest.mark.asyncio
    async def test_show_with_items(self, db_session, sample_group):
        from datetime import datetime, timezone

        await queries.create_item(
            db_session,
            group_id=sample_group.group_id,
            item_type="flight",
            title="Flight BA247",
            start_at=datetime(2025, 3, 15, 11, 0, tzinfo=timezone.utc),
        )
        await db_session.flush()

        entities = Entities()
        result = await handler.handle_itinerary_show(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Flight BA247" in result
        assert "Itinerary" in result


class TestHandleItineraryRemove:
    @pytest.mark.asyncio
    async def test_empty_description_returns_error(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify what to remove" in result.lower()

    @pytest.mark.asyncio
    async def test_remove_existing_item(self, db_session, sample_group):
        await queries.create_item(
            db_session,
            group_id=sample_group.group_id,
            item_type="hotel",
            title="Hotel Check-in",
        )
        await db_session.flush()

        entities = Entities(description="Hotel Check-in")
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Removed" in result
        assert "Hotel Check-in" in result

    @pytest.mark.asyncio
    async def test_remove_no_match(self, db_session, sample_group):
        entities = Entities(description="Nonexistent thing")
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No itinerary item" in result
