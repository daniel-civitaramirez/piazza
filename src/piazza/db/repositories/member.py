"""Member database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.core.encryption import decrypt, encrypt, hash_phone, set_decrypted
from piazza.db.models.member import Member


def _key() -> bytes:
    return settings.encryption_key_bytes


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
        key = _key()
        stored_name = decrypt(member.display_name, key)  # type: ignore[arg-type]
        if stored_name != display_name:
            member.display_name = encrypt(display_name, key)  # type: ignore[assignment]
            await session.flush()
        set_decrypted(member, "display_name", display_name)
        return member

    key = _key()
    member = Member(
        group_id=group_id,
        wa_id_hash=wa_hash,
        wa_id_encrypted=encrypt(wa_id, key),
        display_name=encrypt(display_name, key),  # type: ignore[assignment]
    )
    session.add(member)
    await session.flush()
    set_decrypted(member, "display_name", display_name)
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
        key = _key()
        stored_name = decrypt(member.display_name, key)  # type: ignore[arg-type]
        # Only update display_name if we have a real pushName (not phone number)
        if display_name and stored_name != display_name:
            member.display_name = encrypt(display_name, key)  # type: ignore[assignment]
            stored_name = display_name
            await session.flush()
        # Re-activate if previously deactivated (e.g. member rejoined)
        if not member.is_active:
            member.is_active = True
        set_decrypted(member, "display_name", stored_name)
        return member

    key = _key()
    member = Member(
        group_id=group_id,
        wa_id_hash=wa_hash,
        wa_id_encrypted=encrypt(wa_jid, key),
        display_name=encrypt(name, key),  # type: ignore[assignment]
        is_active=True,
    )
    session.add(member)
    await session.flush()
    set_decrypted(member, "display_name", name)
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
    members = list(result.scalars().all())
    key = _key()
    for m in members:
        set_decrypted(m, "display_name", decrypt(m.display_name, key))
    return members


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
    members = list(result.scalars().all())
    key = _key()
    for m in members:
        set_decrypted(m, "display_name", decrypt(m.display_name, key))
    return members


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
        set_decrypted(member, "display_name", decrypt(member.display_name, _key()))
    return member


async def _get_member_by_name(
    session: AsyncSession, group_id: uuid.UUID, display_name: str
) -> Member | None:
    """Resolve a member by display name (case-insensitive exact match)."""
    result = await session.execute(
        select(Member).where(Member.group_id == group_id)
    )
    members = list(result.scalars().all())
    key = _key()
    for m in members:
        set_decrypted(m, "display_name", decrypt(m.display_name, key))
        if m.display_name.lower() == display_name.lower():  # type: ignore[union-attr]
            return m
    return None


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
    members = await get_active_members(session, group_id)
    candidates = [
        m for m in members
        if display_name.lower() in m.display_name.lower()  # type: ignore[union-attr]
    ]
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates
