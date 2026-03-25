"""Tests for notes intent handlers."""

from __future__ import annotations

import pytest

from piazza.db.repositories import note as queries
from piazza.tools.notes import handler
from piazza.tools.schemas import Entities


class TestHandleNoteSave:
    @pytest.mark.asyncio
    async def test_save_with_tag(self, db_session, sample_group):
        entities = Entities(description="BeachLife2026", tag="wifi password")
        result = await handler.handle_note_save(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "save_note"
        assert result["content"] == "BeachLife2026"
        assert result["tag"] == "wifi password"

    @pytest.mark.asyncio
    async def test_save_without_tag(self, db_session, sample_group):
        entities = Entities(description="The restaurant is La Piazzetta")
        result = await handler.handle_note_save(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "save_note"
        assert result["content"] == "The restaurant is La Piazzetta"
        assert "tag" not in result


class TestHandleNoteFind:
    @pytest.mark.asyncio
    async def test_successful_find(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        entities = Entities(description="wifi")
        result = await handler.handle_note_find(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "list"
        assert len(result["notes"]) == 1
        assert result["notes"][0]["content"] == "BeachLife2026"

    @pytest.mark.asyncio
    async def test_no_results(self, db_session, sample_group):
        entities = Entities(description="nonexistent thing")
        result = await handler.handle_note_find(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "notes"


class TestHandleNoteList:
    @pytest.mark.asyncio
    async def test_empty_list(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_note_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "empty"
        assert result["entity"] == "notes"

    @pytest.mark.asyncio
    async def test_list_with_items(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi",
        )
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="ABC123", tag="booking ref",
        )
        await db_session.flush()

        entities = Entities()
        result = await handler.handle_note_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "list"
        assert len(result["notes"]) == 2
        tags = [n["tag"] for n in result["notes"]]
        assert "wifi" in tags
        assert "booking ref" in tags
        assert result["notes"][0]["number"] == 1
        assert result["notes"][1]["number"] == 2


class TestHandleNoteDelete:
    @pytest.mark.asyncio
    async def test_successful_delete(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        entities = Entities(description="wifi")
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "delete_note"
        assert result["content"] == "BeachLife2026"

    @pytest.mark.asyncio
    async def test_delete_no_match(self, db_session, sample_group):
        entities = Entities(description="nonexistent")
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "note"
        assert result["query"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_delete_by_number(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        entities = Entities(item_number=1)
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "delete_note"

    @pytest.mark.asyncio
    async def test_delete_by_number_out_of_range(self, db_session, sample_group):
        entities = Entities(item_number=99)
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["number"] == 99
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_delete_no_identifier(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"

    @pytest.mark.asyncio
    async def test_delete_ambiguous(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="old wifi code", tag="wifi home",
        )
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="new wifi code", tag="wifi office",
        )
        await db_session.flush()

        entities = Entities(description="wifi")
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ambiguous"
        assert result["entity"] == "note"
        assert len(result["matches"]) == 2
