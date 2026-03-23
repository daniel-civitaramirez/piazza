"""Pydantic models for WhatsApp message schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """Normalized internal message schema.

    This is NOT the raw Evolution API webhook payload.
    The webhook parser (Phase 5) converts raw payloads into this model.
    """

    sender_jid: str
    sender_name: str
    group_jid: str
    text: str
    message_id: str | None = None
    mentioned_jids: list[str] = []
    reply_to_message_id: str | None = None


# --- Evolution API webhook models ---


class WebhookKey(BaseModel):
    """The `key` object inside a webhook message event."""

    model_config = ConfigDict(populate_by_name=True)

    remote_jid: str = Field(alias="remoteJid")
    from_me: bool = Field(False, alias="fromMe")
    id: str = ""
    participant: str | None = None


class ContextInfo(BaseModel):
    """Optional reply/mention context attached to a message."""

    model_config = ConfigDict(populate_by_name=True)

    mentioned_jid: list[str] = Field(default=[], alias="mentionedJid")
    stanza_id: str | None = Field(None, alias="stanzaId")
    participant: str | None = None


class ExtendedTextMessage(BaseModel):
    """Extended text message payload (used when replying or mentioning)."""

    model_config = ConfigDict(populate_by_name=True)

    text: str = ""
    context_info: ContextInfo | None = Field(None, alias="contextInfo")


class WebhookMessageContent(BaseModel):
    """The `message` object which can contain different message shapes."""

    model_config = ConfigDict(populate_by_name=True)

    conversation: str | None = None
    extended_text_message: ExtendedTextMessage | None = Field(
        None, alias="extendedTextMessage"
    )


class WebhookData(BaseModel):
    """The `data` object inside a webhook payload."""

    model_config = ConfigDict(populate_by_name=True)

    key: WebhookKey
    push_name: str = Field("", alias="pushName")
    message: WebhookMessageContent | None = None
    message_timestamp: int | None = Field(None, alias="messageTimestamp")


class WebhookPayload(BaseModel):
    """Top-level Evolution API webhook payload."""

    event: str
    instance: str = ""
    data: WebhookData


# --- Evolution API group event models ---


class GroupParticipant(BaseModel):
    """A participant entry in a groups.upsert event."""

    id: str
    admin: str | None = None


class GroupUpsertData(BaseModel):
    """The data payload for a groups.upsert event.

    Fired when the bot is added to a WhatsApp group.
    Contains the group JID, subject (name), and full participant list.
    Note: participant display names are NOT available from this event.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str  # group JID e.g. "120363001@g.us"
    subject: str | None = None
    participants: list[GroupParticipant] = []


class ParticipantData(BaseModel):
    """Enriched participant data from group-participants.update events."""

    model_config = ConfigDict(populate_by_name=True)

    jid: str
    push_name: str | None = Field(None, alias="pushName")


class GroupParticipantsUpdateData(BaseModel):
    """The data payload for a group-participants.update event.

    Fired when a member joins, leaves, is promoted, or demoted.
    """

    model_config = ConfigDict(populate_by_name=True)

    group_jid: str = Field(alias="groupJid")
    action: str  # "add", "remove", "promote", "demote"
    participants: list[str] = []
    participants_data: list[ParticipantData] = Field(
        default=[], alias="participantsData"
    )
