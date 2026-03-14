"""Tests for piazza.whatsapp.parser — webhook payload parsing."""

from __future__ import annotations

from piazza.messaging.whatsapp.parser import parse_webhook

BOT_JID = "5599999999999@s.whatsapp.net"
GROUP_JID = "120363001@g.us"
SENDER_JID = "5511111111111@s.whatsapp.net"


def _make_payload(
    *,
    event: str = "messages.upsert",
    remote_jid: str = GROUP_JID,
    from_me: bool = False,
    participant: str | None = SENDER_JID,
    push_name: str = "Alice",
    conversation: str | None = None,
    extended_text: str | None = None,
    mentioned_jids: list[str] | None = None,
    stanza_id: str | None = None,
    ctx_participant: str | None = None,
    timestamp: int | None = 1700000000,
) -> dict:
    """Build a minimal Evolution API webhook payload dict."""
    message: dict = {}

    if conversation is not None:
        message["conversation"] = conversation

    if extended_text is not None:
        ext: dict = {"text": extended_text}
        ctx_info: dict = {}
        if mentioned_jids is not None:
            ctx_info["mentionedJid"] = mentioned_jids
        if stanza_id is not None:
            ctx_info["stanzaId"] = stanza_id
        if ctx_participant is not None:
            ctx_info["participant"] = ctx_participant
        if ctx_info:
            ext["contextInfo"] = ctx_info
        message["extendedTextMessage"] = ext

    return {
        "event": event,
        "instance": "piazza-main",
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "id": "ABC123",
                "participant": participant,
            },
            "pushName": push_name,
            "message": message if message else None,
            "messageTimestamp": timestamp,
        },
    }


class TestParseWebhookValid:
    """Test cases where parse_webhook should return a Message."""

    def test_mention_via_extended_text(self):
        raw = _make_payload(
            extended_text="@bot what's up?",
            mentioned_jids=[BOT_JID],
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.text == "@bot what's up?"
        assert msg.group_jid == GROUP_JID
        assert msg.sender_jid == SENDER_JID
        assert msg.sender_name == "Alice"
        assert msg.is_mention is True
        assert BOT_JID in msg.mentioned_jids

    def test_reply_to_bot(self):
        raw = _make_payload(
            extended_text="yes I agree",
            stanza_id="prev-msg-id-123",
            ctx_participant=BOT_JID,
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.text == "yes I agree"
        assert msg.reply_to_message_id == "prev-msg-id-123"
        assert msg.is_mention is False

    def test_mention_and_reply(self):
        raw = _make_payload(
            extended_text="@bot replying here",
            mentioned_jids=[BOT_JID],
            stanza_id="prev-msg-id-456",
            ctx_participant=BOT_JID,
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.is_mention is True
        assert msg.reply_to_message_id == "prev-msg-id-456"

    def test_message_id_extracted(self):
        raw = _make_payload(
            extended_text="@bot hello",
            mentioned_jids=[BOT_JID],
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.message_id == "ABC123"

    def test_timestamp_parsed(self):
        raw = _make_payload(
            extended_text="hello",
            mentioned_jids=[BOT_JID],
            timestamp=1700000000,
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.timestamp is not None
        assert msg.timestamp.year == 2023

    def test_no_timestamp(self):
        raw = _make_payload(
            extended_text="hello",
            mentioned_jids=[BOT_JID],
            timestamp=None,
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.timestamp is None

    def test_sender_fallback_to_remote_jid(self):
        raw = _make_payload(
            extended_text="hello",
            mentioned_jids=[BOT_JID],
            participant=None,
        )
        msg = parse_webhook(raw, BOT_JID)
        assert msg is not None
        assert msg.sender_jid == GROUP_JID


class TestParseWebhookRejected:
    """Test cases where parse_webhook should return None."""

    def test_from_me_rejected(self):
        raw = _make_payload(
            extended_text="bot echo",
            mentioned_jids=[BOT_JID],
            from_me=True,
        )
        assert parse_webhook(raw, BOT_JID) is None

    def test_private_message_rejected(self):
        raw = _make_payload(
            remote_jid="5511111111111@s.whatsapp.net",
            extended_text="hello",
            mentioned_jids=[BOT_JID],
        )
        assert parse_webhook(raw, BOT_JID) is None

    def test_no_text_content_rejected(self):
        raw = _make_payload()  # no conversation or extended_text
        assert parse_webhook(raw, BOT_JID) is None

    def test_not_mentioned_not_replied_rejected(self):
        raw = _make_payload(conversation="just chatting")
        assert parse_webhook(raw, BOT_JID) is None

    def test_reply_to_other_user_rejected(self):
        """Reply to another user's message (not bot's) should be rejected."""
        raw = _make_payload(
            extended_text="I agree with you",
            stanza_id="some-msg-id",
            ctx_participant=SENDER_JID,  # reply to a user, not the bot
        )
        assert parse_webhook(raw, BOT_JID) is None

    def test_mentioned_other_bot_rejected(self):
        raw = _make_payload(
            extended_text="@other hey",
            mentioned_jids=["other-bot@s.whatsapp.net"],
        )
        assert parse_webhook(raw, BOT_JID) is None

    def test_invalid_payload_rejected(self):
        assert parse_webhook({}, BOT_JID) is None
        assert parse_webhook({"event": "messages.upsert"}, BOT_JID) is None

    def test_null_message_rejected(self):
        raw = _make_payload()
        raw["data"]["message"] = None
        assert parse_webhook(raw, BOT_JID) is None
