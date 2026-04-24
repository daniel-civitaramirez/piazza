"""Custom exception hierarchy."""


class PiazzaError(Exception):
    """Base exception for all Piazza errors."""


# Shared user-facing error response strings
GENERIC_ERROR_RESPONSE = "Something went wrong. Please try again."
FLAGGED_RESPONSE = (
    "Your message was flagged for safety reasons. "
    "Please try rephrasing your request."
)
UNAPPROVED_GROUP_RESPONSE = (
    "This group hasn't been approved yet. "
    "The admin has been notified and will review it shortly."
)
RATE_LIMITED_RESPONSE = (
    "This group is sending too many requests. "
    "Please wait a moment and try again."
)
WELCOME_MESSAGE = (
    "Hi! I'm Piazza, a productivity assistant for this group.\n\n"
    "*What I can help with:*\n"
    "- *Expenses*: log expenses, split bills, check balances, settle up\n"
    "- *Reminders*: one-time or recurring\n"
    "- *Notes*: save shared info (wifi, booking refs) and search them\n"
    "- *Checklists*: shared lists you can check off\n"
    "- *Itinerary*: flights, hotels, restaurants, activities\n\n"
    "*How to talk to me:*\n"
    "- @mention me, or reply directly to one of my messages.\n"
    "- I do not read any other messages in this chat — your other "
    "conversations stay private."
)


class NotFoundError(PiazzaError):
    """Item not found by number or search query."""

    def __init__(
        self,
        entity: str,
        *,
        number: int | None = None,
        total: int | None = None,
        query: str | None = None,
    ) -> None:
        self.entity = entity
        self.number = number
        self.total = total
        self.query = query
        super().__init__(f"{entity} not found")


class ExpenseError(PiazzaError):
    """Error in expense processing."""


class ReminderError(PiazzaError):
    """Error in reminder processing."""


class WhatsAppSendError(PiazzaError):
    """WhatsApp message delivery failed after retries."""
