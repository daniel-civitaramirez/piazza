"""Expense, ExpenseParticipant, and Settlement models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from piazza.db.base import Base


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("idx_expenses_group", "group_id", postgresql_where="NOT is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, default="EUR")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str | None] = mapped_column(Text, default=None)
    split_type: Mapped[str] = mapped_column(Text, default="even")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="expenses")  # noqa: F821
    payer: Mapped["Member"] = relationship()  # noqa: F821
    participants: Mapped[list["ExpenseParticipant"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )


class ExpenseParticipant(Base):
    __tablename__ = "expense_participants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id"), nullable=False
    )
    share_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="participants")
    member: Mapped["Member"] = relationship()  # noqa: F821


class Settlement(Base):
    __tablename__ = "settlements"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id"), nullable=False
    )
    payee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="settlements")  # noqa: F821
    payer: Mapped["Member"] = relationship(foreign_keys=[payer_id])  # noqa: F821
    payee: Mapped["Member"] = relationship(foreign_keys=[payee_id])  # noqa: F821
