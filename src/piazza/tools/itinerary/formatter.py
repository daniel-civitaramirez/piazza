"""Itinerary response formatters (WhatsApp markdown)."""

from __future__ import annotations

from collections import defaultdict

from piazza.db.models.itinerary import ItineraryItem

TYPE_EMOJI = {
    "flight": "\u2708\ufe0f",
    "hotel": "\U0001f3e8",
    "restaurant": "\U0001f37d\ufe0f",
    "activity": "\U0001f3a8",
    "transport": "\U0001f697",
}


def _emoji(item_type: str) -> str:
    return TYPE_EMOJI.get(item_type, "\U0001f4cc")


def format_item_confirmation(items: list[ItineraryItem]) -> str:
    """Format confirmation for added items."""
    if not items:
        return "No items added."

    lines = []
    for item in items:
        line = f"{_emoji(item.item_type)} Added: *{item.title}*"
        if item.start_at:
            time_str = item.start_at.strftime("%b %d, %H:%M")
            if item.end_at:
                time_str += f"\u2013{item.end_at.strftime('%H:%M')}"
            line += f" \u2014 {time_str}"
        if item.location:
            line += f"\n   {item.location}"
        lines.append(line)

    return "\n".join(lines)


def format_full_itinerary(items: list[ItineraryItem]) -> str:
    """Format the full itinerary grouped by day.

    Items are numbered with a flat counter matching get_items() ordering,
    so users can reference them by number (e.g. "remove itinerary #3").
    """
    if not items:
        return "No itinerary items yet. Add some with _@Piazza add to itinerary:_"

    # Group by date, preserving flat index for item_number references
    by_day: dict[str, list[tuple[int, ItineraryItem]]] = defaultdict(list)
    no_date: list[tuple[int, ItineraryItem]] = []

    for i, item in enumerate(items, 1):
        if item.start_at:
            day_key = item.start_at.strftime("%A, %B %d")
            by_day[day_key].append((i, item))
        else:
            no_date.append((i, item))

    lines = ["*Trip Itinerary*\n"]

    for day, day_items in by_day.items():
        lines.append(f"*{day}*")
        for i, item in day_items:
            time_str = item.start_at.strftime("%H:%M") if item.start_at else ""
            entry = f"#{i} {time_str}  {_emoji(item.item_type)} {item.title}"
            if item.location:
                entry += f" ({item.location})"
            lines.append(entry)
        lines.append("")

    if no_date:
        lines.append("*Unscheduled*")
        for i, item in no_date:
            lines.append(f"#{i} {_emoji(item.item_type)} {item.title}")

    return "\n".join(lines).strip()


def format_disambiguation(matches: list[ItineraryItem]) -> str:
    """Format disambiguation message for ambiguous removals."""
    lines = ["Multiple items match. Use show_itinerary to find the item number:\n"]
    for item in matches:
        line = f"• {_emoji(item.item_type)} {item.title}"
        if item.start_at:
            line += f" ({item.start_at.strftime('%b %d, %H:%M')})"
        lines.append(line)
    return "\n".join(lines)
