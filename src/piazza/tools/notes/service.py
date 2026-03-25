"""Notes business logic."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError
from piazza.db.models.note import Note
from piazza.db.repositories import note as note_repo

logger = structlog.get_logger()


async def save_note(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    content: str,
    tag: str | None = None,
) -> Note:
    """Save a new note and return the model."""
    note = await note_repo.create_note(
        session, group_id, sender_id, content=content, tag=tag
    )
    await session.commit()
    return note


async def find_notes(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> list[Note]:
    """Search notes by keyword and return matching models."""
    return await note_repo.find_notes(session, group_id, query)


async def list_notes(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Note]:
    """List all notes for the group."""
    return await note_repo.get_notes(session, group_id)


async def delete_note_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> Note:
    """Delete the Nth note (1-indexed, same order as list_notes).

    Raises NotFoundError if the number is out of range.
    """
    notes = await note_repo.get_notes(session, group_id)
    if number < 1 or number > len(notes):
        raise NotFoundError("note", number=number, total=len(notes))

    note = notes[number - 1]
    await session.delete(note)
    await session.flush()
    await session.commit()
    return note


async def delete_note(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> Note | list[Note]:
    """Delete a note by content/tag match, handling ambiguity.

    Returns the deleted Note on single match, or list[Note] for ambiguous matches.
    Raises NotFoundError when no notes match the query.
    """
    matches = await note_repo.find_notes(session, group_id, query)

    if not matches:
        raise NotFoundError("note", query=query)

    if len(matches) == 1:
        note = matches[0]
        await session.delete(note)
        await session.flush()
        await session.commit()
        return note

    return matches
