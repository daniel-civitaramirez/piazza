"""Tests for notes intent handlers."""

from __future__ import annotations

import pytest

from piazza.db.repositories import note as queries
from piazza.tools.notes import handler
from piazza.tools.schemas import Entities


class TestHandleNoteSave:
    @pytest.mark.asyncio
    async def test_empty_description_returns_error(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_note_save(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify what to save" in result.lower()

    @pytest.mark.asyncio
    async def test_save_with_tag(self, db_session, sample_group):
        entities = Entities(description="BeachLife2026", tag="wifi password")
        result = await handler.handle_note_save(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "wifi password" in result
        assert "BeachLife2026" in result
        assert "Saved" in result

    @pytest.mark.asyncio
    async def test_save_without_tag(self, db_session, sample_group):
        entities = Entities(description="The restaurant is La Piazzetta")
        result = await handler.handle_note_save(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "La Piazzetta" in result
        assert "Saved" in result


class TestHandleNoteFind:
    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_note_find(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "looking for" in result.lower()

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
        assert "BeachLife2026" in result

    @pytest.mark.asyncio
    async def test_no_results(self, db_session, sample_group):
        entities = Entities(description="nonexistent thing")
        result = await handler.handle_note_find(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No matching notes" in result


class TestHandleNoteList:
    @pytest.mark.asyncio
    async def test_empty_list(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_note_list(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No notes saved" in result

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
        assert "wifi" in result
        assert "booking ref" in result


class TestHandleNoteDelete:
    @pytest.mark.asyncio
    async def test_empty_description_returns_error(self, db_session, sample_group):
        entities = Entities()
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify which note" in result.lower()

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
        assert "Deleted" in result

    @pytest.mark.asyncio
    async def test_delete_no_match(self, db_session, sample_group):
        entities = Entities(description="nonexistent")
        result = await handler.handle_note_delete(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No note matching" in result
