"""WhatsApp client for Evolution API communication."""

from __future__ import annotations

import asyncio

import httpx
import structlog

from piazza.config.settings import settings
from piazza.core.exceptions import WhatsAppSendError

logger = structlog.get_logger()

_http_client: httpx.AsyncClient | None = None
_SEND_MAX_RETRIES = 3
_SEND_BACKOFF_BASE = 0.5  # seconds


def _get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=10.0)
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

    for attempt in range(1, _SEND_MAX_RETRIES + 1):
        try:
            resp = await http.post(url, json=payload, headers=_headers())
            resp.raise_for_status()
            logger.info(
                "whatsapp_send_text",
                group_jid=group_jid,
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
                group_jid=group_jid,
                attempt=attempt,
                max_retries=_SEND_MAX_RETRIES,
            )
            if attempt < _SEND_MAX_RETRIES:
                await asyncio.sleep(_SEND_BACKOFF_BASE * (2 ** (attempt - 1)))

    logger.error(
        "whatsapp_send_text_failed",
        group_jid=group_jid,
        attempts=_SEND_MAX_RETRIES,
    )
    raise WhatsAppSendError(
        f"Failed to send message to {group_jid} after {_SEND_MAX_RETRIES} attempts"
    ) from last_exc


async def send_typing(group_jid: str) -> None:
    """Send typing indicator (composing presence) to a WhatsApp group."""
    client = _get_client()
    url = _url("chat/presence")
    payload = {"number": group_jid, "presence": "composing"}

    try:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.exception("whatsapp_send_typing_failed", group_jid=group_jid)


async def close() -> None:
    """Close the shared HTTP client (call during app shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
