"""Tests for checklist repository — round-trip encryption."""

from __future__ import annotations

import pytest

from piazza.db.repositories import checklist as checklist_repo


class TestChecklistRepoEncryption:
    @pytest.mark.asyncio
    async def test_create_and_read_roundtrip(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="buy milk", list_name="shopping",
        )
        assert item.content == "buy milk"
        assert item.list_name == "shopping"
        assert item.is_done is False

    @pytest.mark.asyncio
    async def test_get_items_decrypts(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="eggs", list_name="groceries",
        )
        await db_session.commit()

        items = await checklist_repo.get_items(db_session, sample_group.group_id)
        assert len(items) == 1
        assert items[0].content == "eggs"
        assert items[0].list_name == "groceries"

    @pytest.mark.asyncio
    async def test_default_list_name(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="something",
        )
        assert item.list_name == "default"

    @pytest.mark.asyncio
    async def test_find_items_case_insensitive(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="Buy Milk",
        )
        await db_session.commit()

        results = await checklist_repo.find_items(db_session, sample_group.group_id, "milk")
        assert len(results) == 1
        assert results[0].content == "Buy Milk"

    @pytest.mark.asyncio
    async def test_check_and_uncheck(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="task",
        )
        assert item.is_done is False
        assert item.completed_at is None

        await checklist_repo.check_item(db_session, item)
        assert item.is_done is True
        assert item.completed_at is not None

        await checklist_repo.uncheck_item(db_session, item)
        assert item.is_done is False
        assert item.completed_at is None

    @pytest.mark.asyncio
    async def test_get_items_filters_done(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="done task",
        )
        await checklist_repo.check_item(db_session, item)
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="pending task",
        )
        await db_session.commit()

        # Default: exclude done
        pending = await checklist_repo.get_items(db_session, sample_group.group_id)
        assert len(pending) == 1
        assert pending[0].content == "pending task"

        # Include done
        all_items = await checklist_repo.get_items(
            db_session, sample_group.group_id, include_done=True
        )
        assert len(all_items) == 2

    @pytest.mark.asyncio
    async def test_get_items_filters_by_list_name(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="milk", list_name="shopping",
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="passport", list_name="packing",
        )
        await db_session.commit()

        shopping = await checklist_repo.get_items(
            db_session, sample_group.group_id, list_name="shopping"
        )
        assert len(shopping) == 1
        assert shopping[0].content == "milk"

    @pytest.mark.asyncio
    async def test_delete_item(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="to delete",
        )
        await db_session.commit()

        await checklist_repo.delete_item(db_session, item)
        await db_session.commit()

        items = await checklist_repo.get_items(
            db_session, sample_group.group_id, include_done=True
        )
        assert len(items) == 0
