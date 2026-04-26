"""Shared response constants and builders for tool handlers.

Every handler returns a dict with a ``status`` key. This module centralises
the allowed values so new tools follow the same contract.
"""

from __future__ import annotations

from typing import Any

# ---------- Status codes ----------


class Status:
    OK = "ok"
    LIST = "list"
    EMPTY = "empty"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


# ---------- Action verbs (ok responses) ----------


class Action:
    """Action values match the tool registry names in registry.py."""

    # Expenses
    ADD_EXPENSE = "add_expense"
    DELETE_EXPENSE = "delete_expense"
    UPDATE_EXPENSE = "update_expense"
    GET_BALANCES = "get_balances"
    SETTLE_EXPENSE = "settle_expense"

    # Reminders
    SET_REMINDER = "set_reminder"
    CANCEL_REMINDER = "cancel_reminder"
    SNOOZE_REMINDER = "snooze_reminder"
    SET_TIMEZONE = "set_timezone"

    # Notes
    SAVE_NOTE = "save_note"
    DELETE_NOTE = "delete_note"

    # Itinerary
    ADD_ITINERARY = "add_itinerary"
    REMOVE_ITINERARY = "remove_itinerary"

    # Checklist
    ADD_ITEM = "add_item"
    CHECK_ITEM = "check_item"
    UNCHECK_ITEM = "uncheck_item"
    DELETE_ITEM = "delete_item"

    # Status
    GET_STATUS = "get_status"


# ---------- Error reasons ----------


class Reason:
    # Shared
    MISSING_IDENTIFIER = "missing_identifier"
    INTERNAL_ERROR = "internal_error"

    # Expenses
    MISSING_AMOUNT = "missing_amount"
    MISSING_SETTLEMENT_PAYEE = "missing_settlement_payee"
    NOTHING_TO_UPDATE = "nothing_to_update"
    PAYER_NOT_FOUND = "payer_not_found"
    PAYEE_NOT_FOUND = "payee_not_found"
    PARTICIPANTS_NOT_FOUND = "participants_not_found"
    PARTICIPANTS_EXCEED_TOTAL = "participants_exceed_total"
    NEGATIVE_AMOUNT = "negative_amount"
    INVALID_CURRENCY = "invalid_currency"

    # Reminders
    MISSING_DESCRIPTION = "missing_description"
    MISSING_TIME = "missing_time"
    MISSING_DURATION = "missing_duration"
    UNPARSEABLE_TIME = "unparseable_time"
    UNPARSEABLE_DURATION = "unparseable_duration"
    INVALID_TIMEZONE = "invalid_timezone"

    # Itinerary
    MISSING_ITEMS = "missing_items"


# ---------- Entity names ----------


class Entity:
    EXPENSE = "expense"
    EXPENSES = "expenses"
    REMINDER = "reminder"
    REMINDERS = "reminders"
    NOTE = "note"
    NOTES = "notes"
    ITINERARY = "itinerary"
    ITINERARY_ITEM = "itinerary_item"
    CHECKLIST_ITEM = "checklist_item"
    CHECKLIST_ITEMS = "checklist_items"
    GROUP_DATA = "group_data"


# ---------- Response builders ----------


def ok_response(action: str, **data: Any) -> dict:
    """Success response."""
    return {"status": Status.OK, "action": action, **data}


def list_response(entity: str, items: list) -> dict:
    """List response. The key name matches the entity plural."""
    return {"status": Status.LIST, entity: items}


def empty_response(entity: str) -> dict:
    """Empty collection response."""
    return {"status": Status.EMPTY, "entity": entity}


def not_found_response(
    entity: str,
    *,
    number: int | None = None,
    total: int | None = None,
    query: str | None = None,
) -> dict:
    """Item not found response."""
    d: dict = {"status": Status.NOT_FOUND, "entity": entity}
    if number is not None:
        d["number"] = number
        d["total"] = total or 0
    if query is not None:
        d["query"] = query
    return d


def ambiguous_response(entity: str, matches: list, **extra: Any) -> dict:
    """Multiple matches — user must disambiguate."""
    return {"status": Status.AMBIGUOUS, "entity": entity, "matches": matches, **extra}


def error_response(reason: str, **details: Any) -> dict:
    """Error response."""
    return {"status": Status.ERROR, "reason": reason, **details}
