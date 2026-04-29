"""Agent context building — assembles user content with conversation history."""

from __future__ import annotations

import uuid
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
        return msg.member.display_name
    return "Unknown"


def build_user_content(context: AgentContext) -> str:
    """Build the user message content with context tags for the agent LLM."""
    parts: list[str] = []

    now = datetime.now(ZoneInfo(context.tz))
    parts.append(
        f"<current_time>{now.strftime('%A, %-d %B %Y %H:%M:%S')}</current_time>"
    )

    parts.append(f"<sender>{context.sender_name}</sender>")
    if context.member_names:
        parts.append(
            f"<group_members>{', '.join(context.member_names)}</group_members>"
        )

    if context.recent_messages:
        lines = [
            f"[{_speaker_name(msg)}]: {msg.content}" for msg in context.recent_messages
        ]
        parts.append(
            "<recent_context>\n" + "\n".join(lines) + "\n</recent_context>"
        )

    if context.reply_context:
        name = _speaker_name(context.reply_context)
        parts.append(
            "<replying_to_message>\n"
            f"[{name}]: {context.reply_context.content}\n"
            "</replying_to_message>"
        )

    parts.append(
        "<user_message>\n"
        f"[{context.sender_name}]: {context.text}\n"
        "</user_message>"
    )

    return "\n".join(parts)
