"""Light unit tests for the Agent class — tool loop + error mapping."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anthropic
import pytest

from piazza.agent.agent import Agent, AgentTimeoutError, AgentUnavailableError
from piazza.core.exceptions import GENERIC_ERROR_RESPONSE
from piazza.tools.registry import ToolResult


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_id: str, name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use", id=tool_id, name=name, input=args,
        model_dump=lambda: {
            "type": "tool_use", "id": tool_id, "name": name, "input": args,
        },
    )


def _message(content: list) -> SimpleNamespace:
    return SimpleNamespace(content=content)


@pytest.fixture
def agent():
    """Build an Agent with a fully-mocked Anthropic client."""
    with patch("piazza.agent.agent.anthropic.AsyncAnthropic"):
        a = Agent()
    a.client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    return a


@pytest.fixture
def context():
    """Minimal AgentContext skipping hydration (we test _execute directly)."""
    return SimpleNamespace(
        text="hello",
        sender_name="Alice",
        member_names=["Alice", "Bob"],
        session=None,
        group_id=uuid.uuid4(),
        member_id=uuid.uuid4(),
        tz="UTC",
        reply_to_id=None,
        recent_messages=[],
        reply_context=None,
    )


async def test_no_tools_returns_text_directly(agent, context):
    agent.client.messages.create.return_value = _message([_text_block("hi back")])

    result = await agent._execute(context)

    assert result == "hi back"
    assert agent.client.messages.create.await_count == 1


async def test_tool_loop_executes_tool_then_returns_followup_text(agent, context):
    agent.client.messages.create.side_effect = [
        _message([_tool_use_block("call_1", "list_expenses", {})]),
        _message([_text_block("Here are your expenses.")]),
    ]
    fake_tool = AsyncMock(return_value=ToolResult(success=True, response_text="{}"))

    with patch("piazza.agent.agent.execute_tool", fake_tool):
        result = await agent._execute(context)

    assert result == "Here are your expenses."
    assert agent.client.messages.create.await_count == 2
    fake_tool.assert_awaited_once()


async def test_followup_failure_returns_generic_error(agent, context):
    agent.client.messages.create.side_effect = [
        _message([_tool_use_block("call_1", "list_expenses", {})]),
        AgentTimeoutError("boom"),
    ]
    fake_tool = AsyncMock(return_value=ToolResult(success=True, response_text="{}"))

    with patch("piazza.agent.agent.execute_tool", fake_tool):
        result = await agent._execute(context)

    assert result == GENERIC_ERROR_RESPONSE


@pytest.mark.parametrize(
    "sdk_exc, expected",
    [
        (
            anthropic.APITimeoutError(request=SimpleNamespace()),
            AgentTimeoutError,
        ),
        (
            anthropic.APIConnectionError(request=SimpleNamespace()),
            AgentUnavailableError,
        ),
        (
            anthropic.APIError(
                "boom", request=SimpleNamespace(), body=None,
            ),
            AgentUnavailableError,
        ),
    ],
)
async def test_call_maps_sdk_errors(agent, sdk_exc, expected):
    agent.client.messages.create.side_effect = sdk_exc

    with pytest.raises(expected):
        await agent._call(messages=[{"role": "user", "content": "x"}])
