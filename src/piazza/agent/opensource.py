"""Open-source LLM agent using Ollama's OpenAI-compatible API."""

from __future__ import annotations

import json

import httpx
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


def _format_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-format tool defs to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _parse_response(body: dict) -> LLMResponse:
    """Parse OpenAI-format chat completion into LLMResponse."""
    choice = body["choices"][0]["message"]
    text = choice.get("content")
    raw_calls = choice.get("tool_calls", [])
    tool_calls = []
    for tc in raw_calls:
        args = tc["function"]["arguments"]
        if isinstance(args, str):
            args = json.loads(args)
        tool_calls.append(ToolCall(
            id=tc["id"],
            name=tc["function"]["name"],
            arguments=args,
        ))
    return LLMResponse(text=text, tool_calls=tool_calls, raw=raw_calls)


class OpenSourceAgent(BaseAgent):
    """Agent backed by a local Ollama instance."""

    def __init__(
        self, url: str, model: str, timeout: float, temperature: float, context_limit: int,
    ):
        super().__init__(context_limit=context_limit)
        self.url = f"{url.rstrip('/')}/v1/chat/completions"
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    async def _generate(
        self,
        system: str,
        user_content: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "think": False,
        }
        if tools:
            payload["tools"] = _format_tools(tools)

        body = await self._post(payload)
        return _parse_response(body)

    async def _generate_followup(
        self,
        system: str,
        user_content: str,
        prior_response: LLMResponse,
        tool_results: list[ToolResult],
    ) -> LLMResponse:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
            {"role": "assistant", "tool_calls": prior_response.raw},
        ]
        for r in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": r.tool_call_id,
                "content": r.content,
            })

        body = await self._post({
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "think": False,
        })
        return _parse_response(body)

    async def _post(self, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.url, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException as exc:
            logger.warning("ollama_agent_timeout", timeout=self.timeout)
            raise AgentTimeoutError(
                f"Ollama timed out after {self.timeout}s"
            ) from exc
        except httpx.ConnectError as exc:
            logger.warning("ollama_agent_unavailable", url=self.url)
            raise AgentUnavailableError("Cannot connect to Ollama") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "ollama_agent_http_error", status=exc.response.status_code,
            )
            raise AgentUnavailableError(
                f"Ollama returned HTTP {exc.response.status_code}"
            ) from exc
