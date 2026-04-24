"""Base types and shared agent logic."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from piazza.agent.context import AgentContext, build_user_content
from piazza.agent.prompts import AGENT_SYSTEM_PROMPT
from piazza.db.repositories import message_log as message_log_repo
from piazza.tools.registry import AGENT_TOOLS, execute_tool

logger = structlog.get_logger()

UNKNOWN_FALLBACK = (
    "I'm not sure how to help with that. "
    "I can help with *expenses*, *reminders*, *notes*, and *itinerary* — "
    "just ask!"
)


# --- Data types ---


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Result of executing a tool call, sent back to the LLM."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class LLMResponse:
    """Normalized response from any LLM backend."""

    text: str | None
    tool_calls: list[ToolCall]
    raw: Any = field(default=None, repr=False)


# --- Errors ---


class AgentTimeoutError(Exception):
    """Raised when a backend times out."""


class AgentUnavailableError(Exception):
    """Raised when a backend is unreachable."""


# --- Base agent ---


class BaseAgent(ABC):
    """Shared agent logic: context hydration, tool loop, LLM calls."""

    def __init__(self, context_limit: int):
        self.context_limit = context_limit

    async def run(self, context: AgentContext) -> str:
        """Hydrate context and execute the agent loop."""
        await self._hydrate_context(context)
        return await self._execute(context)

    # --- Abstract methods (each backend implements its own) ---

    @abstractmethod
    async def _generate(
        self,
        system: str,
        user_content: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def _generate_followup(
        self,
        system: str,
        user_content: str,
        prior_response: LLMResponse,
        tool_results: list[ToolResult],
    ) -> LLMResponse: ...

    # --- Shared execution ---

    async def _execute(self, context: AgentContext) -> str:
        """Shared agent loop: LLM → tools → followup."""
        start = time.monotonic()
        user_content = build_user_content(context)

        # 1. First LLM call with tools
        response = await self._generate(
            AGENT_SYSTEM_PROMPT, user_content, AGENT_TOOLS,
        )

        # 2. No tool calls → conversational response
        if not response.tool_calls:
            self._log_response(start, 0)
            return response.text or UNKNOWN_FALLBACK

        # 3. Execute tools
        tool_results: list[ToolResult] = []
        tools_called: list[str] = []
        for tc in response.tool_calls:
            result = await execute_tool(
                tc.name, tc.arguments,
                context.session, context.group_id, context.member_id,
            )
            tool_results.append(ToolResult(
                tool_call_id=tc.id,
                content=result.response_text,
                is_error=not result.success,
            ))
            tools_called.append(tc.name)

        # 4. Send results back for final response
        try:
            final = await self._generate_followup(
                AGENT_SYSTEM_PROMPT, user_content, response, tool_results,
            )
            final_text = final.text
        except (AgentTimeoutError, AgentUnavailableError):
            logger.warning("agent_followup_failed")
            final_text = None

        self._log_response(start, tools_called)

        if final_text:
            return final_text

        # Followup failed — try a plain formatting call with results embedded
        results_text = "\n\n".join(r.content for r in tool_results if not r.is_error)
        if results_text:
            try:
                formatting_content = f"{user_content}\n\n[Tool results: {results_text}]"
                fmt = await self._generate(AGENT_SYSTEM_PROMPT, formatting_content)
                if fmt.text:
                    return fmt.text
            except (AgentTimeoutError, AgentUnavailableError):
                pass

        return UNKNOWN_FALLBACK

    async def _hydrate_context(self, context: AgentContext) -> None:
        """Fetch conversation history and reply context."""
        try:
            context.recent_messages = await message_log_repo.get_recent(
                context.session, context.group_id, limit=self.context_limit,
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

    def _log_response(self, start: float, tools_called: int | list) -> None:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(
            "agent_response",
            agent=type(self).__name__,
            tools_called=tools_called,
            elapsed_ms=elapsed,
        )
