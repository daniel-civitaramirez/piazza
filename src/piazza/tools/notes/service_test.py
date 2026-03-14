"""Tests for notes service and query layer."""

from __future__ import annotations

import pytest

from piazza.db.repositories import note as queries
from piazza.tools.notes import service


class TestNoteSave:
    @pytest.mark.asyncio
    async def test_save_with_tag(self, db_session, sample_group):
        result = await service.save_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        assert "wifi password" in result
        assert "BeachLife2026" in result
        assert "Saved" in result

    @pytest.mark.asyncio
    async def test_save_without_tag(self, db_session, sample_group):
        result = await service.save_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="The door code is 4321",
        )
        assert "door code is 4321" in result
        assert "Saved" in result

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
        assert "Saved" in result

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
        assert "BeachLife2026" in result

    @pytest.mark.asyncio
    async def test_find_by_content(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="Check-in at 3pm, check-out at 11am", tag="hotel",
        )
        await db_session.flush()

        result = await service.find_notes(db_session, sample_group.group_id, "check-in")
        assert "3pm" in result

    @pytest.mark.asyncio
    async def test_find_no_matches(self, db_session, sample_group):
        result = await service.find_notes(db_session, sample_group.group_id, "nonexistent")
        assert "No matching notes" in result

    @pytest.mark.asyncio
    async def test_find_case_insensitive(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="ABC123", tag="Booking Ref",
        )
        await db_session.flush()

        result = await service.find_notes(db_session, sample_group.group_id, "booking ref")
        assert "ABC123" in result


class TestNoteList:
    @pytest.mark.asyncio
    async def test_list_empty(self, db_session, sample_group):
        result = await service.list_notes(db_session, sample_group.group_id)
        assert "No notes saved" in result

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
        assert "wifi password" in result
        assert "booking ref" in result
        assert "1." in result
        assert "2." in result


class TestNoteDelete:
    @pytest.mark.asyncio
    async def test_delete_single_match(self, db_session, sample_group):
        await queries.create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            content="BeachLife2026", tag="wifi password",
        )
        await db_session.flush()

        result = await service.delete_note(db_session, sample_group.group_id, "wifi")
        assert "Deleted" in result

        notes = await queries.get_notes(db_session, sample_group.group_id)
        assert len(notes) == 0

    @pytest.mark.asyncio
    async def test_delete_no_match(self, db_session, sample_group):
        result = await service.delete_note(db_session, sample_group.group_id, "nonexistent")
        assert "No note matching" in result

    @pytest.mark.asyncio
    async def test_delete_multiple_matches_disambiguation(self, db_session, sample_group):
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
        assert "Multiple notes match" in result
        assert "1." in result
        assert "2." in result

        # Both notes should still exist
        notes = await queries.get_notes(db_session, sample_group.group_id)
        assert len(notes) == 2
