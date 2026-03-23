"""Group model."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.db.base import Base, TimestampMixin


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    wa_jid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_encrypted: Mapped[bytes | None] = mapped_column(default=None)
    timezone: Mapped[str] = mapped_column(Text, default="UTC")
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    approval_status: Mapped[str] = mapped_column(
        Text, default="pending", server_default="pending"
    )
    # Relationships
    members: Mapped[list["Member"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
    settlements: Mapped[list["Settlement"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
    itinerary_items: Mapped[list["ItineraryItem"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
