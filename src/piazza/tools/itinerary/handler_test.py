"""Tests for itinerary intent handlers."""

from __future__ import annotations

from datetime import datetime, timezone

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
        assert result["status"] == "error"
        assert result["reason"] == "missing_items"

    @pytest.mark.asyncio
    async def test_successful_add_single_item(self, db_session, sample_group):
        entities = Entities(items=[
            {"title": "Flight BA247", "item_type": "flight", "start_at": "2025-03-15T11:00:00"},
        ])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "add_itinerary"
        assert len(result["items"]) == 1
        assert result["items"][0]["title"] == "Flight BA247"
        assert result["items"][0]["item_type"] == "flight"
        assert result["items"][0]["start_at"] is not None

    @pytest.mark.asyncio
    async def test_successful_add_multiple_items(self, db_session, sample_group):
        entities = Entities(items=[
            {"title": "Flight BA247", "item_type": "flight", "start_at": "2025-03-15T11:00:00"},
            {"title": "Hotel Arts", "item_type": "hotel", "location": "Barcelona"},
        ])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert len(result["items"]) == 2
        titles = [item["title"] for item in result["items"]]
        assert "Flight BA247" in titles
        assert "Hotel Arts" in titles

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
        assert result["status"] == "ok"
        item = result["items"][0]
        assert item["title"] == "Dinner at La Piazza"
        assert item["item_type"] == "restaurant"
        assert item["location"] == "Barcelona"
        assert item["notes"] == "Reservation under Smith"
        assert item["start_at"] is not None
        assert item["end_at"] is not None

    @pytest.mark.asyncio
    async def test_add_item_title_only(self, db_session, sample_group):
        entities = Entities(items=[{"title": "Beach day"}])
        result = await handler.handle_itinerary_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["items"][0]["title"] == "Beach day"
        assert result["items"][0]["start_at"] is None


class TestHandleItineraryShow:
    @pytest.mark.asyncio
    async def test_empty_itinerary(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_itinerary_show(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "empty"
        assert result["entity"] == "itinerary"

    @pytest.mark.asyncio
    async def test_show_with_items(self, db_session, sample_group):
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
        assert result["status"] == "list"
        assert len(result["itinerary"]) == 1
        assert result["itinerary"][0]["title"] == "Flight BA247"
        assert result["itinerary"][0]["number"] == 1


class TestHandleItineraryRemove:
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
        assert result["status"] == "ok"
        assert result["action"] == "remove_itinerary"
        assert result["item"]["title"] == "Hotel Check-in"

    @pytest.mark.asyncio
    async def test_remove_no_match(self, db_session, sample_group):
        entities = Entities(description="Nonexistent thing")
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "itinerary_item"
        assert result["query"] == "Nonexistent thing"

    @pytest.mark.asyncio
    async def test_remove_by_number(self, db_session, sample_group):
        await queries.create_item(
            db_session,
            group_id=sample_group.group_id,
            item_type="hotel",
            title="Hotel Check-in",
        )
        await db_session.flush()

        entities = Entities(item_number=1)
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "remove_itinerary"
        assert result["item"]["title"] == "Hotel Check-in"

    @pytest.mark.asyncio
    async def test_remove_by_number_out_of_range(self, db_session, sample_group):
        entities = Entities(item_number=99)
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "itinerary_item"
        assert result["number"] == 99
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_remove_no_identifier(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"

    @pytest.mark.asyncio
    async def test_remove_ambiguous(self, db_session, sample_group):
        await queries.create_item(
            db_session,
            group_id=sample_group.group_id,
            item_type="restaurant",
            title="Dinner at La Piazza",
        )
        await queries.create_item(
            db_session,
            group_id=sample_group.group_id,
            item_type="restaurant",
            title="Dinner at El Bulli",
        )
        await db_session.flush()

        entities = Entities(description="Dinner")
        result = await handler.handle_itinerary_remove(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ambiguous"
        assert result["entity"] == "itinerary_item"
        assert len(result["matches"]) == 2
