"""Expense database queries."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from piazza.db.models.expense import Expense, ExpenseParticipant, Settlement


async def create_expense(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    amount_cents: int,
    currency: str,
    description: str | None,
    category: str | None,
    split_type: str,
) -> Expense:
    """Create an expense record."""
    expense = Expense(
        group_id=group_id,
        payer_id=payer_id,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        category=category,
        split_type=split_type,
    )
    session.add(expense)
    await session.flush()
    return expense


async def create_expense_participants(
    session: AsyncSession,
    expense_id: uuid.UUID,
    shares: list[tuple[uuid.UUID, int]],
) -> None:
    """Create expense participant records."""
    for member_id, share_cents in shares:
        session.add(
            ExpenseParticipant(
                expense_id=expense_id,
                member_id=member_id,
                share_cents=share_cents,
            )
        )
    await session.flush()


async def replace_expense_participants(
    session: AsyncSession,
    expense_id: uuid.UUID,
    shares: list[tuple[uuid.UUID, int]],
) -> None:
    """Delete existing participants and create new ones."""
    await session.execute(
        delete(ExpenseParticipant).where(
            ExpenseParticipant.expense_id == expense_id
        )
    )
    for member_id, share_cents in shares:
        session.add(
            ExpenseParticipant(
                expense_id=expense_id,
                member_id=member_id,
                share_cents=share_cents,
            )
        )
    await session.flush()


async def get_expenses(
    session: AsyncSession, group_id: uuid.UUID, limit: int = 10
) -> list[Expense]:
    """Get recent non-deleted expenses for a group."""
    result = await session.execute(
        select(Expense)
        .options(
            selectinload(Expense.payer),
            selectinload(Expense.participants).selectinload(
                ExpenseParticipant.member
            ),
        )
        .where(Expense.group_id == group_id, Expense.is_deleted == False)  # noqa: E712
        .order_by(Expense.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def find_expenses_by_description(
    session: AsyncSession, group_id: uuid.UUID, description: str
) -> list[Expense]:
    """Find non-deleted expenses matching description (case-insensitive)."""
    result = await session.execute(
        select(Expense)
        .options(
            selectinload(Expense.payer),
            selectinload(Expense.participants).selectinload(
                ExpenseParticipant.member
            ),
        )
        .where(
            Expense.group_id == group_id,
            Expense.is_deleted == False,  # noqa: E712
            Expense.description.ilike(f"%{description}%"),
        )
        .order_by(Expense.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_last_expense(
    session: AsyncSession, group_id: uuid.UUID
) -> Expense | None:
    """Soft-delete the most recent non-deleted expense. Returns it or None."""
    result = await session.execute(
        select(Expense)
        .where(Expense.group_id == group_id, Expense.is_deleted == False)  # noqa: E712
        .order_by(Expense.created_at.desc())
        .limit(1)
    )
    expense = result.scalar_one_or_none()
    if expense is not None:
        expense.is_deleted = True
        await session.flush()
    return expense


async def get_expense_shares(
    session: AsyncSession, group_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
    """Get (payer_id, participant_member_id, share_cents) for all active expenses."""
    result = await session.execute(
        select(Expense.payer_id, ExpenseParticipant.member_id, ExpenseParticipant.share_cents)
        .join(ExpenseParticipant, Expense.id == ExpenseParticipant.expense_id)
        .where(Expense.group_id == group_id, Expense.is_deleted == False)  # noqa: E712
    )
    return list(result.all())


async def get_settlements(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Settlement]:
    """Get all settlements for a group."""
    result = await session.execute(
        select(Settlement).where(Settlement.group_id == group_id)
    )
    return list(result.scalars().all())


async def create_settlement(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    payee_id: uuid.UUID,
    amount_cents: int,
) -> Settlement:
    """Record a settlement."""
    settlement = Settlement(
        group_id=group_id,
        payer_id=payer_id,
        payee_id=payee_id,
        amount_cents=amount_cents,
    )
    session.add(settlement)
    await session.flush()
    return settlement
