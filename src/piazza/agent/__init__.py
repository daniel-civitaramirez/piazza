"""Agent module — LLM agents with tool use for message processing."""

from __future__ import annotations

from piazza.agent.claude import ClaudeAgent
from piazza.agent.opensource import OpenSourceAgent
from piazza.config.settings import settings

_opensource: OpenSourceAgent | None = None
_claude: ClaudeAgent | None = None


def get_opensource_agent() -> OpenSourceAgent:
    """Get or create the shared OpenSourceAgent singleton."""
    global _opensource
    if _opensource is None:
        _opensource = OpenSourceAgent(
            url=settings.ollama_url,
            model="qwen3.5:4b",
            timeout=10.0,
        )
    return _opensource


def get_claude_agent() -> ClaudeAgent:
    """Get or create the shared ClaudeAgent singleton."""
    global _claude
    if _claude is None:
        _claude = ClaudeAgent(
            api_key=settings.anthropic_api_key,
            model="claude-haiku-4-5-20251001",
        )
    return _claude


__all__ = ["ClaudeAgent", "OpenSourceAgent", "get_claude_agent", "get_opensource_agent"]
