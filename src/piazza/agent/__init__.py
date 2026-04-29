"""Agent module — LLM agents with tool use for message processing."""

from __future__ import annotations

from piazza.agent.base import BaseAgent
from piazza.agent.claude import ClaudeAgent
from piazza.agent.fireworks import FireworksAgent
from piazza.config.settings import settings

_claude: ClaudeAgent | None = None
_fireworks: FireworksAgent | None = None


def get_claude_agent() -> ClaudeAgent:
    """Get or create the shared ClaudeAgent singleton."""
    global _claude
    if _claude is None:
        _claude = ClaudeAgent(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            timeout=settings.llm_timeout,
            max_tokens=settings.claude_max_tokens,
            context_limit=settings.conversation_context_limit,
        )
    return _claude


def get_fireworks_agent() -> FireworksAgent:
    """Get or create the shared FireworksAgent singleton."""
    global _fireworks
    if _fireworks is None:
        _fireworks = FireworksAgent(
            api_key=settings.fireworks_api_key,
            model=settings.fireworks_model,
            base_url=settings.fireworks_base_url,
            timeout=settings.llm_timeout,
            temperature=settings.llm_temperature,
            context_limit=settings.conversation_context_limit,
        )
    return _fireworks


def get_agent() -> BaseAgent:
    """Return the configured agent based on settings.llm_provider."""
    if settings.llm_provider == "claude":
        return get_claude_agent()
    if settings.llm_provider == "fireworks":
        return get_fireworks_agent()
    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")


__all__ = [
    "BaseAgent",
    "ClaudeAgent",
    "FireworksAgent",
    "get_agent",
    "get_claude_agent",
    "get_fireworks_agent",
]
