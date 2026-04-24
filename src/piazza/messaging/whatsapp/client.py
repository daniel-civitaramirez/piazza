"""WhatsApp client for Evolution API communication."""

from __future__ import annotations

import asyncio

import httpx
import structlog

from piazza.config.settings import settings
from piazza.core.exceptions import WhatsAppSendError

logger = structlog.get_logger()

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=settings.wa_client_timeout)
    return _http_client


def _headers() -> dict[str, str]:
    """Common headers for Evolution API requests."""
    return {"apikey": settings.evo_api_key, "Content-Type": "application/json"}


def _url(path: str) -> str:
    """Build full Evolution API URL."""
    base = settings.evo_api_url.rstrip("/")
    instance = settings.evo_instance_name
    return f"{base}/{path}/{instance}"


async def send_text(group_jid: str, text: str) -> str | None:
    """Send a text message to a WhatsApp group via Evolution API.

    Retries up to 3 times with exponential backoff.
    Raises WhatsAppSendError if all attempts fail.
    Returns the WhatsApp message ID from the API response, or None if
    the response body couldn't be parsed.
    """
    http = _get_client()
    url = _url("message/sendText")
    payload = {"number": group_jid, "text": text}
    last_exc: Exception | None = None

    for attempt in range(1, settings.wa_send_max_retries + 1):
        try:
            resp = await http.post(url, json=payload, headers=_headers())
            resp.raise_for_status()
            logger.info(
                "whatsapp_send_text",
                text_length=len(text),
                attempt=attempt,
            )
            # Extract WA message ID from Evolution API response
            try:
                body = resp.json()
                return body.get("key", {}).get("id")
            except Exception:
                return None
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "whatsapp_send_text_attempt_failed",
                attempt=attempt,
                max_retries=settings.wa_send_max_retries,
            )
            if attempt < settings.wa_send_max_retries:
                await asyncio.sleep(settings.wa_send_backoff_base * (2 ** (attempt - 1)))

    logger.error(
        "whatsapp_send_text_failed",
        attempts=settings.wa_send_max_retries,
    )
    raise WhatsAppSendError(
        f"Failed to send message to {group_jid} after {settings.wa_send_max_retries} attempts"
    ) from last_exc


async def send_typing(group_jid: str) -> None:
    """Send typing indicator (composing presence) to a WhatsApp group."""
    client = _get_client()
    url = _url("chat/sendPresence")
    payload = {"number": group_jid, "presence": "composing", "delay": 1200}

    try:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("whatsapp_send_typing_failed", error=str(exc))


async def close() -> None:
    """Close the shared HTTP client (call during app shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
