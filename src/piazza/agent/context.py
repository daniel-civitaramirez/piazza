"""Agent context building — assembles user content with conversation history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

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
    reply_to_id: str | None = None
    recent_messages: list[MessageLog] = field(default_factory=list)
    reply_context: MessageLog | None = None


def build_user_content(context: AgentContext) -> str:
    """Build the user message content with context tags for the agent LLM."""
    parts: list[str] = []

    parts.append(f"<sender>{context.sender_name}</sender>")
    if context.member_names:
        parts.append(
            f"<group_members>{', '.join(context.member_names)}</group_members>"
        )

    if context.recent_messages:
        lines = []
        for msg in context.recent_messages:
            if msg.role == "user" and msg.member:
                name = msg.member.display_name
            elif msg.role == "assistant":
                name = "Piazza"
            else:
                name = "Unknown"
            lines.append(f"[{name}]: {msg.content}")
        parts.append(
            "<recent_context>\n" + "\n".join(lines) + "\n</recent_context>"
        )

    if context.reply_context:
        parts.append(
            f"<replying_to>\n{context.reply_context.content}\n</replying_to>"
        )

    parts.append(f"<user_message>{context.text}</user_message>")

    return "\n".join(parts)
