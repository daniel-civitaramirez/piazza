"""Itinerary database queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.core.encryption import (
    decrypt,
    decrypt_nullable,
    encrypt,
    encrypt_nullable,
    set_decrypted,
)
from piazza.db.models.itinerary import ItineraryItem


def _key() -> bytes:
    return settings.encryption_key_bytes


def _decrypt_item(item: ItineraryItem, key: bytes) -> None:
    set_decrypted(item, "title", decrypt(item.title, key))
    set_decrypted(item, "location", decrypt_nullable(item.location, key))
    set_decrypted(item, "notes", decrypt_nullable(item.notes, key))


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
    key = _key()
    item = ItineraryItem(
        group_id=group_id,
        item_type=item_type,
        title=encrypt(title, key),  # type: ignore[assignment]
        start_at=start_at,
        end_at=end_at,
        location=encrypt_nullable(location, key),  # type: ignore[assignment]
        notes=encrypt_nullable(notes, key),  # type: ignore[assignment]
        metadata_=metadata or {},
    )
    session.add(item)
    await session.flush()
    _decrypt_item(item, key)
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
    items = list(result.scalars().all())
    key = _key()
    for item in items:
        _decrypt_item(item, key)
    return items


async def find_items_by_title(
    session: AsyncSession, group_id: uuid.UUID, title_query: str
) -> list[ItineraryItem]:
    """Find itinerary items fuzzy-matching title, ranked best-first."""
    items = await get_items(session, group_id)
    matches = process.extract(
        title_query,
        [i.title for i in items],
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        score_cutoff=70,
        limit=5,
    )
    return [items[idx] for _, _, idx in matches]
