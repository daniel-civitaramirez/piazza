"""Cross-domain search handler."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.db.repositories import checklist as checklist_repo
from piazza.db.repositories import expense as expense_repo
from piazza.db.repositories import itinerary as itinerary_repo
from piazza.db.repositories import note as note_repo
from piazza.db.repositories import reminder as reminder_repo
from piazza.tools.responses import Entity, empty_response, not_found_response
from piazza.tools.schemas import Entities

# ---------- Private helpers ----------


def _expense_summary(expense) -> dict:
    return {
        "description": expense.description,
        "amount_cents": expense.amount_cents,
        "currency": expense.currency,
        "payer": expense.payer.display_name,
    }


def _reminder_summary(reminder) -> dict:
    d: dict = {
        "message": reminder.message,
        "trigger_at": reminder.trigger_at.isoformat(),
    }
    if reminder.recurrence:
        d["recurrence"] = reminder.recurrence
    return d


def _itinerary_summary(item) -> dict:
    d: dict = {
        "title": item.title,
        "item_type": item.item_type,
    }
    if item.start_at:
        d["start_at"] = item.start_at.isoformat()
    if item.location:
        d["location"] = item.location
    return d


def _checklist_summary(item) -> dict:
    d: dict = {
        "content": item.content,
        "done": item.is_done,
    }
    if item.list_name != "default":
        d["list"] = item.list_name
    return d


def _note_summary(note) -> dict:
    d: dict = {
        "content": note.content,
    }
    if note.tag:
        d["tag"] = note.tag
    return d


# ---------- Public API ----------


async def handle_search_group(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    query = entities.description

    if query is not None:
        expenses = await expense_repo.find_expenses_by_description(session, group_id, query)
        reminders = await reminder_repo.find_active_reminders_by_message(session, group_id, query)
        itinerary_items = await itinerary_repo.find_items_by_title(session, group_id, query)
        checklist_items = await checklist_repo.find_items(session, group_id, query)
        notes = await note_repo.find_notes(session, group_id, query)
    else:
        expenses = await expense_repo.get_expenses(session, group_id)
        reminders = await reminder_repo.get_active_reminders(session, group_id)
        itinerary_items = await itinerary_repo.get_items(session, group_id)
        checklist_items = await checklist_repo.get_items(session, group_id)
        notes = await note_repo.get_notes(session, group_id)

    results: dict = {"status": "list"}
    if expenses:
        results["expenses"] = [_expense_summary(e) for e in expenses]
    if reminders:
        results["reminders"] = [_reminder_summary(r) for r in reminders]
    if itinerary_items:
        results["itinerary"] = [_itinerary_summary(it) for it in itinerary_items]
    if checklist_items:
        results["checklist"] = [_checklist_summary(ci) for ci in checklist_items]
    if notes:
        results["notes"] = [_note_summary(n) for n in notes]

    if len(results) == 1:
        if query is None:
            return empty_response(Entity.GROUP_DATA)
        return not_found_response(Entity.GROUP_DATA, query=query)

    return results
