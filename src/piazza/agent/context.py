"""Agent context building — assembles user content with conversation history."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.models.message_log import MessageLog


@dataclass
class AgentContext:
    """All context needed to run the agent for a single message."""

    text: str
    sender_name: str
    member_names: list[str]
    session: AsyncSession
    group_id: uuid.UUID
    member_id: uuid.UUID
    tz: str = "UTC"
    reply_to_id: str | None = None
    recent_messages: list[MessageLog] = field(default_factory=list)
    reply_context: MessageLog | None = None


def _speaker_name(msg: MessageLog) -> str:
    if msg.role == "assistant":
        return "Piazza"
    if msg.role == "user" and msg.member:
        return msg.member.display_name  # type: ignore[no-any-return]
    return "Unknown"


def _from_log(msg: MessageLog) -> tuple[str, str]:
    return _speaker_name(msg), msg.content  # type: ignore[return-value]


def _inline_tag(name: str, value: str) -> str:
    return f"<{name}>{value}</{name}>"


def _authored_block(name: str, entries: Iterable[tuple[str, str]]) -> str:
    lines = [f"[{author}]: {text}" for author, text in entries]
    return f"<{name}>\n" + "\n".join(lines) + f"\n</{name}>"


def build_user_content(context: AgentContext) -> str:
    """Build the user message content with context tags for the agent LLM."""
    now = datetime.now(ZoneInfo(context.tz))

    parts: list[str] = [
        _inline_tag("current_time", now.strftime("%A, %-d %B %Y %H:%M:%S")),
        _inline_tag("message_sender", context.sender_name),
    ]
    if context.member_names:
        parts.append(_inline_tag("group_members", ", ".join(context.member_names)))

    if context.recent_messages:
        parts.append(
            _authored_block("recent_context", (_from_log(m) for m in context.recent_messages))
        )

    if context.reply_context:
        parts.append(
            _authored_block("user_replying_to_message", [_from_log(context.reply_context)])
        )

    parts.append(
        _authored_block("user_message", [(context.sender_name, context.text)])
    )

    return "\n".join(parts)
