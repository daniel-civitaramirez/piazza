"""Tests for message_log repository."""

from __future__ import annotations

import pytest

from piazza.db.repositories.message_log import (
    create_entry,
    get_by_wa_message_id,
    get_recent,
)


class TestCreateEntry:
    @pytest.mark.asyncio
    async def test_user_message(self, db_session, sample_group):
        entry = await create_entry(
            db_session, sample_group.group_id, "user", "hello",
            member_id=sample_group.alice.id, wa_message_id="wa_123",
        )
        assert entry.role == "user"
        assert entry.content == "hello"
        assert entry.member_id == sample_group.alice.id
        assert entry.wa_message_id == "wa_123"

    @pytest.mark.asyncio
    async def test_assistant_message(self, db_session, sample_group):
        entry = await create_entry(
            db_session, sample_group.group_id, "assistant", "hi there",
        )
        assert entry.role == "assistant"
        assert entry.member_id is None
        assert entry.wa_message_id is None


class TestGetRecent:
    @pytest.mark.asyncio
    async def test_returns_oldest_first(self, db_session, sample_group):
        await create_entry(db_session, sample_group.group_id, "user", "first")
        await create_entry(db_session, sample_group.group_id, "assistant", "second")
        await create_entry(db_session, sample_group.group_id, "user", "third")

        messages = await get_recent(db_session, sample_group.group_id)
        assert [m.content for m in messages] == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_respects_limit(self, db_session, sample_group):
        for i in range(5):
            await create_entry(db_session, sample_group.group_id, "user", f"msg{i}")

        messages = await get_recent(db_session, sample_group.group_id, limit=3)
        assert len(messages) == 3
        assert messages[0].content == "msg2"

    @pytest.mark.asyncio
    async def test_empty(self, db_session, sample_group):
        messages = await get_recent(db_session, sample_group.group_id)
        assert messages == []


class TestGetByWaMessageId:
    @pytest.mark.asyncio
    async def test_found(self, db_session, sample_group):
        await create_entry(
            db_session, sample_group.group_id, "user", "hello",
            wa_message_id="wa_456",
        )
        result = await get_by_wa_message_id(db_session, "wa_456")
        assert result is not None
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_not_found(self, db_session, sample_group):
        result = await get_by_wa_message_id(db_session, "nonexistent")
        assert result is None
