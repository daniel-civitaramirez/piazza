"""Notes intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError
from piazza.db.models.note import Note
from piazza.tools.notes import service
from piazza.tools.responses import (
    Action,
    Entity,
    Reason,
    ambiguous_response,
    empty_response,
    error_response,
    list_response,
    not_found_response,
    ok_response,
)
from piazza.tools.schemas import Entities


def _note_to_dict(note: Note, number: int | None = None) -> dict:
    """Convert a Note model to a serialisable dict."""
    d: dict = {"content": note.content}
    if note.tag:
        d["tag"] = note.tag
    if number is not None:
        d["number"] = number
    return d


async def handle_note_save(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Save a note to the group's knowledge base."""
    note = await service.save_note(
        session, group_id, sender_id, content=entities.description or "", tag=entities.tag
    )
    return ok_response(Action.SAVE_NOTE, **_note_to_dict(note))


async def handle_note_find(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Search the group's knowledge base."""
    notes = await service.find_notes(session, group_id, entities.description or "")
    if not notes:
        return not_found_response(Entity.NOTES, query=entities.description or "")
    return list_response(Entity.NOTES, [_note_to_dict(n, i) for i, n in enumerate(notes, 1)])


async def handle_note_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """List all saved notes."""
    notes = await service.list_notes(session, group_id)
    if not notes:
        return empty_response(Entity.NOTES)
    return list_response(Entity.NOTES, [_note_to_dict(n, i) for i, n in enumerate(notes, 1)])


async def handle_note_delete(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Delete a note by list number or content/tag match."""
    try:
        if entities.item_number is not None:
            note = await service.delete_note_by_number(session, group_id, entities.item_number)
            return ok_response(Action.DELETE_NOTE, **_note_to_dict(note))
        if entities.description:
            result = await service.delete_note(session, group_id, entities.description)
            if isinstance(result, list):
                return ambiguous_response(
                    Entity.NOTE,
                    [_note_to_dict(n, i) for i, n in enumerate(result[:5], 1)],
                )
            return ok_response(Action.DELETE_NOTE, **_note_to_dict(result))
    except NotFoundError as exc:
        return not_found_response(
            exc.entity, number=exc.number, total=exc.total, query=exc.query
        )

    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.NOTE)
