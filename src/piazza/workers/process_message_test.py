"""Tests for the message processing pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from piazza.core.exceptions import UNAPPROVED_GROUP_RESPONSE, WhatsAppSendError
from piazza.db.repositories.group import get_or_create_group
from piazza.messaging.whatsapp.schemas import Message
from piazza.workers.process_message import _maybe_send_welcome, process_message


def _make_message(text: str) -> Message:
    return Message(
        sender_jid="5511111111111@s.whatsapp.net",
        sender_name="Alice",
        group_jid="120363001@g.us",
        text=text,
    )


@pytest.fixture(autouse=True)
def _reset_sanitizer_patterns():
    import piazza.workers.security.sanitizer as mod

    mod._INJECTION_PATTERNS = []
    yield
    mod._INJECTION_PATTERNS = []


@pytest.fixture(autouse=True)
def _suppress_welcome():
    """Pipeline tests are orthogonal to onboarding — skip the welcome path."""
    with patch(
        "piazza.workers.process_message._maybe_send_welcome",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture
def mock_agent_runner():
    """Patch agent factories to return mocks."""
    agent = MagicMock()
    agent.run = AsyncMock(return_value="agent response")
    with (
        patch(
            "piazza.workers.process_message.get_opensource_agent",
            return_value=agent,
        ),
        patch(
            "piazza.workers.process_message.get_claude_agent",
            return_value=agent,
        ),
    ):
        yield agent


# ---------- Approval gate tests ----------


class TestApprovalGate:
    @pytest.mark.asyncio
    async def test_unapproved_group_rejected(
        self, db_session, redis_client, mock_agent_runner
    ):
        """A pending group gets the unapproved response."""
        group, _ = await get_or_create_group(db_session, "120363099@g.us")
        group.approval_status = "pending"
        await db_session.flush()

        msg = _make_message("hello")
        msg.group_jid = "120363099@g.us"
        response = await process_message(msg, db_session, redis_client)
        assert response == UNAPPROVED_GROUP_RESPONSE
        mock_agent_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejected_group_rejected(
        self, db_session, redis_client, mock_agent_runner
    ):
        """A rejected group gets the unapproved response."""
        group, _ = await get_or_create_group(db_session, "120363099@g.us")
        group.approval_status = "rejected"
        await db_session.flush()

        msg = _make_message("hello")
        msg.group_jid = "120363099@g.us"
        response = await process_message(msg, db_session, redis_client)
        assert response == UNAPPROVED_GROUP_RESPONSE
        mock_agent_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_approved_group_proceeds(
        self, db_session, redis_client, mock_agent_runner
    ):
        """An approved group reaches the agent pipeline."""
        group, _ = await get_or_create_group(db_session, "120363099@g.us")
        group.approval_status = "approved"
        await db_session.flush()

        msg = _make_message("help me")
        msg.group_jid = "120363099@g.us"
        with patch(
            "piazza.workers.process_message.screen_for_injection",
            return_value=("help me", False, 0.0),
        ):
            response = await process_message(msg, db_session, redis_client)
        mock_agent_runner.run.assert_called_once()
        assert response == "agent response"


# ---------- Agent pipeline tests ----------


class TestAgentPipeline:
    @pytest.mark.asyncio
    async def test_clean_message_calls_agent(
        self, db_session, redis_client, mock_agent_runner
    ):
        """A clean message passes security layers and reaches the agent."""
        with patch(
            "piazza.workers.process_message.screen_for_injection",
            return_value=("help me", False, 0.0),
        ):
            response = await process_message(
                _make_message("help me"), db_session, redis_client
            )
        mock_agent_runner.run.assert_called_once()
        assert response == "agent response"

    @pytest.mark.asyncio
    async def test_agent_receives_context(
        self, db_session, redis_client, mock_agent_runner
    ):
        """The agent receives an AgentContext with correct sender and text."""
        with patch(
            "piazza.workers.process_message.screen_for_injection",
            return_value=("hello world", False, 0.0),
        ):
            await process_message(
                _make_message("hello world"), db_session, redis_client
            )
        context = mock_agent_runner.run.call_args[0][0]
        assert context.text == "hello world"
        assert context.sender_name == "Alice"

    @pytest.mark.asyncio
    async def test_agent_receives_reply_to_id(
        self, db_session, redis_client, mock_agent_runner
    ):
        """reply_to_message_id is passed through to agent context."""
        msg = _make_message("change that to 50")
        msg.reply_to_message_id = "msg_12345"
        with patch(
            "piazza.workers.process_message.screen_for_injection",
            return_value=("change that to 50", False, 0.0),
        ):
            await process_message(msg, db_session, redis_client)
        context = mock_agent_runner.run.call_args[0][0]
        assert context.reply_to_id == "msg_12345"

    @pytest.mark.asyncio
    async def test_no_injection_log_for_clean_message(
        self, db_session, redis_client, mock_agent_runner
    ):
        """A clean message does not trigger injection logging."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("clean", False),
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
                return_value=("clean", False, 0.0),
            ),
            patch("piazza.workers.process_message.logger") as mock_logger,
        ):
            await process_message(
                _make_message("clean"), db_session, redis_client
            )

        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_opensource_disabled_skips_to_claude(
        self, db_session, redis_client
    ):
        """When opensource_agent_enabled=False, Claude is called directly."""
        opensource = MagicMock()
        opensource.run = AsyncMock(return_value="should-not-run")
        claude = MagicMock()
        claude.run = AsyncMock(return_value="claude response")

        with (
            patch(
                "piazza.workers.process_message.get_opensource_agent",
                return_value=opensource,
            ),
            patch(
                "piazza.workers.process_message.get_claude_agent",
                return_value=claude,
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
                return_value=("hello", False, 0.0),
            ),
            patch(
                "piazza.workers.process_message.settings.opensource_agent_enabled",
                False,
            ),
        ):
            response = await process_message(
                _make_message("hello"), db_session, redis_client
            )

        opensource.run.assert_not_called()
        claude.run.assert_called_once()
        assert response == "claude response"


# ---------- Injection pipeline tests ----------


class TestL1Flagging:
    @pytest.mark.asyncio
    async def test_l1_flagged_rejects_immediately(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L1-flagged message is rejected without calling the agent."""
        with patch(
            "piazza.workers.process_message.sanitize_input",
            return_value=("suspicious text", True),
        ):
            response = await process_message(
                _make_message("suspicious text"), db_session, redis_client
            )
        mock_agent_runner.run.assert_not_called()
        assert "flagged for safety" in response

    @pytest.mark.asyncio
    async def test_l1_flagged_skips_l2(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L1-flagged message does not run L2 screening."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("suspicious text", True),
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
            ) as l2_mock,
        ):
            await process_message(
                _make_message("suspicious text"), db_session, redis_client
            )
            l2_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_l1_flagged_logs_warning(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L1-flagged message logs a warning with layer=L1."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("flagged", True),
            ),
            patch("piazza.workers.process_message.logger") as mock_logger,
        ):
            await process_message(
                _make_message("flagged"), db_session, redis_client
            )

        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[0][0] == "injection_flagged"
        assert call_kwargs[1]["layer"] == "L1"


class TestL2Flagging:
    @pytest.mark.asyncio
    async def test_l2_flagged_rejects_immediately(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L2-flagged message is rejected without calling the agent."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("text", False),
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
                return_value=("text", True, 0.92),
            ),
        ):
            response = await process_message(
                _make_message("text"), db_session, redis_client
            )
        mock_agent_runner.run.assert_not_called()
        assert "flagged for safety" in response

    @pytest.mark.asyncio
    async def test_l2_flagged_logs_warning(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L2-flagged message logs a warning with layer=L2 and risk_score."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("text", False),
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
                return_value=("text", True, 0.92),
            ),
            patch("piazza.workers.process_message.logger") as mock_logger,
        ):
            await process_message(
                _make_message("text"), db_session, redis_client
            )

        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[0][0] == "injection_flagged"
        assert call_kwargs[1]["layer"] == "L2"
        assert call_kwargs[1]["risk_score"] == 0.92


class TestL1ShortCircuitsL2:
    @pytest.mark.asyncio
    async def test_l1_flagged_only_logs_l1(
        self, db_session, redis_client, mock_agent_runner
    ):
        """When L1 flags, only one injection warning is logged (L1 only)."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("bad text", True),
            ),
            patch("piazza.workers.process_message.logger") as mock_logger,
        ):
            await process_message(
                _make_message("bad text"), db_session, redis_client
            )

        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args[1]["layer"] == "L1"


# ---------- Welcome onboarding tests ----------


class TestWelcomeOnboarding:
    """Direct tests of _maybe_send_welcome (the autouse fixture suppresses it elsewhere)."""

    @pytest.mark.asyncio
    async def test_first_message_sends_welcome_and_flips_flag(self, db_session):
        group, _ = await get_or_create_group(db_session, "120363077@g.us")
        await db_session.flush()
        assert group.welcome_sent is False

        with patch(
            "piazza.workers.process_message.wa_client.send_text",
            new=AsyncMock(return_value="wa-msg-1"),
        ) as send:
            await _maybe_send_welcome(db_session, group)

        send.assert_called_once()
        assert group.welcome_sent is True

    @pytest.mark.asyncio
    async def test_already_welcomed_group_is_noop(self, db_session):
        group, _ = await get_or_create_group(db_session, "120363078@g.us")
        group.welcome_sent = True
        await db_session.flush()

        with patch(
            "piazza.workers.process_message.wa_client.send_text",
            new=AsyncMock(),
        ) as send:
            await _maybe_send_welcome(db_session, group)

        send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_failure_keeps_flag_false_for_retry(self, db_session):
        group, _ = await get_or_create_group(db_session, "120363079@g.us")
        await db_session.flush()

        with patch(
            "piazza.workers.process_message.wa_client.send_text",
            new=AsyncMock(side_effect=WhatsAppSendError("boom")),
        ):
            await _maybe_send_welcome(db_session, group)

        assert group.welcome_sent is False
