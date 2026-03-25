"""Tests for notes service and query layer."""

from __future__ import annotations

import pytest

from piazza.core.exceptions import NotFoundError
from piazza.db.models.note import Note
from piazza.db.repositories import note as queries
from piazza.tools.notes import service


class TestNoteSave:
    @pytest.mark.asyncio
    async def test_save_with_tag(self, db_session, sample_group):
        result = await service.save_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        assert isinstance(result, Note)
        assert result.content == "BeachLife2026"
        assert result.tag == "wifi password"

    @pytest.mark.asyncio
    async def test_save_without_tag(self, db_session, sample_group):
        result = await service.save_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="The door code is 4321",
        )
        assert isinstance(result, Note)
        assert result.content == "The door code is 4321"
        assert result.tag is None

    @pytest.mark.asyncio
    async def test_save_duplicate_tag_allowed(self, db_session, sample_group):
        await service.save_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="OldPassword", tag="wifi",
        )
        result = await service.save_note(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="NewPassword", tag="wifi",
        )
        assert isinstance(result, Note)
        assert result.content == "NewPassword"

        # Both notes should exist
        notes = await queries.get_notes(db_session, sample_group.group_id)
        assert len(notes) == 2


class TestNoteFind:
    @pytest.mark.asyncio
    async def test_find_by_tag(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        result = await service.find_notes(db_session, sample_group.group_id, "wifi")
        assert len(result) == 1
        assert result[0].content == "BeachLife2026"

    @pytest.mark.asyncio
    async def test_find_by_content(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="Check-in at 3pm, check-out at 11am", tag="hotel",
        )
        await db_session.flush()

        result = await service.find_notes(db_session, sample_group.group_id, "check-in")
        assert len(result) == 1
        assert "3pm" in result[0].content

    @pytest.mark.asyncio
    async def test_find_no_matches(self, db_session, sample_group):
        result = await service.find_notes(db_session, sample_group.group_id, "nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_find_case_insensitive(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="ABC123", tag="Booking Ref",
        )
        await db_session.flush()

        result = await service.find_notes(db_session, sample_group.group_id, "booking ref")
        assert len(result) == 1
        assert result[0].content == "ABC123"


class TestNoteList:
    @pytest.mark.asyncio
    async def test_list_empty(self, db_session, sample_group):
        result = await service.list_notes(db_session, sample_group.group_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_with_notes(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="ABC123", tag="booking ref",
        )
        await db_session.flush()

        result = await service.list_notes(db_session, sample_group.group_id)
        assert len(result) == 2
        assert all(isinstance(n, Note) for n in result)
        tags = [n.tag for n in result]
        assert "wifi password" in tags
        assert "booking ref" in tags


class TestNoteDelete:
    @pytest.mark.asyncio
    async def test_delete_single_match(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        result = await service.delete_note(db_session, sample_group.group_id, "wifi")
        assert isinstance(result, Note)
        assert result.content == "BeachLife2026"

        notes = await queries.get_notes(db_session, sample_group.group_id)
        assert len(notes) == 0

    @pytest.mark.asyncio
    async def test_delete_no_match(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await service.delete_note(db_session, sample_group.group_id, "nonexistent")
        assert exc_info.value.entity == "note"
        assert exc_info.value.query == "nonexistent"

    @pytest.mark.asyncio
    async def test_delete_multiple_matches_returns_list(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="old wifi code", tag="wifi home",
        )
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.bob.id,
            content="new wifi code", tag="wifi office",
        )
        await db_session.flush()

        result = await service.delete_note(db_session, sample_group.group_id, "wifi")
        assert isinstance(result, list)
        assert len(result) == 2
        tags = [n.tag for n in result]
        assert "wifi home" in tags
        assert "wifi office" in tags

        # Both notes should still exist
        notes = await queries.get_notes(db_session, sample_group.group_id)
        assert len(notes) == 2


class TestNoteDeleteByNumber:
    @pytest.mark.asyncio
    async def test_delete_by_number(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        result = await service.delete_note_by_number(db_session, sample_group.group_id, 1)
        assert isinstance(result, Note)
        assert result.content == "BeachLife2026"

    @pytest.mark.asyncio
    async def test_delete_by_number_out_of_range(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await service.delete_note_by_number(db_session, sample_group.group_id, 99)
        assert exc_info.value.entity == "note"
        assert exc_info.value.number == 99
        assert exc_info.value.total == 0

    @pytest.mark.asyncio
    async def test_delete_by_number_zero(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="note1", tag="tag1",
        )
        await db_session.flush()

        with pytest.raises(NotFoundError) as exc_info:
            await service.delete_note_by_number(db_session, sample_group.group_id, 0)
        assert exc_info.value.number == 0
        assert exc_info.value.total == 1
