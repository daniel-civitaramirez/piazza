"""Tests for checklist service layer."""

from __future__ import annotations

import pytest

from piazza.core.exceptions import NotFoundError
from piazza.db.models.checklist import ChecklistItem
from piazza.db.repositories import checklist as checklist_repo
from piazza.tools.checklist import service


class TestAddItem:
    @pytest.mark.asyncio
    async def test_add_default_list(self, db_session, sample_group):
        result = await service.add_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="buy milk",
        )
        assert isinstance(result, ChecklistItem)
        assert result.content == "buy milk"
        assert result.list_name == "default"
        assert result.is_done is False

    @pytest.mark.asyncio
    async def test_add_named_list(self, db_session, sample_group):
        result = await service.add_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="sunscreen", list_name="packing",
        )
        assert isinstance(result, ChecklistItem)
        assert result.list_name == "packing"


class TestListItems:
    @pytest.mark.asyncio
    async def test_list_empty(self, db_session, sample_group):
        result = await service.list_items(db_session, sample_group.group_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_with_items(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="milk",
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="eggs",
        )
        await db_session.commit()

        result = await service.list_items(db_session, sample_group.group_id)
        assert len(result) == 2
        assert all(isinstance(i, ChecklistItem) for i in result)

    @pytest.mark.asyncio
    async def test_list_filters_by_name(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="milk", list_name="shopping",
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="passport", list_name="packing",
        )
        await db_session.commit()

        result = await service.list_items(
            db_session, sample_group.group_id, list_name="shopping"
        )
        assert len(result) == 1
        assert result[0].content == "milk"


class TestCheckItemByNumber:
    @pytest.mark.asyncio
    async def test_check_valid_number(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="task one",
        )
        await db_session.commit()

        result = await service.check_item_by_number(
            db_session, sample_group.group_id, 1
        )
        assert isinstance(result, ChecklistItem)
        assert result.is_done is True
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_check_out_of_range(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await service.check_item_by_number(
                db_session, sample_group.group_id, 99
            )
        assert exc_info.value.entity == "checklist_item"
        assert exc_info.value.number == 99
        assert exc_info.value.total == 0

    @pytest.mark.asyncio
    async def test_check_zero(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="task",
        )
        await db_session.commit()

        with pytest.raises(NotFoundError) as exc_info:
            await service.check_item_by_number(
                db_session, sample_group.group_id, 0
            )
        assert exc_info.value.number == 0
        assert exc_info.value.total == 1


class TestCheckItemByQuery:
    @pytest.mark.asyncio
    async def test_check_single_match(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="buy milk",
        )
        await db_session.commit()

        result = await service.check_item_by_query(
            db_session, sample_group.group_id, "milk"
        )
        assert isinstance(result, ChecklistItem)
        assert result.is_done is True

    @pytest.mark.asyncio
    async def test_check_no_match(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await service.check_item_by_query(
                db_session, sample_group.group_id, "nonexistent"
            )
        assert exc_info.value.query == "nonexistent"

    @pytest.mark.asyncio
    async def test_check_ambiguous(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="buy milk",
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="get milk",
        )
        await db_session.commit()

        result = await service.check_item_by_query(
            db_session, sample_group.group_id, "milk"
        )
        assert isinstance(result, list)
        assert len(result) == 2


class TestUncheckItemByNumber:
    @pytest.mark.asyncio
    async def test_uncheck_valid(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="task",
        )
        await checklist_repo.check_item(db_session, item)
        await db_session.commit()

        result = await service.uncheck_item_by_number(
            db_session, sample_group.group_id, 1
        )
        assert result.is_done is False
        assert result.completed_at is None


class TestDeleteItemByNumber:
    @pytest.mark.asyncio
    async def test_delete_valid(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="to delete",
        )
        await db_session.commit()

        result = await service.delete_item_by_number(
            db_session, sample_group.group_id, 1
        )
        assert isinstance(result, ChecklistItem)
        assert result.content == "to delete"

        remaining = await checklist_repo.get_items(
            db_session, sample_group.group_id, include_done=True
        )
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_delete_out_of_range(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await service.delete_item_by_number(
                db_session, sample_group.group_id, 5
            )
        assert exc_info.value.number == 5


class TestDeleteItemByQuery:
    @pytest.mark.asyncio
    async def test_delete_single_match(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="buy milk",
        )
        await db_session.commit()

        result = await service.delete_item_by_query(
            db_session, sample_group.group_id, "milk"
        )
        assert isinstance(result, ChecklistItem)

    @pytest.mark.asyncio
    async def test_delete_no_match(self, db_session, sample_group):
        with pytest.raises(NotFoundError):
            await service.delete_item_by_query(
                db_session, sample_group.group_id, "nonexistent"
            )

    @pytest.mark.asyncio
    async def test_delete_ambiguous(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="buy milk",
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="get milk",
        )
        await db_session.commit()

        result = await service.delete_item_by_query(
            db_session, sample_group.group_id, "milk"
        )
        assert isinstance(result, list)
        assert len(result) == 2

        # Both should still exist
        remaining = await checklist_repo.get_items(
            db_session, sample_group.group_id, include_done=True
        )
        assert len(remaining) == 2
