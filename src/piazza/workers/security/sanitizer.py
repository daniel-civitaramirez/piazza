"""Input sanitization — Layer 1 of prompt injection defense."""

from __future__ import annotations

import json
import re
import unicodedata

import structlog

from piazza.config.settings import settings

logger = structlog.get_logger()

# Compiled patterns loaded once at module import time
_INJECTION_PATTERNS: list[re.Pattern[str]] = []


def _load_injection_patterns() -> list[re.Pattern[str]]:
    """Load and compile regex patterns from the injection patterns file."""
    path = settings.injection_patterns_path
    try:
        with open(path) as f:
            raw_patterns: list[str] = json.load(f)
        return [re.compile(p, re.IGNORECASE) for p in raw_patterns]
    except FileNotFoundError:
        logger.warning("injection_patterns_not_found", path=path)
        return []
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("injection_patterns_invalid", path=path, error=str(exc))
        return []


def _ensure_patterns_loaded() -> list[re.Pattern[str]]:
    """Lazy-load patterns on first use."""
    global _INJECTION_PATTERNS  # noqa: PLW0603
    if not _INJECTION_PATTERNS:
        _INJECTION_PATTERNS = _load_injection_patterns()
    return _INJECTION_PATTERNS


# Regex for HTML/XML tags
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Regex for code blocks (triple backticks with optional language)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def sanitize_input(text: str) -> tuple[str, bool]:
    """Sanitize user input and detect suspicious patterns.

    Steps:
    1. Unicode NFKC normalization (collapses homoglyphs)
    2. Truncate to MAX_MESSAGE_LENGTH
    3. Strip code blocks
    4. Strip HTML/XML tags
    5. Check against loaded injection patterns

    Returns:
        Tuple of (sanitized_text, is_suspicious).
    """
    # Step 1: Unicode NFKC normalize (collapses homoglyphs like ⅰ→i)
    sanitized = unicodedata.normalize("NFKC", text)

    # Step 2: Truncate
    sanitized = sanitized[:settings.max_message_length]

    # Step 3: Strip code blocks
    sanitized = _CODE_BLOCK_RE.sub("[code block removed]", sanitized)

    # Step 4: Strip HTML/XML tags
    sanitized = _HTML_TAG_RE.sub("", sanitized)

    # Step 5: Check against injection patterns
    patterns = _ensure_patterns_loaded()
    is_suspicious = False
    for pattern in patterns:
        if pattern.search(sanitized):
            is_suspicious = True
            logger.warning(
                "injection_pattern_matched",
                pattern=pattern.pattern,
            )
            break

    return sanitized, is_suspicious
