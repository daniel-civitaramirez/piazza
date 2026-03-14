"""Tests for note repository."""

from __future__ import annotations

import pytest

from piazza.db.repositories.note import create_note, find_notes, get_notes


class TestCreateNote:
    @pytest.mark.asyncio
    async def test_creates_with_tag(self, db_session, sample_group):
        note = await create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            "wifi password is abc123", tag="wifi",
        )
        assert note.content == "wifi password is abc123"
        assert note.tag == "wifi"

    @pytest.mark.asyncio
    async def test_creates_without_tag(self, db_session, sample_group):
        note = await create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            "general note",
        )
        assert note.tag is None


class TestGetNotes:
    @pytest.mark.asyncio
    async def test_ordered_most_recent_first(self, db_session, sample_group):
        await create_note(
            db_session, sample_group.group_id, sample_group.alice.id, "first",
        )
        await create_note(
            db_session, sample_group.group_id, sample_group.alice.id, "second",
        )
        notes = await get_notes(db_session, sample_group.group_id)
        assert notes[0].content == "second"

    @pytest.mark.asyncio
    async def test_empty(self, db_session, sample_group):
        notes = await get_notes(db_session, sample_group.group_id)
        assert notes == []


class TestFindNotes:
    @pytest.mark.asyncio
    async def test_matches_content(self, db_session, sample_group):
        await create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            "beach house address is 123 Main St",
        )
        results = await find_notes(db_session, sample_group.group_id, "beach")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_matches_tag(self, db_session, sample_group):
        await create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            "password is abc123", tag="wifi",
        )
        results = await find_notes(db_session, sample_group.group_id, "wifi")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_match(self, db_session, sample_group):
        await create_note(
            db_session, sample_group.group_id, sample_group.alice.id,
            "some note",
        )
        results = await find_notes(db_session, sample_group.group_id, "zzzzz")
        assert len(results) == 0
