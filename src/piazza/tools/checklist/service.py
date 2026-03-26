"""Checklist business logic."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError
from piazza.db.models.checklist import ChecklistItem
from piazza.db.repositories import checklist as checklist_repo

logger = structlog.get_logger()


async def add_item(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    content: str,
    list_name: str = "default",
) -> ChecklistItem:
    """Add a new checklist item and return the model."""
    item = await checklist_repo.create_item(
        session, group_id, sender_id, content=content, list_name=list_name
    )
    await session.commit()
    return item


async def list_items(
    session: AsyncSession,
    group_id: uuid.UUID,
    list_name: str | None = None,
    include_done: bool = False,
) -> list[ChecklistItem]:
    """List checklist items for the group."""
    return await checklist_repo.get_items(
        session, group_id, list_name=list_name, include_done=include_done
    )


async def _get_item_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> ChecklistItem:
    """Fetch the Nth item (1-indexed, same order as list_items with include_done=True)."""
    items = await checklist_repo.get_items(session, group_id, include_done=True)
    if number < 1 or number > len(items):
        raise NotFoundError("checklist_item", number=number, total=len(items))
    return items[number - 1]


async def _match_by_query(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> ChecklistItem | list[ChecklistItem]:
    """Find items by query. Returns single match or list for ambiguity."""
    matches = await checklist_repo.find_items(session, group_id, query)
    if not matches:
        raise NotFoundError("checklist_item", query=query)
    if len(matches) == 1:
        return matches[0]
    return matches


async def check_item_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> ChecklistItem:
    """Check the Nth item."""
    item = await _get_item_by_number(session, group_id, number)
    await checklist_repo.check_item(session, item)
    await session.commit()
    return item


async def check_item_by_query(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> ChecklistItem | list[ChecklistItem]:
    """Check an item by content match."""
    result = await _match_by_query(session, group_id, query)
    if isinstance(result, list):
        return result
    await checklist_repo.check_item(session, result)
    await session.commit()
    return result


async def uncheck_item_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> ChecklistItem:
    """Uncheck the Nth item."""
    item = await _get_item_by_number(session, group_id, number)
    await checklist_repo.uncheck_item(session, item)
    await session.commit()
    return item


async def uncheck_item_by_query(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> ChecklistItem | list[ChecklistItem]:
    """Uncheck an item by content match."""
    result = await _match_by_query(session, group_id, query)
    if isinstance(result, list):
        return result
    await checklist_repo.uncheck_item(session, result)
    await session.commit()
    return result


async def delete_item_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> ChecklistItem:
    """Delete the Nth item."""
    item = await _get_item_by_number(session, group_id, number)
    await checklist_repo.delete_item(session, item)
    await session.commit()
    return item


async def delete_item_by_query(
    session: AsyncSession, group_id: uuid.UUID, query: str
) -> ChecklistItem | list[ChecklistItem]:
    """Delete an item by content match."""
    result = await _match_by_query(session, group_id, query)
    if isinstance(result, list):
        return result
    await checklist_repo.delete_item(session, result)
    await session.commit()
    return result
