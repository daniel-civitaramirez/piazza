"""Tests for checklist intent handlers."""

from __future__ import annotations

import pytest

from piazza.db.repositories import checklist as checklist_repo
from piazza.tools.checklist import handler
from piazza.tools.schemas import Entities


class TestHandleItemAdd:
    @pytest.mark.asyncio
    async def test_add_default_list(self, db_session, sample_group):
        entities = Entities(description="milk")
        result = await handler.handle_item_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "add_item"
        assert result["content"] == "milk"
        assert result["done"] is False
        assert "list" not in result

    @pytest.mark.asyncio
    async def test_add_named_list(self, db_session, sample_group):
        entities = Entities(description="sunscreen", list_name="packing")
        result = await handler.handle_item_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["content"] == "sunscreen"
        assert result["list"] == "packing"

    @pytest.mark.asyncio
    async def test_add_missing_description(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_item_add(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_description"


class TestHandleItemList:
    @pytest.mark.asyncio
    async def test_empty_list(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_item_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "empty"
        assert result["entity"] == "checklist_items"

    @pytest.mark.asyncio
    async def test_list_with_items(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="milk"
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.bob.id, content="eggs"
        )
        await db_session.commit()

        entities = Entities()
        result = await handler.handle_item_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "list"
        assert len(result["checklist_items"]) == 2
        assert result["checklist_items"][0]["number"] == 1
        assert result["checklist_items"][1]["number"] == 2

    @pytest.mark.asyncio
    async def test_list_filtered_by_name(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="milk", list_name="shopping",
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="passport", list_name="packing",
        )
        await db_session.commit()

        entities = Entities(list_name="shopping")
        result = await handler.handle_item_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "list"
        assert len(result["checklist_items"]) == 1
        assert result["checklist_items"][0]["content"] == "milk"

    @pytest.mark.asyncio
    async def test_list_hides_done_by_default(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="milk"
        )
        await checklist_repo.check_item(db_session, item)
        await db_session.commit()

        entities = Entities()
        result = await handler.handle_item_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "empty"

    @pytest.mark.asyncio
    async def test_list_show_done(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="milk"
        )
        await checklist_repo.check_item(db_session, item)
        await db_session.commit()

        entities = Entities(show_done=True)
        result = await handler.handle_item_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "list"
        assert len(result["checklist_items"]) == 1
        assert result["checklist_items"][0]["done"] is True


class TestHandleItemCheck:
    @pytest.mark.asyncio
    async def test_check_by_number(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="milk"
        )
        await db_session.commit()

        entities = Entities(item_number=1)
        result = await handler.handle_item_check(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "check_item"
        assert result["content"] == "milk"
        assert result["done"] is True

    @pytest.mark.asyncio
    async def test_check_by_description(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="buy milk"
        )
        await db_session.commit()

        entities = Entities(description="milk")
        result = await handler.handle_item_check(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "check_item"

    @pytest.mark.asyncio
    async def test_check_not_found(self, db_session, sample_group):
        entities = Entities(item_number=99)
        result = await handler.handle_item_check(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["number"] == 99

    @pytest.mark.asyncio
    async def test_check_ambiguous(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="buy milk"
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.bob.id, content="get milk"
        )
        await db_session.commit()

        entities = Entities(description="milk")
        result = await handler.handle_item_check(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ambiguous"
        assert result["entity"] == "checklist_item"
        assert len(result["matches"]) == 2

    @pytest.mark.asyncio
    async def test_check_missing_identifier(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_item_check(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"


class TestHandleItemUncheck:
    @pytest.mark.asyncio
    async def test_uncheck_by_number(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="milk"
        )
        await checklist_repo.check_item(db_session, item)
        await db_session.commit()

        entities = Entities(item_number=1)
        result = await handler.handle_item_uncheck(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "uncheck_item"
        assert result["done"] is False

    @pytest.mark.asyncio
    async def test_uncheck_by_description(self, db_session, sample_group):
        item = await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="buy milk"
        )
        await checklist_repo.check_item(db_session, item)
        await db_session.commit()

        entities = Entities(description="milk")
        result = await handler.handle_item_uncheck(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "uncheck_item"


class TestHandleItemDelete:
    @pytest.mark.asyncio
    async def test_delete_by_number(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="milk"
        )
        await db_session.commit()

        entities = Entities(item_number=1)
        result = await handler.handle_item_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "delete_item"
        assert result["content"] == "milk"

    @pytest.mark.asyncio
    async def test_delete_by_description(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="buy milk"
        )
        await db_session.commit()

        entities = Entities(description="milk")
        result = await handler.handle_item_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "delete_item"

    @pytest.mark.asyncio
    async def test_delete_not_found(self, db_session, sample_group):
        entities = Entities(description="nonexistent")
        result = await handler.handle_item_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["query"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_delete_ambiguous(self, db_session, sample_group):
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.alice.id, content="buy milk"
        )
        await checklist_repo.create_item(
            db_session, sample_group.group_id, sample_group.bob.id, content="get milk"
        )
        await db_session.commit()

        entities = Entities(description="milk")
        result = await handler.handle_item_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ambiguous"
        assert len(result["matches"]) == 2

    @pytest.mark.asyncio
    async def test_delete_missing_identifier(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_item_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"
