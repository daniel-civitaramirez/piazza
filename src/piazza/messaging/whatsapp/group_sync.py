"""Group membership sync handlers for Evolution API webhook events.

Three mechanisms keep the members table in sync with WhatsApp:

1. handle_group_upsert() — fires when Piazza is added to a group.
   Populates all existing group members (JIDs only, phone numbers as temp names).

2. handle_group_participants_update() — fires when members join/leave/promote/demote.
   Keeps the roster current over time.

3. learn_display_name() — runs on every group message (before the mention gate).
   Learns WhatsApp display names (pushName) as members chat.
"""

from __future__ import annotations

import structlog

from piazza.admin.notify import notify_admin_new_group
from piazza.config.settings import APPROVAL_PENDING, APPROVAL_REJECTED, settings
from piazza.core.encryption import encrypt
from piazza.db.engine import AsyncSessionFactory
from piazza.db.repositories.group import get_or_create_group
from piazza.db.repositories.member import (
    deactivate_member,
    get_or_create_member_by_jid,
)
from piazza.messaging.whatsapp.schemas import (
    GroupParticipantsUpdateData,
    GroupUpsertData,
)

logger = structlog.get_logger()


async def handle_group_upsert(raw: dict) -> None:
    """Handle groups.upsert — bot was added to a WhatsApp group.

    Creates the group record and member records for all existing participants.
    Display names are not available from this event; phone numbers are used
    as temporary names until learned from messages.
    """
    try:
        raw_data = raw.get("data", {})
        if isinstance(raw_data, list):
            raw_data = raw_data[0] if raw_data else {}
        logger.debug("group_upsert_raw_data", raw_data=raw_data)
        data = GroupUpsertData(**raw_data)
    except Exception:
        logger.exception("group_upsert_parse_error")
        return

    try:
        async with AsyncSessionFactory() as session:
            group, was_created = await get_or_create_group(session, data.id)

            # Store group subject (encrypted) if encryption key is configured
            if (
                data.subject
                and group.name_encrypted is None
                and settings.encryption_key
            ):
                group.name_encrypted = encrypt(
                    data.subject, settings.encryption_key_bytes
                )

            synced = 0
            for participant in data.participants:
                # Evolution API v2 uses LID format for id; phoneNumber has the real JID
                jid = participant.phone_number or participant.id
                if jid and jid.endswith("@s.whatsapp.net"):
                    await get_or_create_member_by_jid(
                        session, group.id, jid
                    )
                    synced += 1

                # Auto-discover bot's LID for mention detection
                if jid == settings.bot_jid and participant.id.endswith("@lid"):
                    if not settings.bot_lid:
                        settings.bot_lid = participant.id
                        logger.info("bot_lid_discovered", bot_lid=participant.id)

            await session.commit()
            logger.info(
                "group_upsert_synced",
                group_id=str(group.id),
                members_synced=synced,
            )

            # Notify admin of new pending group (after commit)
            if was_created and group.approval_status == APPROVAL_PENDING:
                await notify_admin_new_group(
                    group_jid=data.id,
                    subject=data.subject,
                    participant_jids=[
                        (p.phone_number or p.id)
                        for p in data.participants
                        if (p.phone_number or p.id).endswith("@s.whatsapp.net")
                    ],
                )
    except Exception:
        logger.exception("group_upsert_error")


async def handle_group_participants_update(raw: dict) -> None:
    """Handle group-participants.update — member joined, left, promoted, or demoted.

    - add: creates member record (or re-activates if they rejoined)
    - remove: marks member as inactive (preserves expense history)
    - promote/demote: logged only, no DB changes needed for expenses
    """
    try:
        data = GroupParticipantsUpdateData(**raw.get("data", {}))
    except Exception:
        logger.exception("group_participants_update_parse_error")
        return

    try:
        async with AsyncSessionFactory() as session:
            group, _ = await get_or_create_group(session, data.group_jid)

            if group.approval_status == APPROVAL_REJECTED:
                return

            # Build a JID -> pushName mapping from participantsData (if available)
            name_map: dict[str, str | None] = {}
            for pd in data.participants_data:
                name_map[pd.jid] = pd.push_name

            if data.action == "add":
                for jid in data.participants:
                    if jid and jid.endswith("@s.whatsapp.net"):
                        await get_or_create_member_by_jid(
                            session,
                            group.id,
                            jid,
                            display_name=name_map.get(jid),
                        )

            elif data.action == "remove":
                for jid in data.participants:
                    if jid and jid.endswith("@s.whatsapp.net"):
                        await deactivate_member(session, group.id, jid)

            else:
                # promote / demote — log only
                logger.info(
                    "group_participants_action",
                    group_id=str(group.id),
                    action=data.action,
                    count=len(data.participants),
                )
                return

            await session.commit()
            logger.info(
                "group_participants_updated",
                group_id=str(group.id),
                action=data.action,
                count=len(data.participants),
            )
    except Exception:
        logger.exception(
            "group_participants_update_error",
            action=data.action,
        )


async def learn_display_name(
    group_jid: str, sender_jid: str, push_name: str
) -> None:
    """Learn a member's display name from any group message.

    This runs on every messages.upsert event (before the mention gate)
    so we learn WhatsApp display names as members chat, even if they
    never @mention Piazza.
    """
    try:
        async with AsyncSessionFactory() as session:
            group, _ = await get_or_create_group(session, group_jid)

            if group.approval_status == APPROVAL_REJECTED:
                return

            await get_or_create_member_by_jid(
                session, group.id, sender_jid, display_name=push_name
            )
            await session.commit()
    except Exception:
        # Fire-and-forget — must never block the webhook
        logger.exception("learn_display_name_error")
