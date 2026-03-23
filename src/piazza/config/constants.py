"""Application constants."""

# Circuit breaker constants
CIRCUIT_BREAKER_FAILURES = 3
CIRCUIT_BREAKER_WINDOW = 120  # 2 minutes in seconds
CIRCUIT_BREAKER_COOLDOWN = 600  # 10 minutes in seconds

# Input sanitization
MAX_MESSAGE_LENGTH = 500

DEFAULT_CURRENCY = "EUR"
