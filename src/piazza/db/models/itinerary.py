"""ItineraryItem model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.db.base import Base


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"
    __table_args__ = (
        Index("idx_itinerary_group", "group_id", "start_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    location: Mapped[str | None] = mapped_column(Text, default=None)
    location_url: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="itinerary_items")  # noqa: F821
