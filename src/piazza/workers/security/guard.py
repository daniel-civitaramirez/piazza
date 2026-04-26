"""ML-based prompt injection screening — Layer 2 of defense."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

# Attempt to load llm-guard's PromptInjection scanner.
# Falls back to heuristic scoring if the import fails (e.g. transformers compat).
_scanner = None
_SCANNER_AVAILABLE = False

try:
    from llm_guard.input_scanners import PromptInjection

    _scanner = PromptInjection(threshold=0.85)
    _SCANNER_AVAILABLE = True
    logger.info("llm_guard_scanner_loaded")
except Exception as exc:
    logger.warning("llm_guard_unavailable", error=str(exc))


# Heuristic signals used when ML scanner is unavailable.
# Each (pattern, weight) pair contributes to a risk score [0..1].
_HEURISTIC_SIGNALS: list[tuple[str, float]] = [
    ("ignore", 0.15),
    ("instruction", 0.15),
    ("system prompt", 0.25),
    ("you are now", 0.20),
    ("pretend", 0.15),
    ("act as", 0.12),
    ("jailbreak", 0.30),
    ("DAN", 0.25),
    ("bypass", 0.15),
    ("override", 0.15),
    ("unrestricted", 0.20),
    ("reveal your", 0.20),
    ("admin mode", 0.20),
    ("developer mode", 0.20),
    ("ignore previous", 0.30),
    ("disregard", 0.15),
    ("forget your", 0.20),
]

_HEURISTIC_THRESHOLD = 0.95


def _heuristic_score(text: str) -> float:
    """Compute a heuristic injection risk score from keyword signals."""
    text_lower = text.lower()
    score = 0.0
    for keyword, weight in _HEURISTIC_SIGNALS:
        if keyword in text_lower:
            score += weight
    return min(score, 1.0)


def screen_for_injection(text: str) -> tuple[str, bool, float]:
    """Screen input for prompt injection using ML model or heuristic fallback.

    Returns:
        Tuple of (sanitized_text, is_injection, risk_score).
        risk_score is between 0.0 and 1.0.
    """
    if _SCANNER_AVAILABLE and _scanner is not None:
        try:
            sanitized, is_valid, risk_score = _scanner.scan(text)
            is_injection = not is_valid
            logger.info(
                "guard_ml_scan",
                is_injection=is_injection,
                risk_score=risk_score,
            )
            return sanitized, is_injection, risk_score
        except Exception as exc:
            logger.warning("guard_ml_scan_error", error=str(exc))
            # Fall through to heuristic

    # Heuristic fallback
    risk_score = _heuristic_score(text)
    is_injection = risk_score >= _HEURISTIC_THRESHOLD
    logger.info(
        "guard_heuristic_scan",
        is_injection=is_injection,
        risk_score=risk_score,
    )
    return text, is_injection, risk_score
