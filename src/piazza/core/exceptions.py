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


class ClassificationError(PiazzaError):
    """LLM failed to produce a valid classification."""


class LLMTimeoutError(PiazzaError):
    """LLM call timed out."""


class LLMUnavailableError(PiazzaError):
    """LLM service is unreachable."""


class RateLimitExceededError(PiazzaError):
    """Request was rate-limited."""


class InjectionDetectedError(PiazzaError):
    """Prompt injection was detected."""


class MemberNotFoundError(PiazzaError):
    """Could not resolve a member by name."""


class ExpenseError(PiazzaError):
    """Error in expense processing."""


class ReminderError(PiazzaError):
    """Error in reminder processing."""


class WhatsAppSendError(PiazzaError):
    """WhatsApp message delivery failed after retries."""
