"""Custom exception hierarchy."""


class PiazzaError(Exception):
    """Base exception for all Piazza errors."""


# Shared user-facing error response strings
GENERIC_ERROR_RESPONSE = "Something went wrong. Please try again."
FLAGGED_RESPONSE = (
    "Your message was flagged for safety reasons. "
    "Please try rephrasing your request."
)
TOO_MANY_ACTIONS_RESPONSE = (
    "That's too many requests at once! "
    "I can handle up to 5 tasks per message. "
    "Please split your requests into smaller messages."
)
UNAPPROVED_GROUP_RESPONSE = (
    "This group hasn't been approved yet. "
    "The admin has been notified and will review it shortly."
)


class ExpenseError(PiazzaError):
    """Error in expense processing."""


class ReminderError(PiazzaError):
    """Error in reminder processing."""


class WhatsAppSendError(PiazzaError):
    """WhatsApp message delivery failed after retries."""
