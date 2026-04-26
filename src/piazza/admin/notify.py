"""Admin notification for pending group approvals."""

from __future__ import annotations

import structlog

from piazza.config.settings import settings
from piazza.messaging.whatsapp import client

logger = structlog.get_logger()


def _format_phone(jid: str) -> str:
    """Extract phone number from a WhatsApp JID."""
    return jid.split("@")[0]


def _build_message(
    group_jid: str,
    subject: str | None,
    participant_jids: list[str],
) -> str:
    name = subject or "(unnamed)"
    count = len(participant_jids)
    phones = ", ".join(_format_phone(jid) for jid in participant_jids[:10])
    if len(participant_jids) > 10:
        phones += f" (+{len(participant_jids) - 10} more)"

    return (
        f"\U0001f4cb New group wants to use Piazza\n"
        f"\n"
        f"Group: {name}\n"
        f"JID: {group_jid}\n"
        f"Participants ({count}): {phones}\n"
        f"\n"
        f'To approve, open Supabase \u2192 groups table \u2192 find this JID '
        f'\u2192 set approval_status to "approved"'
    )


async def notify_admin_new_group(
    group_jid: str,
    subject: str | None,
    participant_jids: list[str],
) -> None:
    """Send admin a DM about a new group pending approval.

    No-op if admin_jid is not configured.
    Fire-and-forget — failures are logged but never raised.
    """
    if not settings.admin_jid:
        return

    message = _build_message(group_jid, subject, participant_jids)

    try:
        await client.send_text(settings.admin_jid, message)
        logger.info("admin_notified_new_group")
    except Exception:
        logger.exception("admin_notify_failed")
