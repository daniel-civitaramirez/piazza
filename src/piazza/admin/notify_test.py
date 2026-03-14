"""Tests for admin notification."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from piazza.admin.notify import _build_message, notify_admin_new_group


class TestBuildMessage:
    def test_includes_group_name_and_jid(self):
        msg = _build_message(
            "120363001@g.us",
            "Trip to Italy",
            ["5511111111111@s.whatsapp.net", "5522222222222@s.whatsapp.net"],
        )
        assert "Trip to Italy" in msg
        assert "120363001@g.us" in msg

    def test_unnamed_group(self):
        msg = _build_message("120363001@g.us", None, [])
        assert "(unnamed)" in msg

    def test_shows_participant_count(self):
        jids = [f"55{i:011d}@s.whatsapp.net" for i in range(5)]
        msg = _build_message("120363001@g.us", "Test", jids)
        assert "Participants (5)" in msg

    def test_truncates_long_participant_list(self):
        jids = [f"55{i:011d}@s.whatsapp.net" for i in range(15)]
        msg = _build_message("120363001@g.us", "Test", jids)
        assert "(+5 more)" in msg

    def test_includes_approval_instructions(self):
        msg = _build_message("120363001@g.us", "Test", [])
        assert "approval_status" in msg
        assert "approved" in msg


class TestNotifyAdminNewGroup:
    @pytest.mark.asyncio
    async def test_sends_dm_when_admin_configured(self):
        mock_send = AsyncMock()
        with (
            patch("piazza.admin.notify.settings") as mock_settings,
            patch("piazza.messaging.whatsapp.client.send_text", mock_send),
        ):
            mock_settings.admin_jid = "559999@s.whatsapp.net"
            await notify_admin_new_group("120363001@g.us", "Test Group", [])

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "559999@s.whatsapp.net"
        assert "120363001@g.us" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_skipped_when_no_admin(self):
        mock_send = AsyncMock()
        with (
            patch("piazza.admin.notify.settings") as mock_settings,
            patch("piazza.messaging.whatsapp.client.send_text", mock_send),
        ):
            mock_settings.admin_jid = ""
            await notify_admin_new_group("120363001@g.us", "Test", [])

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_raise_on_send_failure(self):
        mock_send = AsyncMock(side_effect=Exception("network error"))
        with (
            patch("piazza.admin.notify.settings") as mock_settings,
            patch("piazza.messaging.whatsapp.client.send_text", mock_send),
        ):
            mock_settings.admin_jid = "559999@s.whatsapp.net"
            # Should not raise
            await notify_admin_new_group("120363001@g.us", "Test", [])
