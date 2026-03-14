"""Reminder model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.db.base import Base


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index(
            "idx_reminders_pending",
            "trigger_at",
            "status",
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recurrence: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="reminders")  # noqa: F821
    creator: Mapped["Member"] = relationship()  # noqa: F821
