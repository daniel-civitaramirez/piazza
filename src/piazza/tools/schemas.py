"""Shared data models for tool arguments."""

from __future__ import annotations

from pydantic import BaseModel


class Entities(BaseModel):
    amount: float | None = None
    currency: str | None = None
    description: str | None = None
    paid_by: str | None = None
    participants: list[str] | None = None
    datetime_raw: str | None = None
    tag: str | None = None
    items: list[dict] | None = None
    reminder_number: int | None = None
    new_description: str | None = None
