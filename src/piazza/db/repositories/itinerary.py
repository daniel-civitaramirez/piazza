"""Itinerary database queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.models.itinerary import ItineraryItem


async def create_item(
    session: AsyncSession,
    group_id: uuid.UUID,
    item_type: str,
    title: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    location: str | None = None,
    notes: str | None = None,
    metadata: dict | None = None,
) -> ItineraryItem:
    """Add an itinerary item."""
    item = ItineraryItem(
        group_id=group_id,
        item_type=item_type,
        title=title,
        start_at=start_at,
        end_at=end_at,
        location=location,
        notes=notes,
        metadata_=metadata or {},
    )
    session.add(item)
    await session.flush()
    return item


async def get_items(
    session: AsyncSession, group_id: uuid.UUID
) -> list[ItineraryItem]:
    """Get all itinerary items for a group, ordered by start_at."""
    result = await session.execute(
        select(ItineraryItem)
        .where(ItineraryItem.group_id == group_id)
        .order_by(ItineraryItem.start_at.asc().nulls_last())
    )
    return list(result.scalars().all())


async def find_items_by_title(
    session: AsyncSession, group_id: uuid.UUID, title_query: str
) -> list[ItineraryItem]:
    """Find itinerary items matching a title query (case-insensitive LIKE)."""
    result = await session.execute(
        select(ItineraryItem).where(
            ItineraryItem.group_id == group_id,
            ItineraryItem.title.ilike(f"%{title_query}%"),
        )
    )
    return list(result.scalars().all())
