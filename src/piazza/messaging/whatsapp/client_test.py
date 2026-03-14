"""Tests for piazza.whatsapp.client — Evolution API HTTP client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from piazza.core.exceptions import WhatsAppSendError
from piazza.messaging.whatsapp import client


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the global HTTP client between tests."""
    client._http_client = None
    yield
    client._http_client = None


@pytest.fixture
def mock_httpx():
    """Mock httpx.AsyncClient for testing HTTP calls."""
    mock = AsyncMock(spec=httpx.AsyncClient)
    mock.is_closed = False
    mock.post = AsyncMock()
    response = AsyncMock()
    response.is_success = True
    response.raise_for_status = lambda: None
    mock.post.return_value = response
    return mock


class TestSendText:
    @patch("piazza.messaging.whatsapp.client.settings")
    async def test_send_text_calls_correct_endpoint(self, mock_settings, mock_httpx):
        mock_settings.evo_api_url = "http://evo:8080"
        mock_settings.evo_api_key = "test-key"
        mock_settings.evo_instance_name = "piazza-main"
        client._http_client = mock_httpx

        await client.send_text("120363001@g.us", "Hello group!")

        mock_httpx.post.assert_called_once()
        call_args = mock_httpx.post.call_args
        assert call_args[0][0] == "http://evo:8080/message/sendText/piazza-main"
        assert call_args[1]["json"] == {"number": "120363001@g.us", "text": "Hello group!"}
        assert call_args[1]["headers"]["apikey"] == "test-key"

    @patch("piazza.messaging.whatsapp.client.asyncio.sleep", new_callable=AsyncMock)
    @patch("piazza.messaging.whatsapp.client.settings")
    async def test_send_text_raises_after_retries_exhausted(
        self, mock_settings, mock_sleep, mock_httpx
    ):
        mock_settings.evo_api_url = "http://evo:8080"
        mock_settings.evo_api_key = "test-key"
        mock_settings.evo_instance_name = "piazza-main"
        mock_httpx.post.side_effect = httpx.ConnectError("connection refused")
        client._http_client = mock_httpx

        with pytest.raises(WhatsAppSendError):
            await client.send_text("120363001@g.us", "Hello")

        assert mock_httpx.post.call_count == 3
        assert mock_sleep.call_count == 2  # backoff between retries

    @patch("piazza.messaging.whatsapp.client.asyncio.sleep", new_callable=AsyncMock)
    @patch("piazza.messaging.whatsapp.client.settings")
    async def test_send_text_retries_then_succeeds(
        self, mock_settings, mock_sleep, mock_httpx
    ):
        mock_settings.evo_api_url = "http://evo:8080"
        mock_settings.evo_api_key = "test-key"
        mock_settings.evo_instance_name = "piazza-main"

        response = AsyncMock()
        response.raise_for_status = lambda: None
        mock_httpx.post.side_effect = [
            httpx.ConnectError("connection refused"),
            response,
        ]
        client._http_client = mock_httpx

        await client.send_text("120363001@g.us", "Hello")

        assert mock_httpx.post.call_count == 2
        assert mock_sleep.call_count == 1


class TestSendTyping:
    @patch("piazza.messaging.whatsapp.client.settings")
    async def test_send_typing_calls_correct_endpoint(self, mock_settings, mock_httpx):
        mock_settings.evo_api_url = "http://evo:8080"
        mock_settings.evo_api_key = "test-key"
        mock_settings.evo_instance_name = "piazza-main"
        client._http_client = mock_httpx

        await client.send_typing("120363001@g.us")

        mock_httpx.post.assert_called_once()
        call_args = mock_httpx.post.call_args
        assert call_args[0][0] == "http://evo:8080/chat/presence/piazza-main"
        assert call_args[1]["json"] == {
            "number": "120363001@g.us",
            "presence": "composing",
        }

    @patch("piazza.messaging.whatsapp.client.settings")
    async def test_send_typing_handles_http_error(self, mock_settings, mock_httpx):
        mock_settings.evo_api_url = "http://evo:8080"
        mock_settings.evo_api_key = "test-key"
        mock_settings.evo_instance_name = "piazza-main"
        mock_httpx.post.side_effect = httpx.ConnectError("connection refused")
        client._http_client = mock_httpx

        # Should not raise
        await client.send_typing("120363001@g.us")


class TestClientLifecycle:
    async def test_close_when_open(self):
        mock = AsyncMock(spec=httpx.AsyncClient)
        mock.is_closed = False
        client._http_client = mock

        await client.close()

        mock.aclose.assert_called_once()
        assert client._http_client is None

    async def test_close_when_already_closed(self):
        mock = AsyncMock(spec=httpx.AsyncClient)
        mock.is_closed = True
        client._http_client = mock

        await client.close()
        mock.aclose.assert_not_called()

    async def test_close_when_none(self):
        client._http_client = None
        await client.close()  # Should not raise
