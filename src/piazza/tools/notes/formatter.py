"""Notes response formatters (WhatsApp markdown)."""

from __future__ import annotations

from piazza.db.models.note import Note


def format_save_confirmation(note: Note) -> str:
    """Format confirmation for a saved note."""
    if note.tag:
        return f"\U0001f4cc Saved: *{note.tag}* \u2014 {note.content}"
    return f"\U0001f4cc Saved: {note.content}"


def format_note_list(notes: list[Note]) -> str:
    """Format a numbered list of all notes."""
    if not notes:
        return "No notes saved yet. Try: _@Piazza save: wifi password is BeachLife2026_"

    lines = ["*Saved Notes*\n"]
    for i, note in enumerate(notes, 1):
        if note.tag:
            lines.append(f"{i}. *{note.tag}* \u2014 {note.content}")
        else:
            lines.append(f"{i}. {note.content}")
    return "\n".join(lines)


def format_search_results(notes: list[Note]) -> str:
    """Format search results."""
    if not notes:
        return "No matching notes found."

    if len(notes) == 1:
        note = notes[0]
        if note.tag:
            return f"\U0001f4cc *{note.tag}* \u2014 {note.content}"
        return f"\U0001f4cc {note.content}"

    lines = [f"Found {len(notes)} matching notes:\n"]
    for i, note in enumerate(notes, 1):
        if note.tag:
            lines.append(f"{i}. *{note.tag}* \u2014 {note.content}")
        else:
            lines.append(f"{i}. {note.content}")
    return "\n".join(lines)


def format_delete_confirmation(note: Note) -> str:
    """Format confirmation for a deleted note."""
    if note.tag:
        return f"Deleted: *{note.tag}* \u2014 {note.content}"
    return f"Deleted: {note.content}"


def format_disambiguation(notes: list[Note]) -> str:
    """Format disambiguation message for ambiguous deletes."""
    lines = ["Multiple notes match. Use list_notes to find the item number:\n"]
    for note in notes:
        if note.tag:
            lines.append(f"• *{note.tag}* \u2014 {note.content}")
        else:
            lines.append(f"• {note.content}")
    return "\n".join(lines)
