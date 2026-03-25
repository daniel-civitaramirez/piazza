"""Itinerary intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError
from piazza.db.models.itinerary import ItineraryItem
from piazza.tools.itinerary import service
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


def _item_to_dict(item: ItineraryItem, *, number: int | None = None) -> dict:
    """Convert an ItineraryItem to a serialisable dict."""
    d: dict = {
        "title": item.title,
        "item_type": item.item_type,
        "start_at": item.start_at.isoformat() if item.start_at else None,
        "end_at": item.end_at.isoformat() if item.end_at else None,
        "location": item.location,
        "notes": item.notes,
    }
    if number is not None:
        d["number"] = number
    return d


async def handle_itinerary_add(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Add items to the itinerary."""
    if not entities.items:
        return error_response(Reason.MISSING_ITEMS)

    items = await service.add_from_items(session, group_id, sender_id, entities.items)
    return ok_response(
        Action.ADD_ITINERARY,
        items=[_item_to_dict(item) for item in items],
    )


async def handle_itinerary_show(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Show the full itinerary."""
    items = await service.list_itinerary(session, group_id)
    if not items:
        return empty_response(Entity.ITINERARY)

    return list_response(
        Entity.ITINERARY,
        [_item_to_dict(item, number=i) for i, item in enumerate(items, 1)],
    )


async def handle_itinerary_remove(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Remove an item from the itinerary by list number or description match."""
    if entities.item_number is not None:
        try:
            item = await service.delete_item_by_number(
                session, group_id, entities.item_number
            )
        except NotFoundError as exc:
            return not_found_response(exc.entity, number=exc.number, total=exc.total)
        return ok_response(Action.REMOVE_ITINERARY, item=_item_to_dict(item))

    if entities.description:
        try:
            result = await service.delete_item(
                session, group_id, entities.description
            )
        except NotFoundError as exc:
            return not_found_response(exc.entity, query=exc.query)
        if isinstance(result, list):
            return ambiguous_response(
                Entity.ITINERARY_ITEM,
                [_item_to_dict(item) for item in result],
                query=entities.description,
            )
        return ok_response(Action.REMOVE_ITINERARY, item=_item_to_dict(result))

    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.ITINERARY_ITEM)
