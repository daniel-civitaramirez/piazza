"""LLM agent: Claude or Fireworks via the Anthropic SDK + tool loop."""

from __future__ import annotations

import time
from typing import Any, cast

import anthropic
import structlog

from piazza.agent.context import AgentContext, build_user_content
from piazza.agent.prompts import AGENT_SYSTEM_PROMPT
from piazza.config.settings import settings
from piazza.db.repositories import message_log as message_log_repo
from piazza.tools.registry import AGENT_TOOLS, execute_tool

logger = structlog.get_logger()

UNKNOWN_FALLBACK = (
    "I'm not sure how to help with that. "
    "I can help with *expenses*, *reminders*, *notes*, and *itinerary* — "
    "just ask!"
)

# Fireworks exposes an Anthropic-compatible endpoint here (no /v1 suffix).
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference"


class AgentTimeoutError(Exception):
    """Raised when an LLM call times out."""


class AgentUnavailableError(Exception):
    """Raised when the LLM backend is unreachable or returns an error."""


class Agent:
    """LLM agent supporting Claude or Fireworks via the Anthropic SDK."""

    def __init__(self) -> None:
        if settings.llm_provider == "claude":
            self.client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=settings.llm_timeout,
            )
            self.model = settings.claude_model
        elif settings.llm_provider == "fireworks":
            self.client = anthropic.AsyncAnthropic(
                api_key=settings.fireworks_api_key,
                base_url=FIREWORKS_BASE_URL,
                timeout=settings.llm_timeout,
            )
            self.model = settings.fireworks_model
        else:
            raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")

    async def run(self, context: AgentContext) -> str:
        """Hydrate context and execute the agent loop."""
        await self._hydrate(context)
        return await self._execute(context)

    async def _hydrate(self, context: AgentContext) -> None:
        try:
            context.recent_messages = await message_log_repo.get_recent(
                context.session,
                context.group_id,
                limit=settings.conversation_context_limit,
            )
        except Exception:
            logger.exception("failed_to_fetch_recent_messages")

        if context.reply_to_id:
            try:
                context.reply_context = (
                    await message_log_repo.get_by_wa_message_id(
                        context.session, context.reply_to_id,
                    )
                )
            except Exception:
                logger.exception("failed_to_fetch_reply_context")

    async def _execute(self, context: AgentContext) -> str:
        start = time.monotonic()
        user_content = build_user_content(context)
        messages: list[dict] = [{"role": "user", "content": user_content}]

        response = await self._call(messages, tools=AGENT_TOOLS)
        text = next(
            (b.text for b in response.content if b.type == "text"), None,
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        if not tool_uses:
            self._log(start, [])
            return text or UNKNOWN_FALLBACK

        tool_results: list[dict] = []
        tools_called: list[str] = []
        for tu in tool_uses:
            result = await execute_tool(
                tu.name, tu.input,
                context.session, context.group_id, context.member_id,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result.response_text,
            })
            tools_called.append(tu.name)

        messages.extend([
            {
                "role": "assistant",
                "content": [b.model_dump() for b in response.content],
            },
            {"role": "user", "content": tool_results},
        ])

        try:
            final = await self._call(messages)
            final_text = next(
                (b.text for b in final.content if b.type == "text"), None,
            )
        except (AgentTimeoutError, AgentUnavailableError):
            logger.warning("agent_followup_failed")
            final_text = None

        self._log(start, tools_called)
        return final_text or UNKNOWN_FALLBACK

    async def _call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> anthropic.types.Message:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": settings.llm_max_tokens,
            "system": AGENT_SYSTEM_PROMPT,
            "messages": messages,
            "temperature": settings.llm_temperature,
            "thinking": {"type": "disabled"},
        }
        if tools:
            kwargs["tools"] = tools

        try:
            msg = await self.client.messages.create(**kwargs)
            return cast(anthropic.types.Message, msg)
        except anthropic.APITimeoutError as exc:
            logger.warning("llm_timeout", provider=settings.llm_provider)
            raise AgentTimeoutError("LLM timed out") from exc
        except anthropic.APIConnectionError as exc:
            logger.warning("llm_unavailable", provider=settings.llm_provider)
            raise AgentUnavailableError("Cannot connect to LLM") from exc
        except anthropic.APIError as exc:
            logger.warning(
                "llm_api_error",
                provider=settings.llm_provider,
                error=str(exc),
            )
            raise AgentUnavailableError(f"LLM error: {exc}") from exc

    def _log(self, start: float, tools_called: list[str]) -> None:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(
            "agent_response",
            provider=settings.llm_provider,
            model=self.model,
            tools_called=tools_called,
            elapsed_ms=elapsed,
        )
