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
