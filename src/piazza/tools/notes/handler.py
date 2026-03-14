"""Notes intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.tools.notes import service
from piazza.tools.schemas import Entities


async def handle_note_save(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Save a note to the group's knowledge base."""
    content = entities.description or ""
    if not content:
        return (
            "Please specify what to save. "
            "Example: _@Piazza save: wifi password is BeachLife2026_"
        )

    return await service.save_note(
        session, group_id, sender_id, content=content, tag=entities.tag
    )


async def handle_note_find(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Search the group's knowledge base."""
    query = entities.description or ""
    if not query:
        return "What are you looking for? Example: _@Piazza find wifi password_"

    return await service.find_notes(session, group_id, query)


async def handle_note_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """List all saved notes."""
    return await service.list_notes(session, group_id)


async def handle_note_delete(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Delete a note from the knowledge base."""
    query = entities.description or ""
    if not query:
        return "Please specify which note to delete. Example: _@Piazza delete note wifi password_"

    return await service.delete_note(session, group_id, query)
