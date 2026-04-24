"""Parse raw Evolution API webhook payloads into normalized Message objects."""

from __future__ import annotations

import structlog
from pydantic import ValidationError

from piazza.messaging.whatsapp.schemas import (
    Message,
    WebhookPayload,
)

logger = structlog.get_logger()


# --- Private helpers ---


def _extract_text(data) -> str | None:
    """Extract text content from webhook data, handling both message shapes."""
    if data.message is None:
        return None

    # Shape 1: extendedTextMessage (replies, mentions)
    if data.message.extended_text_message and data.message.extended_text_message.text:
        return data.message.extended_text_message.text

    # Shape 2: simple conversation
    if data.message.conversation:
        return data.message.conversation

    return None


# --- Public API ---


def extract_sender_info(
    raw: dict, bot_jid: str
) -> tuple[str, str, str] | None:
    """Extract lightweight sender info from any group message.

    Returns (group_jid, sender_jid, push_name) for display name learning,
    or None if the message should be skipped (not a group message, from
    the bot itself, or missing data).

    Much lighter than parse_webhook() — no mention gate, no text extraction.
    """
    try:
        payload = WebhookPayload(**raw)
    except ValidationError:
        return None

    data = payload.data
    key = data.key

    # Skip bot's own messages
    if key.from_me:
        return None

    # Only group messages
    if not key.remote_jid.endswith("@g.us"):
        return None

    # Need a push_name to be useful
    if not data.push_name:
        return None

    # Use participantAlt (phone JID) when participant is LID format
    sender_jid = key.participant_alt or key.participant or key.remote_jid
    # Don't learn from the bot's own JID
    if sender_jid == bot_jid:
        return None

    return key.remote_jid, sender_jid, data.push_name


def parse_webhook(raw: dict, bot_jid: str) -> Message | None:
    """Convert a raw Evolution API webhook dict into a Message, or None if irrelevant.

    Returns None when:
    - Payload fails validation
    - Message is from the bot itself (fromMe=True)
    - Not a group message (remoteJid must end with @g.us)
    - No text content found
    - Bot was neither @mentioned nor replied to
    """
    try:
        payload = WebhookPayload(**raw)
    except ValidationError as e:
        logger.warning("webhook_parse_error", raw_keys=list(raw.keys()), error=str(e))
        return None

    data = payload.data
    key = data.key

    # Reject bot's own messages
    if key.from_me:
        logger.debug("parse_skip_from_me")
        return None

    # Only process group messages
    if not key.remote_jid.endswith("@g.us"):
        logger.debug("parse_skip_not_group", remote_jid=key.remote_jid)
        return None

    # Extract text from either message shape
    text = _extract_text(data)
    logger.debug(
        "parse_text_extraction",
        has_message=data.message is not None,
        has_extended=bool(data.message and data.message.extended_text_message),
        has_conversation=bool(data.message and data.message.conversation),
        text_found=text is not None,
    )
    if not text:
        logger.debug("parse_skip_no_text")
        return None

    # Check mention / reply-to-bot
    # contextInfo can be top-level on data OR inside extendedTextMessage
    mentioned_jids: list[str] = []
    reply_to_id: str | None = None
    ctx = None

    if data.message and data.message.extended_text_message:
        ctx = data.message.extended_text_message.context_info

    if ctx is None:
        ctx = data.context_info

    if ctx:
        mentioned_jids = ctx.mentioned_jid
        reply_to_id = ctx.stanza_id

    logger.debug(
        "parse_context_info",
        ctx_source="extended" if (data.message and data.message.extended_text_message and data.message.extended_text_message.context_info) else "top_level",
        mentioned_jids=mentioned_jids,
        ctx_participant=ctx.participant if ctx else None,
    )

    # Bot JID may be phone format (33688511175@s.whatsapp.net) while mentions
    # use LID format (75192697139363@lid) — extract phone number for comparison
    bot_phone = bot_jid.split("@")[0]
    is_mention = bot_jid in mentioned_jids or any(
        jid.split("@")[0] == bot_phone for jid in mentioned_jids
    )
    is_reply_to_bot = (
        reply_to_id is not None
        and ctx is not None
        and ctx.participant is not None
        and (ctx.participant == bot_jid or ctx.participant.split("@")[0] == bot_phone)
    )

    logger.debug(
        "parse_mention_check",
        bot_jid=bot_jid,
        mentioned_jids=mentioned_jids,
        is_mention=is_mention,
        is_reply_to_bot=is_reply_to_bot,
        text_preview=text[:50] if text else None,
    )

    if not is_mention and not is_reply_to_bot:
        logger.debug("parse_skip_no_mention")
        return None

    # Use participantAlt (phone JID) when participant is LID format
    sender_jid = key.participant_alt or key.participant or key.remote_jid

    return Message(
        sender_jid=sender_jid,
        sender_name=data.push_name or sender_jid,
        group_jid=key.remote_jid,
        text=text,
        message_id=key.id or None,
        mentioned_jids=mentioned_jids,
        reply_to_message_id=reply_to_id,
    )
