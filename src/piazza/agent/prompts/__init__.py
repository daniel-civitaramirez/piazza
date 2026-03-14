"""Agent prompt templates loaded from text files."""

from pathlib import Path

_DIR = Path(__file__).parent


def _load(name: str) -> str:
    return (_DIR / name).read_text().strip()


AGENT_SYSTEM_PROMPT: str = _load("system.txt")
