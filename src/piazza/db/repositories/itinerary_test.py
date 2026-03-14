"""Tests for itinerary repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from piazza.db.repositories.itinerary import (
    create_item,
    find_items_by_title,
    get_items,
)


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_creates_item(self, db_session, sample_group):
        item = await create_item(
            db_session, sample_group.group_id, "activity", "Beach Day",
            start_at=datetime(2025, 7, 1, 10, 0, tzinfo=timezone.utc),
            location="Copacabana",
        )
        assert item.title == "Beach Day"
        assert item.item_type == "activity"
        assert item.location == "Copacabana"


class TestGetItems:
    @pytest.mark.asyncio
    async def test_ordered_by_start_at(self, db_session, sample_group):
        now = datetime.now(timezone.utc)
        await create_item(
            db_session, sample_group.group_id, "activity", "Later",
            start_at=now + timedelta(hours=2),
        )
        await create_item(
            db_session, sample_group.group_id, "activity", "Sooner",
            start_at=now + timedelta(hours=1),
        )
        await create_item(
            db_session, sample_group.group_id, "activity", "No time",
        )
        items = await get_items(db_session, sample_group.group_id)
        assert items[0].title == "Sooner"
        assert items[1].title == "Later"
        assert items[2].title == "No time"  # nulls last


class TestFindItemsByTitle:
    @pytest.mark.asyncio
    async def test_case_insensitive(self, db_session, sample_group):
        await create_item(
            db_session, sample_group.group_id, "activity", "Beach Day",
        )
        results = await find_items_by_title(db_session, sample_group.group_id, "beach")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_match(self, db_session, sample_group):
        await create_item(
            db_session, sample_group.group_id, "activity", "Beach Day",
        )
        results = await find_items_by_title(db_session, sample_group.group_id, "mountain")
        assert len(results) == 0
