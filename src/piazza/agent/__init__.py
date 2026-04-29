"""Agent module — LLM agent with tool use for message processing."""

from __future__ import annotations

from piazza.agent.agent import (
    Agent,
    AgentTimeoutError,
    AgentUnavailableError,
)
from piazza.agent.context import AgentContext

_agent: Agent | None = None


def get_agent() -> Agent:
    """Get or create the shared Agent singleton."""
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent


__all__ = [
    "Agent",
    "AgentContext",
    "AgentTimeoutError",
    "AgentUnavailableError",
    "get_agent",
]
