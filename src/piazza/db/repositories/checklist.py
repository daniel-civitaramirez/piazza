"""Checklist database queries."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.core.encryption import decrypt, encrypt, set_decrypted
from piazza.db.models.checklist import ChecklistItem


def _key() -> bytes:
    return settings.encryption_key_bytes


def _decrypt_item(item: ChecklistItem, key: bytes) -> None:
    set_decrypted(item, "content", decrypt(item.content, key))
    set_decrypted(item, "list_name", decrypt(item.list_name, key))


async def create_item(
    session: AsyncSession,
    group_id: uuid.UUID,
    created_by: uuid.UUID,
    content: str,
    list_name: str = "default",
) -> ChecklistItem:
    """Add a checklist item to a group."""
    key = _key()
    item = ChecklistItem(
        group_id=group_id,
        created_by=created_by,
        content=encrypt(content, key),  # type: ignore[assignment]
        list_name=encrypt(list_name, key),  # type: ignore[assignment]
    )
    session.add(item)
    await session.flush()
    _decrypt_item(item, key)
    return item


async def get_items(
    session: AsyncSession,
    group_id: uuid.UUID,
    *,
    list_name: str | None = None,
    include_done: bool = False,
) -> list[ChecklistItem]:
    """Get checklist items for a group, oldest first.

    Filters by list_name (exact, post-decryption) and is_done.
    """
    stmt = (
        select(ChecklistItem)
        .where(ChecklistItem.group_id == group_id)
        .order_by(ChecklistItem.created_at.asc())
    )
    if not include_done:
        stmt = stmt.where(ChecklistItem.is_done == False)  # noqa: E712

    result = await session.execute(stmt)
    items = list(result.scalars().all())
    key = _key()
    for item in items:
        _decrypt_item(item, key)

    if list_name is not None:
        items = [i for i in items if i.list_name == list_name]

    return items


async def find_items(
    session: AsyncSession,
    group_id: uuid.UUID,
    query: str,
) -> list[ChecklistItem]:
    """Find checklist items matching a query (case-insensitive on content)."""
    items = await get_items(session, group_id, include_done=True)
    q = query.lower()
    return [i for i in items if q in i.content.lower()]  # type: ignore[union-attr]


async def check_item(session: AsyncSession, item: ChecklistItem) -> ChecklistItem:
    """Mark an item as done."""
    item.is_done = True
    item.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return item


async def uncheck_item(session: AsyncSession, item: ChecklistItem) -> ChecklistItem:
    """Mark an item as not done."""
    item.is_done = False
    item.completed_at = None
    await session.flush()
    return item


async def delete_item(session: AsyncSession, item: ChecklistItem) -> None:
    """Delete a checklist item."""
    await session.delete(item)
    await session.flush()
