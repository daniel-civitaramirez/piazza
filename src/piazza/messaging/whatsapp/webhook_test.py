"""Tests for piazza.whatsapp.webhook — FastAPI webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

BOT_JID = "5599999999999@s.whatsapp.net"
GROUP_JID = "120363001@g.us"
SENDER_JID = "5511111111111@s.whatsapp.net"


def _valid_payload() -> dict:
    """A minimal valid messages.upsert payload with a mention."""
    return {
        "event": "messages.upsert",
        "instance": "piazza-main",
        "data": {
            "key": {
                "remoteJid": GROUP_JID,
                "fromMe": False,
                "id": "MSG001",
                "participant": SENDER_JID,
            },
            "pushName": "Alice",
            "message": {
                "extendedTextMessage": {
                    "text": "@bot add expense $50",
                    "contextInfo": {"mentionedJid": [BOT_JID]},
                }
            },
            "messageTimestamp": 1700000000,
        },
    }


@pytest.fixture
def app():
    """Create a test FastAPI app with webhook router."""
    from fastapi import FastAPI

    from piazza.messaging.whatsapp.webhook import router

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.arq_pool = AsyncMock()
    return test_app


@pytest.fixture
def client(app):
    """TestClient for the webhook app."""
    return TestClient(app)


class TestWebhookEndpoint:
    """Test POST /webhook."""

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_messages_upsert_enqueues_job(self, mock_settings, app, client):
        mock_settings.webhook_secret = ""
        mock_settings.bot_jid = BOT_JID

        resp = client.post("/webhook", json=_valid_payload())
        assert resp.status_code == 200
        app.state.arq_pool.enqueue_job.assert_called_once()
        call_args = app.state.arq_pool.enqueue_job.call_args
        assert call_args[0][0] == "process_message_job"

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_non_messages_event_ignored(self, mock_settings, client):
        mock_settings.webhook_secret = ""
        mock_settings.bot_jid = BOT_JID

        payload = _valid_payload()
        payload["event"] = "connection.update"
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_irrelevant_message_not_enqueued(self, mock_settings, app, client):
        mock_settings.webhook_secret = ""
        mock_settings.bot_jid = BOT_JID

        payload = _valid_payload()
        # Remove mention so parser returns None
        payload["data"]["message"]["extendedTextMessage"]["contextInfo"] = {}
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        app.state.arq_pool.enqueue_job.assert_not_called()

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_no_arq_pool_returns_200(self, mock_settings, app, client):
        mock_settings.webhook_secret = ""
        mock_settings.bot_jid = BOT_JID
        app.state.arq_pool = None

        resp = client.post("/webhook", json=_valid_payload())
        assert resp.status_code == 200


class TestHmacVerification:
    """Test HMAC-SHA256 signature verification."""

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_valid_signature_accepted(self, mock_settings, app, client):
        secret = "test-secret-key"
        mock_settings.webhook_secret = secret
        mock_settings.bot_jid = BOT_JID

        body = json.dumps(_valid_payload()).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-webhook-signature": sig,
            },
        )
        assert resp.status_code == 200
        app.state.arq_pool.enqueue_job.assert_called_once()

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_invalid_signature_rejected(self, mock_settings, app, client):
        mock_settings.webhook_secret = "test-secret-key"
        mock_settings.bot_jid = BOT_JID

        resp = client.post(
            "/webhook",
            json=_valid_payload(),
            headers={"x-webhook-signature": "invalid-sig"},
        )
        assert resp.status_code == 200
        app.state.arq_pool.enqueue_job.assert_not_called()

    @patch("piazza.messaging.whatsapp.webhook.settings")
    def test_missing_signature_rejected(self, mock_settings, app, client):
        mock_settings.webhook_secret = "test-secret-key"
        mock_settings.bot_jid = BOT_JID

        resp = client.post("/webhook", json=_valid_payload())
        assert resp.status_code == 200
        app.state.arq_pool.enqueue_job.assert_not_called()
