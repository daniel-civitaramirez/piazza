"""Tests for group membership sync handlers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select

from piazza.db.models.group import Group
from piazza.db.models.member import Member
from piazza.messaging.whatsapp.group_sync import (
    handle_group_participants_update,
    handle_group_upsert,
    learn_display_name,
)


@pytest.fixture
def patch_session(db_session):
    """Patch AsyncSessionFactory so handlers use the test db_session."""

    @asynccontextmanager
    async def _factory():
        yield db_session

    with patch(
        "piazza.messaging.whatsapp.group_sync.AsyncSessionFactory", _factory
    ):
        yield


class TestHandleGroupUpsert:
    @pytest.mark.asyncio
    async def test_creates_group_and_members(self, db_session, patch_session):
        raw = {
            "data": {
                "id": "120363099@g.us",
                "subject": "Trip Group",
                "participants": [
                    {"id": "5511111111111@s.whatsapp.net"},
                    {"id": "5522222222222@s.whatsapp.net"},
                ],
            }
        }
        await handle_group_upsert(raw)

        groups = (await db_session.execute(select(Group))).scalars().all()
        assert len(groups) == 1
        assert groups[0].wa_jid == "120363099@g.us"

        members = (await db_session.execute(select(Member))).scalars().all()
        assert len(members) == 2

    @pytest.mark.asyncio
    async def test_filters_non_user_jids(self, db_session, patch_session):
        raw = {
            "data": {
                "id": "120363099@g.us",
                "participants": [
                    {"id": "5511111111111@s.whatsapp.net"},
                    {"id": "0:abcdef123456@lid"},
                ],
            }
        }
        await handle_group_upsert(raw)

        members = (await db_session.execute(select(Member))).scalars().all()
        assert len(members) == 1

    @pytest.mark.asyncio
    async def test_idempotent_on_repeat(self, db_session, patch_session):
        raw = {
            "data": {
                "id": "120363099@g.us",
                "participants": [{"id": "5511111111111@s.whatsapp.net"}],
            }
        }
        await handle_group_upsert(raw)
        await handle_group_upsert(raw)

        groups = (await db_session.execute(select(Group))).scalars().all()
        assert len(groups) == 1
        members = (await db_session.execute(select(Member))).scalars().all()
        assert len(members) == 1

    @pytest.mark.asyncio
    async def test_malformed_data_no_crash(self, db_session, patch_session):
        raw = {"data": {}}
        await handle_group_upsert(raw)  # should not raise


class TestHandleGroupParticipantsUpdate:
    @pytest.mark.asyncio
    async def test_add_creates_member(self, db_session, sample_group, patch_session):
        raw = {
            "data": {
                "groupJid": "120363001@g.us",
                "action": "add",
                "participants": ["5544444444444@s.whatsapp.net"],
                "participantsData": [
                    {"jid": "5544444444444@s.whatsapp.net", "pushName": "Diana"}
                ],
            }
        }
        await handle_group_participants_update(raw)

        members = (await db_session.execute(select(Member))).scalars().all()
        names = {m.display_name for m in members}
        assert "Diana" in names

    @pytest.mark.asyncio
    async def test_add_reactivates_inactive(self, db_session, sample_group, patch_session):
        sample_group.alice.is_active = False
        await db_session.flush()

        raw = {
            "data": {
                "groupJid": "120363001@g.us",
                "action": "add",
                "participants": ["5511111111111@s.whatsapp.net"],
                "participantsData": [],
            }
        }
        await handle_group_participants_update(raw)
        await db_session.refresh(sample_group.alice)
        assert sample_group.alice.is_active is True

    @pytest.mark.asyncio
    async def test_remove_deactivates(self, db_session, sample_group, patch_session):
        raw = {
            "data": {
                "groupJid": "120363001@g.us",
                "action": "remove",
                "participants": ["5511111111111@s.whatsapp.net"],
                "participantsData": [],
            }
        }
        await handle_group_participants_update(raw)
        await db_session.refresh(sample_group.alice)
        assert sample_group.alice.is_active is False

    @pytest.mark.asyncio
    async def test_promote_demote_no_db_change(self, db_session, sample_group, patch_session):
        raw = {
            "data": {
                "groupJid": "120363001@g.us",
                "action": "promote",
                "participants": ["5511111111111@s.whatsapp.net"],
                "participantsData": [],
            }
        }
        await handle_group_participants_update(raw)
        await db_session.refresh(sample_group.alice)
        assert sample_group.alice.is_active is True


class TestLearnDisplayName:
    @pytest.mark.asyncio
    async def test_updates_display_name(self, db_session, sample_group, patch_session):
        await learn_display_name(
            "120363001@g.us", "5511111111111@s.whatsapp.net", "Alice Updated"
        )
        await db_session.refresh(sample_group.alice)
        assert sample_group.alice.display_name == "Alice Updated"

    @pytest.mark.asyncio
    async def test_creates_member_if_new(self, db_session, sample_group, patch_session):
        await learn_display_name(
            "120363001@g.us", "5599999999999@s.whatsapp.net", "NewPerson"
        )
        members = (await db_session.execute(select(Member))).scalars().all()
        names = {m.display_name for m in members}
        assert "NewPerson" in names
