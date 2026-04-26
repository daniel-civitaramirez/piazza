"""Currency code normalization.

All currency strings entering the system pass through `normalize` so that
storage, comparison, and FX lookups share a single canonical form: an
uppercase 3-letter ISO-4217 code (no surrounding whitespace).
"""

from __future__ import annotations

import re

_ISO_4217 = re.compile(r"^[A-Z]{3}$")


class InvalidCurrencyError(ValueError):
    """Raised when a string cannot be parsed as an ISO-4217 currency code."""


def normalize(code: str) -> str:
    """Return the canonical uppercase 3-letter form, or raise."""
    if not isinstance(code, str):
        raise InvalidCurrencyError(f"currency must be a string, got {type(code).__name__}")
    cleaned = code.strip().upper()
    if not _ISO_4217.match(cleaned):
        raise InvalidCurrencyError(f"invalid ISO-4217 currency code: {code!r}")
    return cleaned


def normalize_or(code: str | None, fallback: str) -> str:
    """Normalize `code` if given, otherwise normalize and return `fallback`."""
    if code is None or (isinstance(code, str) and not code.strip()):
        return normalize(fallback)
    return normalize(code)
