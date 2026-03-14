"""Tests for group repository."""

from __future__ import annotations

import pytest

from piazza.db.repositories.group import get_or_create_group


class TestGetOrCreateGroup:
    @pytest.mark.asyncio
    async def test_creates_new_group(self, db_session):
        group = await get_or_create_group(db_session, "120363099@g.us")
        assert group.wa_jid == "120363099@g.us"
        assert group.id is not None

    @pytest.mark.asyncio
    async def test_returns_existing(self, db_session):
        g1 = await get_or_create_group(db_session, "120363099@g.us")
        g2 = await get_or_create_group(db_session, "120363099@g.us")
        assert g1.id == g2.id

    @pytest.mark.asyncio
    async def test_different_jids_different_groups(self, db_session):
        g1 = await get_or_create_group(db_session, "120363001@g.us")
        g2 = await get_or_create_group(db_session, "120363002@g.us")
        assert g1.id != g2.id
