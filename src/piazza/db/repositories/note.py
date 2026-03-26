"""Notes database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.core.encryption import (
    decrypt,
    decrypt_nullable,
    encrypt,
    encrypt_nullable,
    set_decrypted,
)
from piazza.db.models.note import Note


def _key() -> bytes:
    return settings.encryption_key_bytes


def _decrypt_note(note: Note, key: bytes) -> None:
    set_decrypted(note, "content", decrypt(note.content, key))
    set_decrypted(note, "tag", decrypt_nullable(note.tag, key))


async def create_note(
    session: AsyncSession,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    content: str,
    tag: str | None = None,
) -> Note:
    """Add a note to the group."""
    key = _key()
    note = Note(
        group_id=group_id,
        created_by=created_by,
        content=encrypt(content, key),  # type: ignore[assignment]
        tag=encrypt_nullable(tag, key),  # type: ignore[assignment]
    )
    session.add(note)
    await session.flush()
    _decrypt_note(note, key)
    return note


async def get_notes(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Note]:
    """Get all notes for a group, most recent first."""
    result = await session.execute(
        select(Note)
        .where(Note.group_id == group_id)
        .order_by(Note.created_at.desc())
    )
    notes = list(result.scalars().all())
    key = _key()
    for n in notes:
        _decrypt_note(n, key)
    return notes


async def find_notes(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> list[Note]:
    """Find notes matching a query (case-insensitive on content and tag)."""
    notes = await get_notes(session, group_id)
    q = query.lower()
    return [
        n for n in notes
        if q in n.content.lower()  # type: ignore[union-attr]
        or (n.tag and q in n.tag.lower())
    ]


