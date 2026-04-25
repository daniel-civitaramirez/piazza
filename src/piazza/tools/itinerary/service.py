"""Itinerary business logic."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError
from piazza.db.models.itinerary import ItineraryItem
from piazza.db.repositories import itinerary as itinerary_repo

logger = structlog.get_logger()


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def add_from_items(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    raw_items: list[dict],
) -> list[ItineraryItem]:
    """Add structured itinerary items (already parsed by the agent LLM)."""
    items = []
    for raw in raw_items:
        start_at = _parse_iso(raw.get("start_at"))
        end_at = _parse_iso(raw.get("end_at"))

        item = await itinerary_repo.create_item(
            session,
            group_id=group_id,
            item_type=raw.get("item_type", "activity"),
            title=raw.get("title", "Untitled"),
            start_at=start_at,
            end_at=end_at,
            location=raw.get("location"),
            notes=raw.get("notes"),
        )
        items.append(item)

    await session.commit()
    return items


async def list_itinerary(
    session: AsyncSession, group_id: uuid.UUID
) -> list[ItineraryItem]:
    """Get the full itinerary as a list of items."""
    return await itinerary_repo.get_items(session, group_id)


async def delete_item_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> ItineraryItem:
    """Delete the Nth itinerary item (1-indexed, same order as show_itinerary).

    Raises NotFoundError if the number is out of range.
    """
    items = await itinerary_repo.get_items(session, group_id)
    if number < 1 or number > len(items):
        raise NotFoundError("itinerary_item", number=number, total=len(items))

    item = items[number - 1]
    await session.delete(item)
    await session.flush()
    await session.commit()
    return item


async def delete_item(
    session: AsyncSession, group_id: uuid.UUID, description: str
) -> ItineraryItem | list[ItineraryItem]:
    """Delete an item by title match, handling ambiguity.

    Returns a single ItineraryItem on exact/unique match, or a list for ambiguous.
    Raises NotFoundError if no matches.
    """
    matches = await itinerary_repo.find_items_by_title(session, group_id, description)

    if not matches:
        raise NotFoundError("itinerary_item", query=description)

    if len(matches) == 1:
        await session.delete(matches[0])
        await session.flush()
        await session.commit()
        return matches[0]

    return matches
