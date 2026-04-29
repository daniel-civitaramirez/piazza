"""Tests for agent context building."""

from __future__ import annotations

import pytest

from piazza.agent.context import (
    AgentContext,
    _authored_block,
    _from_log,
    _inline_tag,
    _speaker_name,
    build_user_content,
)
from piazza.db.repositories import message_log as message_log_repo


class TestInlineTag:
    def test_wraps_value(self):
        assert _inline_tag("foo", "bar") == "<foo>bar</foo>"

    def test_empty_value(self):
        assert _inline_tag("group_members", "") == "<group_members></group_members>"


class TestAuthoredBlock:
    def test_single_entry(self):
        assert _authored_block("blk", [("Alice", "hi")]) == "<blk>\n[Alice]: hi\n</blk>"

    def test_multiple_entries_preserve_order(self):
        result = _authored_block(
            "recent_context",
            [("Alice", "hi"), ("Piazza", "hello"), ("Bob", "yo")],
        )
        assert result == (
            "<recent_context>\n"
            "[Alice]: hi\n"
            "[Piazza]: hello\n"
            "[Bob]: yo\n"
            "</recent_context>"
        )

    def test_accepts_generator(self):
        gen = ((n, t) for n, t in [("A", "1"), ("B", "2")])
        result = _authored_block("blk", gen)
        assert "[A]: 1" in result
        assert "[B]: 2" in result


class TestSpeakerName:
    @pytest.mark.asyncio
    async def test_assistant_role(self, db_session, sample_group):
        msg = await message_log_repo.create_entry(
            db_session, sample_group.group_id, "assistant", "hi",
        )
        assert _speaker_name(msg) == "Piazza"

    @pytest.mark.asyncio
    async def test_user_with_member(self, db_session, sample_group):
        await message_log_repo.create_entry(
            db_session, sample_group.group_id, "user", "hello",
            member_id=sample_group.alice.id,
        )
        msgs = await message_log_repo.get_recent(db_session, sample_group.group_id)
        assert _speaker_name(msgs[0]) == "Alice"

    @pytest.mark.asyncio
    async def test_user_without_member(self, db_session, sample_group):
        msg = await message_log_repo.create_entry(
            db_session, sample_group.group_id, "user", "anon",
        )
        assert _speaker_name(msg) == "Unknown"


class TestFromLog:
    @pytest.mark.asyncio
    async def test_returns_name_and_content(self, db_session, sample_group):
        await message_log_repo.create_entry(
            db_session, sample_group.group_id, "user", "hello there",
            member_id=sample_group.alice.id,
        )
        msgs = await message_log_repo.get_recent(db_session, sample_group.group_id)
        assert _from_log(msgs[0]) == ("Alice", "hello there")


class TestBuildUserContent:
    def _ctx(self, db_session, sample_group, **overrides) -> AgentContext:
        defaults = dict(
            text="hello world",
            sender_name="Alice",
            member_names=["Alice", "Bob", "Charlie"],
            session=db_session,
            group_id=sample_group.group_id,
            member_id=sample_group.alice.id,
            tz="UTC",
        )
        defaults.update(overrides)
        return AgentContext(**defaults)

    @pytest.mark.asyncio
    async def test_minimal_only_required_blocks(self, db_session, sample_group):
        out = build_user_content(self._ctx(db_session, sample_group, member_names=[]))
        assert "<current_time>" in out
        assert "<message_sender>Alice</message_sender>" in out
        assert "<group_members>" not in out
        assert "<recent_context>" not in out
        assert "<user_replying_to_message>" not in out
        assert "<user_message>\n[Alice]: hello world\n</user_message>" in out

    @pytest.mark.asyncio
    async def test_includes_group_members(self, db_session, sample_group):
        out = build_user_content(self._ctx(db_session, sample_group))
        assert "<group_members>Alice, Bob, Charlie</group_members>" in out

    @pytest.mark.asyncio
    async def test_recent_without_reply(self, db_session, sample_group):
        await message_log_repo.create_entry(
            db_session, sample_group.group_id, "user", "first",
            member_id=sample_group.alice.id,
        )
        recent = await message_log_repo.get_recent(db_session, sample_group.group_id)
        out = build_user_content(self._ctx(db_session, sample_group, recent_messages=recent))
        assert "<recent_context>\n[Alice]: first\n</recent_context>" in out
        assert "<user_replying_to_message>" not in out

    @pytest.mark.asyncio
    async def test_full_context_block_order(self, db_session, sample_group):
        await message_log_repo.create_entry(
            db_session, sample_group.group_id, "user", "anyone here?",
            member_id=sample_group.bob.id, wa_message_id="wa_1",
        )
        await message_log_repo.create_entry(
            db_session, sample_group.group_id, "assistant", "yes I am",
            wa_message_id="wa_2",
        )
        recent = await message_log_repo.get_recent(db_session, sample_group.group_id)
        reply = await message_log_repo.get_by_wa_message_id(db_session, "wa_2")

        out = build_user_content(self._ctx(
            db_session, sample_group,
            text="thanks",
            reply_to_id="wa_2",
            recent_messages=recent,
            reply_context=reply,
        ))

        positions = [
            out.index("<current_time>"),
            out.index("<message_sender>"),
            out.index("<group_members>"),
            out.index("<recent_context>"),
            out.index("<user_replying_to_message>"),
            out.index("<user_message>"),
        ]
        assert positions == sorted(positions)

        assert "[Bob]: anyone here?" in out
        assert "[Piazza]: yes I am" in out
        assert (
            "<user_replying_to_message>\n[Piazza]: yes I am\n</user_replying_to_message>"
            in out
        )
        assert "<user_message>\n[Alice]: thanks\n</user_message>" in out

    @pytest.mark.asyncio
    async def test_reply_author_is_independent_of_message_sender(
        self, db_session, sample_group,
    ):
        await message_log_repo.create_entry(
            db_session, sample_group.group_id, "user", "original from charlie",
            member_id=sample_group.charlie.id, wa_message_id="wa_x",
        )
        reply = await message_log_repo.get_by_wa_message_id(db_session, "wa_x")
        out = build_user_content(self._ctx(
            db_session, sample_group, reply_context=reply,
        ))
        assert "<message_sender>Alice</message_sender>" in out
        assert (
            "<user_replying_to_message>\n[Charlie]: original from charlie\n"
            "</user_replying_to_message>"
        ) in out
