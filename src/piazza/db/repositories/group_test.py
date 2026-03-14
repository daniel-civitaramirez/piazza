"""Tests for group repository."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from piazza.db.repositories.group import get_or_create_group


class TestGetOrCreateGroup:
    @pytest.mark.asyncio
    async def test_creates_new_group(self, db_session):
        group, created = await get_or_create_group(db_session, "120363099@g.us")
        assert group.wa_jid == "120363099@g.us"
        assert group.id is not None
        assert created is True

    @pytest.mark.asyncio
    async def test_returns_existing(self, db_session):
        g1, created1 = await get_or_create_group(db_session, "120363099@g.us")
        g2, created2 = await get_or_create_group(db_session, "120363099@g.us")
        assert g1.id == g2.id
        assert created1 is True
        assert created2 is False

    @pytest.mark.asyncio
    async def test_different_jids_different_groups(self, db_session):
        g1, _ = await get_or_create_group(db_session, "120363001@g.us")
        g2, _ = await get_or_create_group(db_session, "120363002@g.us")
        assert g1.id != g2.id

    @pytest.mark.asyncio
    async def test_auto_approve_when_no_admin(self, db_session):
        """When admin_jid is empty, new groups are auto-approved."""
        with patch("piazza.db.repositories.group.settings") as mock_settings:
            mock_settings.admin_jid = ""
            group, _ = await get_or_create_group(db_session, "120363010@g.us")
        assert group.approval_status == "approved"

    @pytest.mark.asyncio
    async def test_pending_when_admin_configured(self, db_session):
        """When admin_jid is set, new groups default to pending."""
        with patch("piazza.db.repositories.group.settings") as mock_settings:
            mock_settings.admin_jid = "559999@s.whatsapp.net"
            group, _ = await get_or_create_group(db_session, "120363011@g.us")
        assert group.approval_status == "pending"
