"""Notes business logic."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.repositories import note as note_repo
from piazza.tools.notes import formatter

logger = structlog.get_logger()


async def save_note(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    content: str,
    tag: str | None = None,
) -> str:
    """Save a new note and return confirmation."""
    note = await note_repo.create_note(
        session, group_id, sender_id, content=content, tag=tag
    )
    await session.commit()
    return formatter.format_save_confirmation(note)


async def find_notes(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> str:
    """Search notes by keyword and return formatted results."""
    notes = await note_repo.find_notes(session, group_id, query)
    return formatter.format_search_results(notes)


async def list_notes(
    session: AsyncSession, group_id: uuid.UUID
) -> str:
    """List all notes for the group."""
    notes = await note_repo.get_notes(session, group_id)
    return formatter.format_note_list(notes)


async def delete_note_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> str:
    """Delete the Nth note (1-indexed, same order as list_notes)."""
    notes = await note_repo.get_notes(session, group_id)
    if number < 1 or number > len(notes):
        total = len(notes)
        if total == 0:
            return "No notes to delete."
        return f"Note #{number} not found. You have {total} saved note(s)."

    note = notes[number - 1]
    await session.delete(note)
    await session.flush()
    await session.commit()
    return formatter.format_delete_confirmation(note)


async def delete_note(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> str:
    """Delete a note by content/tag match, handling ambiguity."""
    matches = await note_repo.find_notes(session, group_id, query)

    if not matches:
        return f"No note matching _{query}_ found."

    if len(matches) == 1:
        note = matches[0]
        await session.delete(note)
        await session.flush()
        await session.commit()
        return formatter.format_delete_confirmation(note)

    return formatter.format_disambiguation(matches)
