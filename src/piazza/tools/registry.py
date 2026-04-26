"""Tool definitions and executor.

Tools are defined in Anthropic format (canonical). The OpenSourceAgent converts
to OpenAI format internally. Each tool maps to an existing handler function.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import PiazzaError
from piazza.tools.checklist.handler import (
    handle_item_add,
    handle_item_check,
    handle_item_delete,
    handle_item_list,
    handle_item_uncheck,
)
from piazza.tools.expenses.handler import (
    handle_expense_add,
    handle_expense_balance,
    handle_expense_delete,
    handle_expense_list,
    handle_expense_settle,
    handle_expense_update,
)
from piazza.tools.itinerary.handler import (
    handle_itinerary_add,
    handle_itinerary_remove,
    handle_itinerary_show,
)
from piazza.tools.notes.handler import (
    handle_note_delete,
    handle_note_find,
    handle_note_list,
    handle_note_save,
)
from piazza.tools.reminders.handler import (
    handle_reminder_cancel,
    handle_reminder_list,
    handle_reminder_set,
    handle_reminder_snooze,
    handle_set_timezone,
)
from piazza.tools.responses import Reason, error_response
from piazza.tools.schemas import Entities
from piazza.tools.search.handler import handle_search_group
from piazza.tools.status.status import handle_status

logger = structlog.get_logger()

HandlerFunc = Callable[
    [AsyncSession, uuid.UUID, uuid.UUID, Entities],
    Awaitable[dict],
]


@dataclass
class ToolResult:
    """Structured result from a tool handler."""

    success: bool
    response_text: str  # JSON-serialized dict


# --- Tool definitions (Anthropic format) ---

AGENT_TOOLS: list[dict] = [
    {
        "name": "add_expense",
        "description": (
            "Record a shared expense."
            " Set paid_by to the sender's name unless someone else paid."
            " The expense is stored in its own currency; mixed-currency"
            " groups are normal and supported."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "number",
                    "description": "Amount in major currency units",
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO-4217 code (EUR, USD, GBP, etc.)."
                        " Omit to use the group's default currency."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "What the expense was for",
                },
                "paid_by": {
                    "type": "string",
                    "description": (
                        "Display name of the payer"
                        " (use the sender's name if they paid)"
                    ),
                },
                "participants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Display name"},
                            "amount": {"type": "number", "description": "Amount owed"},
                        },
                        "required": ["name", "amount"],
                    },
                    "description": (
                        "Each person who owes the payer and how much."
                        " Payer is never included."
                    ),
                },
            },
            "required": ["amount", "paid_by", "participants"],
        },
    },
    {
        "name": "get_balances",
        "description": (
            "Show who owes whom in the group."
            " Default response groups debts by currency (one debt list per"
            " ISO-4217 code) so mixed-currency groups stay mathematically"
            " honest."
            " Pass `currency` to additionally receive a single-currency"
            " consolidated view computed at today's live FX rate."
            " If the response carries `fx_unavailable: true`, FX rates"
            " could not be fetched — relay the per-currency view to the"
            " user and tell them conversion is temporarily unavailable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO-4217 code (e.g. EUR, USD) to consolidate the"
                        " mixed-currency balance into a single view."
                    ),
                },
            },
        },
    },
    {
        "name": "settle_expense",
        "description": (
            "Record a settlement payment between members."
            " The settlement is stored in whatever currency the user"
            " actually paid in — settling in a currency that differs from"
            " the outstanding debt is supported. To inspect the resulting"
            " cross-currency net, follow up with get_balances and pass"
            " the currency the user wants the answer in."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "participants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The member being paid (exactly one name)",
                },
                "amount": {
                    "type": "number",
                    "description": "Settlement amount",
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO-4217 code of the payment."
                        " Omit to use the group's default currency."
                    ),
                },
            },
            "required": ["amount", "participants"],
        },
    },
    {
        "name": "delete_expense",
        "description": "Delete an expense by its list number or by matching its description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_expenses (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to identify the expense to delete",
                },
            },
        },
    },
    {
        "name": "update_expense",
        "description": (
            "Update a previously logged expense."
            " Changing only `currency` converts the stored amount at"
            " today's FX rate so the real value is preserved."
            " Supplying both `amount` and `currency` re-states the expense"
            " verbatim with the user's number — no FX conversion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_expenses (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to identify the expense to update",
                },
                "amount": {
                    "type": "number",
                    "description": "New amount (if changing)",
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "New currency code (if changing). When changed without"
                        " a new amount, the stored amount is converted at"
                        " today's FX rate so the real value is preserved."
                    ),
                },
                "new_description": {
                    "type": "string",
                    "description": "New description (if renaming)",
                },
                "paid_by": {
                    "type": "string",
                    "description": "New payer display name (if changing who paid)",
                },
                "participants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Display name"},
                            "amount": {"type": "number", "description": "Amount owed"},
                        },
                        "required": ["name", "amount"],
                    },
                    "description": (
                        "New split — each person who owes the payer and how much."
                        " Payer is never included."
                    ),
                },
            },
        },
    },
    {
        "name": "list_expenses",
        "description": "List recent expenses for the group.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_reminder",
        "description": "Set a one-time or recurring reminder for the group.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What to remind about",
                },
                "datetime_raw": {
                    "type": "string",
                    "description": (
                        "When the first/next reminder fires, in natural language"
                        " (e.g. 'tomorrow 6am', 'in 2 hours')."
                        " Optional when recurrence is provided — the next"
                        " occurrence will be derived from the rule."
                    ),
                },
                "recurrence": {
                    "type": "string",
                    "description": (
                        "Optional iCalendar RRULE for repeating reminders."
                        " Examples: 'FREQ=DAILY;BYHOUR=10;BYMINUTE=0' (daily at 10:00),"
                        " 'FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0' (every Monday 9am),"
                        " 'FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=9;BYMINUTE=0' (1st of every month 9am)."
                        " Omit for one-time reminders."
                    ),
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List active reminders for the group.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a reminder by its list number or by matching text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_reminders (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to match against the reminder message (e.g. 'dentist')",
                },
            },
        },
    },
    {
        "name": "snooze_reminder",
        "description": "Snooze a reminder by its list number or by matching text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_reminders (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to match against the reminder message (e.g. 'dentist')",
                },
                "datetime_raw": {
                    "type": "string",
                    "description": "Snooze duration (e.g. '1h', '30m')",
                },
            },
            "required": ["datetime_raw"],
        },
    },
    {
        "name": "add_itinerary",
        "description": "Add one or more items to the group's shared itinerary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Structured itinerary items to add",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Item title"},
                            "item_type": {
                                "type": "string",
                                "enum": ["flight", "hotel", "restaurant", "activity", "transport"],
                                "description": "Type of itinerary item",
                            },
                            "start_at": {
                                "type": "string",
                                "description": "Start datetime in ISO 8601 format",
                            },
                            "end_at": {
                                "type": "string",
                                "description": "End datetime in ISO 8601 format",
                            },
                            "location": {"type": "string", "description": "Location or venue"},
                            "notes": {"type": "string", "description": "Additional notes"},
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "show_itinerary",
        "description": "Show the group's itinerary.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remove_itinerary",
        "description": "Remove an item from the itinerary by its list number or by matching text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from show_itinerary (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Identifying text of the item to remove",
                },
            },
        },
    },
    {
        "name": "save_note",
        "description": "Save information to the group's shared knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "The information to save",
                },
                "tag": {
                    "type": "string",
                    "description": (
                        "Short label/category"
                        " (e.g. 'wifi password', 'booking ref')"
                    ),
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "find_note",
        "description": "Search the group's saved notes and knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Search keywords",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "list_notes",
        "description": "List all saved notes for the group.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_note",
        "description": "Delete a note by its list number or by matching its content/tag.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_notes (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Identifying text of the note to delete",
                },
            },
        },
    },
    {
        "name": "add_item",
        "description": "Add an item to a shared checklist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "The item to add",
                },
                "list_name": {
                    "type": "string",
                    "description": (
                        "Name of the list (e.g. 'shopping', 'packing')."
                        " Defaults to 'default' if omitted."
                    ),
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "list_items",
        "description": "Show items on a shared checklist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": "Filter by list name. Omit to show all lists.",
                },
                "show_done": {
                    "type": "boolean",
                    "description": (
                        "Set true when user asks for completed/checked-off items,"
                        " the full list, or 'everything'. Default false (pending only)."
                    ),
                },
            },
        },
    },
    {
        "name": "check_item",
        "description": "Mark a checklist item as done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_items (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to match against the item content",
                },
            },
        },
    },
    {
        "name": "uncheck_item",
        "description": "Mark a checklist item as not done.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_items (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to match against the item content",
                },
            },
        },
    },
    {
        "name": "delete_item",
        "description": "Remove an item from a shared checklist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_number": {
                    "type": "integer",
                    "description": "Position number from list_items (e.g. 2 for #2)",
                },
                "description": {
                    "type": "string",
                    "description": "Text to match against the item content",
                },
            },
        },
    },
    {
        "name": "set_timezone",
        "description": "Set the group's timezone for reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "Timezone name"
                        " (e.g. 'Europe/Paris', 'America/New_York')"
                    ),
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "get_status",
        "description": "Show group statistics (expense count, active reminders, etc.).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_group",
        "description": (
            "Search across all group data — expenses, reminders, itinerary,"
            " checklists, and notes. Returns matching items grouped by type."
            " Omit description to get an overview of everything the group has saved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Search keywords. Omit to list all items from every domain.",
                },
            },
        },
    },
]

# --- Tool registry: maps tool names to handler functions ---

TOOL_REGISTRY: dict[str, HandlerFunc] = {
    "add_expense": handle_expense_add,
    "get_balances": handle_expense_balance,
    "settle_expense": handle_expense_settle,
    "delete_expense": handle_expense_delete,
    "update_expense": handle_expense_update,
    "list_expenses": handle_expense_list,
    "set_reminder": handle_reminder_set,
    "list_reminders": handle_reminder_list,
    "cancel_reminder": handle_reminder_cancel,
    "snooze_reminder": handle_reminder_snooze,
    "add_itinerary": handle_itinerary_add,
    "show_itinerary": handle_itinerary_show,
    "remove_itinerary": handle_itinerary_remove,
    "save_note": handle_note_save,
    "find_note": handle_note_find,
    "list_notes": handle_note_list,
    "delete_note": handle_note_delete,
    "add_item": handle_item_add,
    "list_items": handle_item_list,
    "check_item": handle_item_check,
    "uncheck_item": handle_item_uncheck,
    "delete_item": handle_item_delete,
    "set_timezone": handle_set_timezone,
    "get_status": handle_status,
    "search_group": handle_search_group,
}


async def execute_tool(
    name: str,
    arguments: dict,
    session: AsyncSession,
    group_id: uuid.UUID,
    member_id: uuid.UUID,
) -> ToolResult:
    """Execute a tool call by mapping it to a handler function."""
    handler = TOOL_REGISTRY.get(name)
    if handler is None:
        return ToolResult(
            success=False,
            response_text=json.dumps(error_response(Reason.INTERNAL_ERROR, tool=name)),
        )

    try:
        entities = Entities(**arguments)
        result_dict = await handler(session, group_id, member_id, entities)
        return ToolResult(success=True, response_text=json.dumps(result_dict))
    except PiazzaError as exc:
        logger.warning("tool_domain_error", tool=name, error=str(exc))
        return ToolResult(
            success=False,
            response_text=json.dumps(error_response(Reason.INTERNAL_ERROR, detail=str(exc))),
        )
    except Exception:
        logger.exception("tool_execution_error", tool=name)
        return ToolResult(
            success=False,
            response_text=json.dumps(error_response(Reason.INTERNAL_ERROR)),
        )
