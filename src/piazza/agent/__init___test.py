"""Tests for the provider dispatcher in piazza.agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import piazza.agent as agent_module
from piazza.agent import ClaudeAgent, FireworksAgent, get_agent


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Clear cached singletons so settings overrides take effect each test."""
    agent_module._claude = None
    agent_module._fireworks = None
    yield
    agent_module._claude = None
    agent_module._fireworks = None


def test_get_agent_returns_claude_when_provider_claude():
    with patch.object(agent_module.settings, "llm_provider", "claude"):
        assert isinstance(get_agent(), ClaudeAgent)


def test_get_agent_returns_fireworks_when_provider_fireworks():
    with patch.object(agent_module.settings, "llm_provider", "fireworks"):
        assert isinstance(get_agent(), FireworksAgent)


def test_get_agent_raises_on_unknown_provider():
    with patch.object(agent_module.settings, "llm_provider", "bogus"):
        with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
            get_agent()


def test_get_agent_returns_singleton():
    with patch.object(agent_module.settings, "llm_provider", "claude"):
        first = get_agent()
        second = get_agent()
        assert first is second
