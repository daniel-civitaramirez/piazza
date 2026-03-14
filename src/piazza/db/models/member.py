"""Member model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.db.base import Base


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("group_id", "wa_id_hash", name="uq_member_group_wa"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    wa_id_hash: Mapped[str] = mapped_column(Text, nullable=False)
    wa_id_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="members")  # noqa: F821
