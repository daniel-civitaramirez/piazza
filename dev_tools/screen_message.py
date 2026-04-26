"""Interactive CLI for tuning the L1 + L2 security pipeline.

Usage:
    uv run python dev_tools/screen_message.py

Type a message, press ENTER, see the L1 verdict, L2 verdict, and L2 risk score.
Mirrors workers/process_message.py:170-178 exactly. Ctrl-D / Ctrl-C to exit.
"""

from __future__ import annotations

from piazza.workers.security import guard
from piazza.workers.security.guard import screen_for_injection
from piazza.workers.security.sanitizer import _ensure_patterns_loaded, sanitize_input


def _l2_threshold() -> float:
    """Return the live L2 threshold for whichever scanner is active."""
    if guard._SCANNER_AVAILABLE and guard._scanner is not None:
        return float(getattr(guard._scanner, "_threshold", guard._HEURISTIC_THRESHOLD))
    return guard._HEURISTIC_THRESHOLD


def _screen(text: str, threshold: float) -> None:
    sanitized, flagged_l1 = sanitize_input(text)
    _, flagged_l2, risk = screen_for_injection(sanitized)

    l1 = "BLOCK" if flagged_l1 else "pass"
    l2 = "BLOCK" if flagged_l2 else "pass"
    print(f"  L1: {l1}")
    print(f"  L2: {l2}    risk={risk:.3f}    threshold={threshold:.3f}")
    print(f"  -> {'BLOCKED' if (flagged_l1 or flagged_l2) else 'PASSES to agent'}")


def main() -> None:
    patterns = _ensure_patterns_loaded()
    scanner = "llm-guard ML model" if guard._SCANNER_AVAILABLE else "heuristic fallback"
    threshold = _l2_threshold()
    print(f"L1 patterns: {len(patterns)}    L2 scanner: {scanner}    threshold: {threshold:.3f}")
    print("Type a message and press ENTER. Ctrl-D to exit.")
    print("=" * 60)

    try:
        while True:
            text = input("> ").strip()
            if text:
                _screen(text, threshold)
    except (EOFError, KeyboardInterrupt):
        print()


if __name__ == "__main__":
    main()
