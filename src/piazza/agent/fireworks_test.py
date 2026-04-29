"""Tests for FireworksAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from piazza.agent.base import AgentTimeoutError, AgentUnavailableError
from piazza.agent.fireworks import FireworksAgent, _format_tools


def _make_agent() -> FireworksAgent:
    return FireworksAgent(
        api_key="fw_test_key",
        model="accounts/fireworks/models/qwen3-30b-a3b-instruct-2507",
        base_url="https://api.fireworks.ai/inference/v1",
        timeout=5.0,
        temperature=0.0,
        context_limit=10,
    )


def _mock_async_client(
    *, json_response: dict | None = None, side_effect: Exception | None = None,
    status_code: int = 200,
) -> tuple[MagicMock, MagicMock]:
    """Build a context-manager-aware mock for httpx.AsyncClient."""
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=json_response or {})

    if status_code >= 400:
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "error", request=MagicMock(), response=response,
            )
        )
    else:
        response.raise_for_status = MagicMock(return_value=None)

    instance = MagicMock()
    if side_effect:
        instance.post = AsyncMock(side_effect=side_effect)
    else:
        instance.post = AsyncMock(return_value=response)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=instance)
    client.__aexit__ = AsyncMock(return_value=None)
    return client, instance


async def test_post_sends_bearer_authorization_header():
    agent = _make_agent()
    client, instance = _mock_async_client(
        json_response={"choices": [{"message": {"content": "hi", "tool_calls": []}}]},
    )

    with patch("piazza.agent.fireworks.httpx.AsyncClient", return_value=client):
        body = await agent._post({"model": agent.model, "messages": []})

    assert body == {"choices": [{"message": {"content": "hi", "tool_calls": []}}]}
    instance.post.assert_called_once()
    call_kwargs = instance.post.call_args.kwargs
    assert call_kwargs["headers"] == {"Authorization": "Bearer fw_test_key"}
    assert instance.post.call_args.args[0] == (
        "https://api.fireworks.ai/inference/v1/chat/completions"
    )


async def test_post_timeout_raises_agent_timeout_error():
    agent = _make_agent()
    client, _ = _mock_async_client(side_effect=httpx.TimeoutException("timed out"))

    with patch("piazza.agent.fireworks.httpx.AsyncClient", return_value=client):
        with pytest.raises(AgentTimeoutError):
            await agent._post({"model": agent.model, "messages": []})


async def test_post_connect_error_raises_agent_unavailable():
    agent = _make_agent()
    client, _ = _mock_async_client(side_effect=httpx.ConnectError("refused"))

    with patch("piazza.agent.fireworks.httpx.AsyncClient", return_value=client):
        with pytest.raises(AgentUnavailableError):
            await agent._post({"model": agent.model, "messages": []})


async def test_post_401_raises_agent_unavailable():
    agent = _make_agent()
    client, _ = _mock_async_client(json_response={"error": "unauthorized"}, status_code=401)

    with patch("piazza.agent.fireworks.httpx.AsyncClient", return_value=client):
        with pytest.raises(AgentUnavailableError):
            await agent._post({"model": agent.model, "messages": []})


async def test_post_500_raises_agent_unavailable():
    agent = _make_agent()
    client, _ = _mock_async_client(json_response={"error": "boom"}, status_code=500)

    with patch("piazza.agent.fireworks.httpx.AsyncClient", return_value=client):
        with pytest.raises(AgentUnavailableError):
            await agent._post({"model": agent.model, "messages": []})


async def test_post_sends_payload_as_json():
    agent = _make_agent()
    client, instance = _mock_async_client(
        json_response={"choices": [{"message": {"content": "ok", "tool_calls": []}}]},
    )

    with patch("piazza.agent.fireworks.httpx.AsyncClient", return_value=client):
        await agent._post(
            {"model": agent.model, "messages": [{"role": "user", "content": "hi"}]},
        )

    sent_json = instance.post.call_args.kwargs["json"]
    assert sent_json["model"] == agent.model
    assert sent_json["messages"][0]["content"] == "hi"


def test_format_tools_converts_anthropic_to_openai():
    anthropic_tools = [
        {
            "name": "add_expense",
            "description": "Record an expense",
            "input_schema": {
                "type": "object",
                "properties": {"amount": {"type": "number"}},
                "required": ["amount"],
            },
        },
    ]
    assert _format_tools(anthropic_tools) == [
        {
            "type": "function",
            "function": {
                "name": "add_expense",
                "description": "Record an expense",
                "parameters": {
                    "type": "object",
                    "properties": {"amount": {"type": "number"}},
                    "required": ["amount"],
                },
            },
        },
    ]


def test_format_tools_handles_missing_description():
    anthropic_tools = [
        {"name": "ping", "input_schema": {"type": "object", "properties": {}}},
    ]
    result = _format_tools(anthropic_tools)
    assert result[0]["function"]["description"] == ""
    assert result[0]["function"]["name"] == "ping"


def test_url_strips_trailing_slash_from_base_url():
    agent = FireworksAgent(
        api_key="k",
        model="m",
        base_url="https://api.fireworks.ai/inference/v1/",
        timeout=5.0,
        temperature=0.0,
        context_limit=10,
    )
    assert agent.url == "https://api.fireworks.ai/inference/v1/chat/completions"
