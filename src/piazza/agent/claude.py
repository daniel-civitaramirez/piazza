"""Claude LLM agent using the Anthropic SDK."""

from __future__ import annotations

import anthropic
import structlog

from piazza.agent.base import (
    AgentTimeoutError,
    AgentUnavailableError,
    BaseAgent,
    LLMResponse,
    ToolCall,
    ToolResult,
)

logger = structlog.get_logger()


def _parse_response(msg: anthropic.types.Message) -> LLMResponse:
    """Parse Anthropic Message into LLMResponse."""
    text_parts = [b.text for b in msg.content if b.type == "text"]
    tool_calls = [
        ToolCall(id=b.id, name=b.name, arguments=b.input)
        for b in msg.content
        if b.type == "tool_use"
    ]
    raw = [b.model_dump() for b in msg.content]
    return LLMResponse(
        text=text_parts[0] if text_parts else None,
        tool_calls=tool_calls,
        raw=raw,
    )


class ClaudeAgent(BaseAgent):
    """Agent backed by the Claude API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout: float = 15.0,
    ):
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout,
        )
        self.model = model

    async def _generate(
        self,
        system: str,
        user_content: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }
        if tools:
            kwargs["tools"] = tools  # Already in Anthropic format

        try:
            msg = await self.client.messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            logger.warning("claude_agent_timeout")
            raise AgentTimeoutError("Claude API timed out") from exc
        except anthropic.APIConnectionError as exc:
            logger.warning("claude_agent_unavailable")
            raise AgentUnavailableError(
                "Cannot connect to Claude API"
            ) from exc
        except anthropic.APIError as exc:
            logger.warning("claude_agent_api_error", error=str(exc))
            raise AgentUnavailableError(
                f"Claude API error: {exc}"
            ) from exc

        return _parse_response(msg)

    async def _generate_followup(
        self,
        system: str,
        user_content: str,
        prior_response: LLMResponse,
        tool_results: list[ToolResult],
    ) -> LLMResponse:
        messages = [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": prior_response.raw},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                    }
                    for r in tool_results
                ],
            },
        ]

        try:
            msg = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=messages,
            )
        except anthropic.APIError as exc:
            logger.warning("claude_agent_followup_error", error=str(exc))
            raise AgentUnavailableError(
                f"Claude API error on followup: {exc}"
            ) from exc

        return _parse_response(msg)
