"""Injection log model for tracking detected injection attempts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from piazza.db.base import Base


class InjectionLog(Base):
    __tablename__ = "injection_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_hash: Mapped[str] = mapped_column(String(64), index=True)
    layer: Mapped[str] = mapped_column(String(10))  # "L1" or "L2"
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
