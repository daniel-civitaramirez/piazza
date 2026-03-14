"""Notes database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.models.note import Note


async def create_note(
    session: AsyncSession,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    content: str,
    tag: str | None = None,
) -> Note:
    """Add a note to the group."""
    note = Note(
        group_id=group_id,
        created_by=created_by,
        content=content,
        tag=tag,
    )
    session.add(note)
    await session.flush()
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
    return list(result.scalars().all())


async def find_notes(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> list[Note]:
    """Find notes matching a query (case-insensitive LIKE on content and tag)."""
    pattern = f"%{query}%"
    result = await session.execute(
        select(Note).where(
            Note.group_id == group_id,
            (Note.content.ilike(pattern)) | (Note.tag.ilike(pattern)),
        )
    )
    return list(result.scalars().all())


