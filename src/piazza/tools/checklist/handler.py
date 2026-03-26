"""Checklist intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import NotFoundError
from piazza.db.models.checklist import ChecklistItem
from piazza.tools.checklist import service
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


def _item_to_dict(item: ChecklistItem, number: int | None = None) -> dict:
    """Convert a ChecklistItem model to a serialisable dict."""
    d: dict = {"content": item.content, "done": item.is_done}
    if item.list_name != "default":
        d["list"] = item.list_name
    if number is not None:
        d["number"] = number
    return d


async def handle_item_add(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Add an item to a checklist."""
    if not entities.description:
        return error_response(Reason.MISSING_DESCRIPTION, entity=Entity.CHECKLIST_ITEM)
    item = await service.add_item(
        session, group_id, sender_id,
        content=entities.description,
        list_name=entities.list_name or "default",
    )
    return ok_response(Action.ADD_ITEM, **_item_to_dict(item))


async def handle_item_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """List checklist items."""
    items = await service.list_items(
        session, group_id,
        list_name=entities.list_name,
        include_done=entities.show_done or False,
    )
    if not items:
        return empty_response(Entity.CHECKLIST_ITEMS)
    return list_response(
        Entity.CHECKLIST_ITEMS,
        [_item_to_dict(item, i) for i, item in enumerate(items, 1)],
    )


async def handle_item_check(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Check off an item."""
    try:
        if entities.item_number is not None:
            item = await service.check_item_by_number(session, group_id, entities.item_number)
            return ok_response(Action.CHECK_ITEM, **_item_to_dict(item))
        if entities.description:
            result = await service.check_item_by_query(session, group_id, entities.description)
            if isinstance(result, list):
                return ambiguous_response(
                    Entity.CHECKLIST_ITEM,
                    [_item_to_dict(item, i) for i, item in enumerate(result[:5], 1)],
                )
            return ok_response(Action.CHECK_ITEM, **_item_to_dict(result))
    except NotFoundError as exc:
        return not_found_response(
            exc.entity, number=exc.number, total=exc.total, query=exc.query
        )
    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.CHECKLIST_ITEM)


async def handle_item_uncheck(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Uncheck an item."""
    try:
        if entities.item_number is not None:
            item = await service.uncheck_item_by_number(session, group_id, entities.item_number)
            return ok_response(Action.UNCHECK_ITEM, **_item_to_dict(item))
        if entities.description:
            result = await service.uncheck_item_by_query(session, group_id, entities.description)
            if isinstance(result, list):
                return ambiguous_response(
                    Entity.CHECKLIST_ITEM,
                    [_item_to_dict(item, i) for i, item in enumerate(result[:5], 1)],
                )
            return ok_response(Action.UNCHECK_ITEM, **_item_to_dict(result))
    except NotFoundError as exc:
        return not_found_response(
            exc.entity, number=exc.number, total=exc.total, query=exc.query
        )
    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.CHECKLIST_ITEM)


async def handle_item_delete(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Delete a checklist item."""
    try:
        if entities.item_number is not None:
            item = await service.delete_item_by_number(session, group_id, entities.item_number)
            return ok_response(Action.DELETE_ITEM, **_item_to_dict(item))
        if entities.description:
            result = await service.delete_item_by_query(session, group_id, entities.description)
            if isinstance(result, list):
                return ambiguous_response(
                    Entity.CHECKLIST_ITEM,
                    [_item_to_dict(item, i) for i, item in enumerate(result[:5], 1)],
                )
            return ok_response(Action.DELETE_ITEM, **_item_to_dict(result))
    except NotFoundError as exc:
        return not_found_response(
            exc.entity, number=exc.number, total=exc.total, query=exc.query
        )
    return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.CHECKLIST_ITEM)
