"""Tests for the message processing pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from piazza.core.exceptions import UNAPPROVED_GROUP_RESPONSE
from piazza.db.models.injection_log import InjectionLog
from piazza.db.repositories.group import get_or_create_group
from piazza.messaging.whatsapp.schemas import Message
from piazza.workers.process_message import process_message


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
        """A clean message does not create injection_log records."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("clean", False),
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
                return_value=("clean", False, 0.0),
            ),
        ):
            await process_message(
                _make_message("clean"), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        assert len(result.scalars().all()) == 0


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
    async def test_l1_flagged_creates_log(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L1-flagged message creates an injection_log record with layer=L1."""
        with patch(
            "piazza.workers.process_message.sanitize_input",
            return_value=("flagged", True),
        ):
            await process_message(
                _make_message("flagged"), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].layer == "L1"


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
    async def test_l2_flagged_creates_log(
        self, db_session, redis_client, mock_agent_runner
    ):
        """L2-flagged message creates an injection_log record with layer=L2."""
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
            await process_message(
                _make_message("text"), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].layer == "L2"
        assert logs[0].risk_score == 0.92


class TestL1ShortCircuitsL2:
    @pytest.mark.asyncio
    async def test_l1_flagged_only_creates_l1_log(
        self, db_session, redis_client, mock_agent_runner
    ):
        """When L1 flags, only one injection_log record is created (L1 only)."""
        with patch(
            "piazza.workers.process_message.sanitize_input",
            return_value=("bad text", True),
        ):
            await process_message(
                _make_message("bad text"), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        assert logs[0].layer == "L1"


class TestInjectionLogRecords:
    @pytest.mark.asyncio
    async def test_log_records_correct_risk_score(
        self, db_session, redis_client, mock_agent_runner
    ):
        """Injection log records contain the correct risk score."""
        with (
            patch(
                "piazza.workers.process_message.sanitize_input",
                return_value=("text", False),
            ),
            patch(
                "piazza.workers.process_message.screen_for_injection",
                return_value=("text", True, 0.91),
            ),
        ):
            await process_message(
                _make_message("text"), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        log = result.scalar_one()
        assert log.risk_score == 0.91

    @pytest.mark.asyncio
    async def test_log_records_user_hash(
        self, db_session, redis_client, mock_agent_runner
    ):
        """Injection log records contain the user's phone hash."""
        from piazza.core.encryption import hash_phone

        with patch(
            "piazza.workers.process_message.sanitize_input",
            return_value=("text", True),
        ):
            await process_message(
                _make_message("text"), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        log = result.scalar_one()
        expected_hash = hash_phone("5511111111111@s.whatsapp.net")
        assert log.user_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_records_snippet_truncated(
        self, db_session, redis_client, mock_agent_runner
    ):
        """Injection log snippet is truncated to 100 chars."""
        long_text = "x" * 200
        with patch(
            "piazza.workers.process_message.sanitize_input",
            return_value=(long_text, True),
        ):
            await process_message(
                _make_message(long_text), db_session, redis_client
            )

        result = await db_session.execute(select(InjectionLog))
        log = result.scalar_one()
        assert log.snippet is not None
        assert len(log.snippet) == 100
