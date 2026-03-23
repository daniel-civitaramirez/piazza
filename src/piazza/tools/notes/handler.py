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
    return await service.save_note(
        session, group_id, sender_id, content=entities.description or "", tag=entities.tag
    )


async def handle_note_find(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Search the group's knowledge base."""
    return await service.find_notes(session, group_id, entities.description or "")


async def handle_note_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """List all saved notes."""
    return await service.list_notes(session, group_id)


async def handle_note_delete(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Delete a note by list number or content/tag match."""
    if entities.item_number is not None:
        return await service.delete_note_by_number(session, group_id, entities.item_number)
    if entities.description:
        return await service.delete_note(session, group_id, entities.description)
    return (
        "Please specify which note to delete. "
        "Example: _delete note #1_ or _delete the wifi note_"
    )
