"""Application constants."""

# Rate limit constants
RATE_LIMIT_USER_PER_GROUP = 20  # per hour
RATE_LIMIT_GROUP_TOTAL = 100  # per 24 hours
RATE_LIMIT_GROUP_LLM = 30  # per hour
RATE_LIMIT_GLOBAL_LLM = 500  # per hour
RATE_LIMIT_NOTIFY_COOLDOWN = 300  # 5 minutes in seconds

# Circuit breaker constants
CIRCUIT_BREAKER_FAILURES = 3
CIRCUIT_BREAKER_WINDOW = 120  # 2 minutes in seconds
CIRCUIT_BREAKER_COOLDOWN = 600  # 10 minutes in seconds

# Input sanitization
MAX_MESSAGE_LENGTH = 500

# Supported currencies
SUPPORTED_CURRENCIES = frozenset({
    "EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK",
    "PLN", "CZK", "HUF", "RON", "BGN", "HRK", "TRY",
    "JPY", "CNY", "KRW", "INR", "AUD", "CAD", "NZD",
    "BRL", "MXN", "ARS", "CLP", "COP", "PEN",
    "ZAR", "EGP", "NGN", "KES", "MAD",
    "AED", "SAR", "QAR", "KWD", "BHD",
    "SGD", "HKD", "TWD", "THB", "MYR", "IDR", "PHP", "VND",
})

DEFAULT_CURRENCY = "EUR"
