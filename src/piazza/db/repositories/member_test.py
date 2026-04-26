"""Tests for member repository."""

from __future__ import annotations

import pytest

from piazza.conftest import TEST_ENCRYPTION_KEY
from piazza.core.encryption import encrypt, hash_phone
from piazza.db.models.member import Member
from piazza.config.settings import settings
from piazza.db.repositories.member import (
    _get_member_by_name,
    deactivate_member,
    find_member_by_name,
    get_active_members,
    get_all_members,
    get_or_create_member_by_jid,
)


BOT_JID = "5500000000000@s.whatsapp.net"


@pytest.fixture
def configured_bot_jid(monkeypatch):
    """Pin settings.bot_jid for tests that depend on the bot filter."""
    monkeypatch.setattr(settings, "bot_jid", BOT_JID)
    return BOT_JID


def _insert_member(db_session, group_id, jid, name, *, is_active=True):
    m = Member(
        group_id=group_id,
        wa_id_hash=hash_phone(jid),
        wa_id_encrypted=encrypt(jid, TEST_ENCRYPTION_KEY),
        display_name=encrypt(name, TEST_ENCRYPTION_KEY),
        is_active=is_active,
    )
    db_session.add(m)
    return m


class TestGetOrCreateMemberByJid:
    @pytest.mark.asyncio
    async def test_creates_with_phone_fallback(self, db_session, sample_group):
        jid = "5599999999999@s.whatsapp.net"
        member = await get_or_create_member_by_jid(db_session, sample_group.group_id, jid)
        assert member.display_name == "5599999999999"
        assert member.is_active is True

    @pytest.mark.asyncio
    async def test_creates_with_display_name(self, db_session, sample_group):
        jid = "5599999999999@s.whatsapp.net"
        member = await get_or_create_member_by_jid(
            db_session, sample_group.group_id, jid, display_name="NewPerson"
        )
        assert member.display_name == "NewPerson"

    @pytest.mark.asyncio
    async def test_updates_name_from_push_name(self, db_session, sample_group):
        jid = "5599999999999@s.whatsapp.net"
        await get_or_create_member_by_jid(db_session, sample_group.group_id, jid)
        member = await get_or_create_member_by_jid(
            db_session, sample_group.group_id, jid, display_name="RealName"
        )
        assert member.display_name == "RealName"

    @pytest.mark.asyncio
    async def test_does_not_overwrite_name_with_none(self, db_session, sample_group):
        jid = "5599999999999@s.whatsapp.net"
        await get_or_create_member_by_jid(
            db_session, sample_group.group_id, jid, display_name="RealName"
        )
        member = await get_or_create_member_by_jid(
            db_session, sample_group.group_id, jid, display_name=None
        )
        assert member.display_name == "RealName"

    @pytest.mark.asyncio
    async def test_reactivates_inactive(self, db_session, sample_group):
        jid = "5599999999999@s.whatsapp.net"
        m = await get_or_create_member_by_jid(db_session, sample_group.group_id, jid)
        m.is_active = False
        await db_session.flush()
        m2 = await get_or_create_member_by_jid(db_session, sample_group.group_id, jid)
        assert m2.is_active is True
        assert m2.id == m.id

    @pytest.mark.asyncio
    async def test_idempotent(self, db_session, sample_group):
        jid = "5599999999999@s.whatsapp.net"
        m1 = await get_or_create_member_by_jid(db_session, sample_group.group_id, jid)
        m2 = await get_or_create_member_by_jid(db_session, sample_group.group_id, jid)
        assert m1.id == m2.id


class TestDeactivateMember:
    @pytest.mark.asyncio
    async def test_deactivate_existing(self, db_session, sample_group):
        result = await deactivate_member(
            db_session, sample_group.group_id, "5511111111111@s.whatsapp.net"
        )
        assert result is not None
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_nonexistent_returns_none(self, db_session, sample_group):
        result = await deactivate_member(
            db_session, sample_group.group_id, "0000000000000@s.whatsapp.net"
        )
        assert result is None


class TestFindMemberByName:
    @pytest.mark.asyncio
    async def test_exact_match(self, db_session, sample_group):
        member, candidates = await find_member_by_name(
            db_session, sample_group.group_id, "alice"
        )
        assert member is not None
        assert member.display_name == "Alice"
        assert candidates == []

    @pytest.mark.asyncio
    async def test_substring_single(self, db_session, sample_group):
        member, candidates = await find_member_by_name(
            db_session, sample_group.group_id, "arli"
        )
        assert member is not None
        assert member.display_name == "Charlie"
        assert candidates == []

    @pytest.mark.asyncio
    async def test_substring_multiple(self, db_session, sample_group):
        m = Member(
            group_id=sample_group.group_id,
            wa_id_hash=hash_phone("5588888888888@s.whatsapp.net"),
            wa_id_encrypted=encrypt("5588888888888@s.whatsapp.net", TEST_ENCRYPTION_KEY),
            display_name=encrypt("Alicia", TEST_ENCRYPTION_KEY),
        )
        db_session.add(m)
        await db_session.flush()

        member, candidates = await find_member_by_name(
            db_session, sample_group.group_id, "Ali"
        )
        assert member is None
        assert len(candidates) == 2

    @pytest.mark.asyncio
    async def test_no_match(self, db_session, sample_group):
        member, candidates = await find_member_by_name(
            db_session, sample_group.group_id, "Zara"
        )
        assert member is None
        assert candidates == []

    @pytest.mark.asyncio
    async def test_typo_resolves_to_unique_match(self, db_session, sample_group):
        # "Aliec" is a typo of "Alice" — fuzzy should resolve unambiguously
        member, candidates = await find_member_by_name(
            db_session, sample_group.group_id, "Aliec"
        )
        assert member is not None
        assert member.display_name == "Alice"
        assert candidates == []


class TestBotFilter:
    """The bot's own member row must never appear in roster reads."""

    @pytest.mark.asyncio
    async def test_get_active_members_excludes_bot(
        self, db_session, sample_group, configured_bot_jid
    ):
        _insert_member(db_session, sample_group.group_id, configured_bot_jid, "Piazza")
        await db_session.flush()

        members = await get_active_members(db_session, sample_group.group_id)
        names = {m.display_name for m in members}
        assert names == {"Alice", "Bob", "Charlie"}
        assert "Piazza" not in names

    @pytest.mark.asyncio
    async def test_get_all_members_excludes_bot(
        self, db_session, sample_group, configured_bot_jid
    ):
        _insert_member(
            db_session, sample_group.group_id, configured_bot_jid, "Piazza", is_active=False
        )
        await db_session.flush()

        members = await get_all_members(db_session, sample_group.group_id)
        names = {m.display_name for m in members}
        assert names == {"Alice", "Bob", "Charlie"}

    @pytest.mark.asyncio
    async def test_filter_no_op_when_bot_jid_unset(
        self, db_session, sample_group, monkeypatch
    ):
        # Empty bot_jid => no filter applied; the bot row (if any) shows up.
        monkeypatch.setattr(settings, "bot_jid", "")
        _insert_member(db_session, sample_group.group_id, BOT_JID, "Piazza")
        await db_session.flush()

        members = await get_active_members(db_session, sample_group.group_id)
        names = {m.display_name for m in members}
        assert "Piazza" in names

    @pytest.mark.asyncio
    async def test_filter_does_not_drop_other_members(
        self, db_session, sample_group, configured_bot_jid
    ):
        # Sanity: filtering must only drop the exact bot wa_id_hash, nothing else.
        members = await get_active_members(db_session, sample_group.group_id)
        assert len(members) == 3

    @pytest.mark.asyncio
    async def test_get_member_by_name_excludes_bot(
        self, db_session, sample_group, configured_bot_jid
    ):
        # If the bot's display name was learned (e.g. "Piazza"), an exact-name
        # lookup must still skip it — otherwise mutation tools could resolve
        # the bot as a participant.
        _insert_member(db_session, sample_group.group_id, configured_bot_jid, "Piazza")
        await db_session.flush()

        member = await _get_member_by_name(db_session, sample_group.group_id, "Piazza")
        assert member is None

    @pytest.mark.asyncio
    async def test_find_member_by_name_excludes_bot_on_exact_match(
        self, db_session, sample_group, configured_bot_jid
    ):
        _insert_member(db_session, sample_group.group_id, configured_bot_jid, "Piazza")
        await db_session.flush()

        member, candidates = await find_member_by_name(
            db_session, sample_group.group_id, "Piazza"
        )
        assert member is None
        assert candidates == []


class TestGetMemberByName:
    @pytest.mark.asyncio
    async def test_resolve_by_name(self, db_session, sample_group):
        member = await _get_member_by_name(db_session, sample_group.group_id, "Alice")
        assert member is not None
        assert member.display_name == "Alice"

    @pytest.mark.asyncio
    async def test_resolve_case_insensitive(self, db_session, sample_group):
        member = await _get_member_by_name(db_session, sample_group.group_id, "alice")
        assert member is not None

    @pytest.mark.asyncio
    async def test_resolve_unknown_returns_none(self, db_session, sample_group):
        member = await _get_member_by_name(db_session, sample_group.group_id, "Zara")
        assert member is None
