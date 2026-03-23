"""Tests for member repository."""

from __future__ import annotations

import pytest

from piazza.conftest import TEST_ENCRYPTION_KEY
from piazza.core.encryption import encrypt, hash_phone
from piazza.db.models.member import Member
from piazza.db.repositories.member import (
    _get_member_by_name,
    deactivate_member,
    find_member_by_name,
    get_or_create_member_by_jid,
)


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
            display_name="Alicia",
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
