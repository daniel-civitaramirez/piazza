"""Tests for the Agent factory in piazza.agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import piazza.agent as agent_module
from piazza.agent import Agent, get_agent
from piazza.agent.agent import FIREWORKS_BASE_URL
from piazza.config.settings import settings


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Clear cached singleton so settings overrides take effect each test."""
    agent_module._agent = None
    yield
    agent_module._agent = None


def test_get_agent_uses_claude_when_provider_claude():
    with patch.object(settings, "llm_provider", "claude"):
        agent = get_agent()
    assert isinstance(agent, Agent)
    assert agent.model == settings.claude_model
    assert "fireworks" not in str(agent.client.base_url)


def test_get_agent_uses_fireworks_when_provider_fireworks():
    with patch.object(settings, "llm_provider", "fireworks"):
        agent = get_agent()
    assert isinstance(agent, Agent)
    assert agent.model == settings.fireworks_model
    assert str(agent.client.base_url).rstrip("/") == FIREWORKS_BASE_URL


def test_get_agent_raises_on_unknown_provider():
    # Bypass pydantic Literal validation by patching the live settings.
    with patch.object(settings, "llm_provider", "bogus"):
        with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
            get_agent()


def test_get_agent_returns_singleton():
    with patch.object(settings, "llm_provider", "claude"):
        first = get_agent()
        second = get_agent()
    assert first is second
