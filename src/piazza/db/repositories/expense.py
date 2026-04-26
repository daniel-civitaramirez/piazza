"""Expense database queries."""

from __future__ import annotations

import uuid

from rapidfuzz import fuzz, process, utils
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from piazza.config.settings import settings
from piazza.core.encryption import decrypt, decrypt_nullable, encrypt_nullable, set_decrypted
from piazza.db.models.expense import Expense, ExpenseParticipant, Settlement


def _key() -> bytes:
    return settings.encryption_key_bytes


def _decrypt_expense(exp: Expense, key: bytes) -> None:
    set_decrypted(exp, "description", decrypt_nullable(exp.description, key))
    if exp.payer:
        set_decrypted(exp.payer, "display_name", decrypt(exp.payer.display_name, key))
    for p in (exp.participants or []):
        if p.member:
            set_decrypted(p.member, "display_name", decrypt(p.member.display_name, key))


async def create_expense(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    amount_cents: int,
    currency: str,
    description: str | None,
) -> Expense:
    """Create an expense record."""
    key = _key()
    expense = Expense(
        group_id=group_id,
        payer_id=payer_id,
        amount_cents=amount_cents,
        currency=currency,
        description=encrypt_nullable(description, key),  # type: ignore[assignment]
    )
    session.add(expense)
    await session.flush()
    set_decrypted(expense, "description", description)
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
    expenses = list(result.scalars().all())
    key = _key()
    for exp in expenses:
        _decrypt_expense(exp, key)
    return expenses


async def find_expenses_by_description(
    session: AsyncSession, group_id: uuid.UUID, description: str
) -> list[Expense]:
    """Find non-deleted expenses fuzzy-matching description, ranked best-first.

    Uses rapidfuzz WRatio, which scores exact substrings at 100 and degrades
    smoothly with edit distance. score_cutoff=70 accepts 1-2 character typos
    and rejects unrelated strings.
    """
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
        )
        .order_by(Expense.created_at.desc())
    )
    expenses = list(result.scalars().all())
    key = _key()
    for exp in expenses:
        _decrypt_expense(exp, key)
    candidates = [e for e in expenses if e.description]
    matches = process.extract(
        description,
        [e.description for e in candidates],
        scorer=fuzz.WRatio,
        processor=utils.default_process,
        score_cutoff=70,
        limit=5,
    )
    return [candidates[idx] for _, _, idx in matches]



async def update_description(
    session: AsyncSession, expense: Expense, new_description: str | None
) -> None:
    """Update an expense's description (encrypts on write, keeps in-memory plaintext)."""
    key = _key()
    expense.description = encrypt_nullable(new_description, key)  # type: ignore[assignment]
    await session.flush()
    set_decrypted(expense, "description", new_description)


async def get_expense_shares(
    session: AsyncSession, group_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID, int, str]]:
    """Get (payer_id, participant_member_id, share_cents, currency) for active expenses."""
    result = await session.execute(
        select(
            Expense.payer_id,
            ExpenseParticipant.member_id,
            ExpenseParticipant.share_cents,
            Expense.currency,
        )
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
    currency: str,
) -> Settlement:
    """Record a settlement."""
    settlement = Settlement(
        group_id=group_id,
        payer_id=payer_id,
        payee_id=payee_id,
        amount_cents=amount_cents,
        currency=currency,
    )
    session.add(settlement)
    await session.flush()
    return settlement
