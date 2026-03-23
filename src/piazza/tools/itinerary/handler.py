"""Itinerary intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.tools.itinerary import service
from piazza.tools.schemas import Entities


async def handle_itinerary_add(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Add items to the itinerary."""
    if not entities.items:
        return (
            "Please describe what to add. "
            "Example: _@Piazza add to itinerary: Flight BA247, Mar 15, 11am_"
        )

    return await service.add_from_items(session, group_id, sender_id, entities.items)


async def handle_itinerary_show(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Show the full itinerary."""
    return await service.list_itinerary(session, group_id)


async def handle_itinerary_remove(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Remove an item from the itinerary by list number or description match."""
    if entities.item_number is not None:
        return await service.delete_item_by_number(session, group_id, entities.item_number)
    if entities.description:
        return await service.delete_item(session, group_id, entities.description)
    return (
        "Please specify which item to remove. "
        "Example: _remove itinerary #2_ or _remove the hotel_"
    )
