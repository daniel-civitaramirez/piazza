"""Group model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.config.settings import APPROVAL_PENDING
from piazza.db.base import Base, TimestampMixin


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    wa_jid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_encrypted: Mapped[bytes | None] = mapped_column(default=None)
    timezone: Mapped[str] = mapped_column(Text, default="UTC")
    approval_status: Mapped[str] = mapped_column(
        Text, default=APPROVAL_PENDING, server_default=APPROVAL_PENDING
    )
    welcome_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
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
    checklist_items: Mapped[list["ChecklistItem"]] = relationship(  # noqa: F821
        back_populates="group", cascade="all, delete-orphan"
    )
