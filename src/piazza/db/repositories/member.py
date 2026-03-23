"""Member database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.core.encryption import encrypt, hash_phone
from piazza.db.models.member import Member


async def get_or_create_member(
    session: AsyncSession,
    group_id: uuid.UUID,
    wa_id: str,
    display_name: str,
) -> Member:
    """Get a member by WA ID hash, or create if not exists.

    Updates display_name if it changed (e.g. user changed their WhatsApp name).
    """
    wa_hash = hash_phone(wa_id)
    result = await session.execute(
        select(Member).where(
            Member.group_id == group_id, Member.wa_id_hash == wa_hash
        )
    )
    member = result.scalar_one_or_none()
    if member is not None:
        if member.display_name != display_name:
            member.display_name = display_name
        return member

    if not settings.encryption_key:
        raise ValueError("ENCRYPTION_KEY must be configured")
    key = settings.encryption_key_bytes
    member = Member(
        group_id=group_id,
        wa_id_hash=wa_hash,
        wa_id_encrypted=encrypt(wa_id, key),
        display_name=display_name,
    )
    session.add(member)
    await session.flush()
    return member


async def get_or_create_member_by_jid(
    session: AsyncSession,
    group_id: uuid.UUID,
    wa_jid: str,
    display_name: str | None = None,
) -> Member:
    """Get or create a member from a WhatsApp JID (Evolution API sync).

    Used when syncing members from group events where display names may not
    be available. Falls back to the phone number portion of the JID as a
    temporary display name. Only overwrites an existing display_name if a
    real pushName is provided (avoids replacing a learned name with a phone
    number). Re-activates inactive members on re-add.
    """
    wa_hash = hash_phone(wa_jid)
    result = await session.execute(
        select(Member).where(
            Member.group_id == group_id, Member.wa_id_hash == wa_hash
        )
    )
    member = result.scalar_one_or_none()

    # Derive fallback name from JID phone number
    fallback_name = wa_jid.split("@")[0]
    name = display_name or fallback_name

    if member is not None:
        # Only update display_name if we have a real pushName (not phone number)
        if display_name and member.display_name != display_name:
            member.display_name = display_name
        # Re-activate if previously deactivated (e.g. member rejoined)
        if not member.is_active:
            member.is_active = True
        return member

    if not settings.encryption_key:
        raise ValueError("ENCRYPTION_KEY must be configured")
    key = settings.encryption_key_bytes
    member = Member(
        group_id=group_id,
        wa_id_hash=wa_hash,
        wa_id_encrypted=encrypt(wa_jid, key),
        display_name=name,
        is_active=True,
    )
    session.add(member)
    await session.flush()
    return member


async def get_all_members(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Member]:
    """Get all members of a group (including inactive).

    Used for balance calculations where inactive members still owe/are owed.
    """
    result = await session.execute(
        select(Member).where(Member.group_id == group_id)
    )
    return list(result.scalars().all())


async def get_active_members(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Member]:
    """Get active members of a group.

    Used for LLM context injection and 'everyone' expense expansion.
    """
    result = await session.execute(
        select(Member).where(
            Member.group_id == group_id,
            Member.is_active == True,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def deactivate_member(
    session: AsyncSession, group_id: uuid.UUID, wa_jid: str
) -> Member | None:
    """Mark a member as inactive (e.g. they left the group).

    Does not delete — member may still have expense history.
    """
    wa_hash = hash_phone(wa_jid)
    result = await session.execute(
        select(Member).where(
            Member.group_id == group_id, Member.wa_id_hash == wa_hash
        )
    )
    member = result.scalar_one_or_none()
    if member is not None:
        member.is_active = False
    return member


async def _get_member_by_name(
    session: AsyncSession, group_id: uuid.UUID, display_name: str
) -> Member | None:
    """Resolve a member by display name (case-insensitive exact match)."""
    result = await session.execute(
        select(Member).where(
            Member.group_id == group_id,
            Member.display_name.ilike(display_name),
        )
    )
    return result.scalar_one_or_none()


async def find_member_by_name(
    session: AsyncSession, group_id: uuid.UUID, display_name: str
) -> tuple[Member | None, list[Member]]:
    """Resolve a member by name with fuzzy fallback.

    Returns (exact_match, fuzzy_candidates):
    - If exact case-insensitive match found: (member, [])
    - If single substring match found: (member, [])
    - If multiple substring matches: (None, [candidates...])
    - If no match at all: (None, [])
    """
    # Try exact match first (fast path)
    exact = await _get_member_by_name(session, group_id, display_name)
    if exact is not None:
        return exact, []

    # Try substring match on active members
    result = await session.execute(
        select(Member).where(
            Member.group_id == group_id,
            Member.is_active == True,  # noqa: E712
            Member.display_name.ilike(f"%{display_name}%"),
        )
    )
    candidates = list(result.scalars().all())
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates
