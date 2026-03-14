"""LLM prompt templates loaded from text files."""

from pathlib import Path

_DIR = Path(__file__).parent


def _load(name: str) -> str:
    return (_DIR / name).read_text().strip()


ITINERARY_EXTRACTION_PROMPT: str = _load("itinerary_extraction.txt")
