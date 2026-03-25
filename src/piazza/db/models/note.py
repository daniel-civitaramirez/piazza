"""Note model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.db.base import Base


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("idx_notes_group", "group_id", "created_at"),
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
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    tag: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="notes")  # noqa: F821
