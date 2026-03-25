"""Expense business logic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import ExpenseError, NotFoundError
from piazza.db.models.expense import Expense
from piazza.db.repositories import expense as expense_repo
from piazza.db.repositories import note as note_repo
from piazza.db.repositories.member import get_all_members

# ---------- Private helpers ----------


def _build_expense_note(
    description: str | None,
    amount_cents: int,
    currency: str,
    payer_name: str,
    participant_names: list[str],
) -> str:
    """Build a readable knowledge-base note from an expense."""
    amount = f"{amount_cents / 100:.2f} {currency}"
    names = ", ".join(participant_names)
    return f"{description} \u2014 {amount}, {payer_name}, {names}"


def _build_settlement_note(
    payer_name: str,
    payee_name: str,
    amount_cents: int,
    currency: str,
) -> str:
    """Build a readable knowledge-base note from a settlement."""
    amount = f"{amount_cents / 100:.2f} {currency}"
    return f"{payer_name} → {payee_name} {amount}"


def _member_map(members: list) -> dict[uuid.UUID, str]:
    return {m.id: m.display_name for m in members}


def _named_shares(
    shares: list[tuple[uuid.UUID, int]], member_map: dict[uuid.UUID, str]
) -> list[dict]:
    return [
        {"name": member_map[mid], "amount_cents": cents}
        for mid, cents in shares
    ]


# ---------- Result types ----------


@dataclass
class ExpenseResult:
    """Data returned after creating an expense."""

    expense: Expense
    payer_name: str
    shares: list[dict]  # [{"name": str, "amount_cents": int}]


@dataclass
class SettlementResult:
    """Data returned after recording a settlement."""

    payer_name: str
    payee_name: str
    amount_cents: int
    currency: str
    remaining_cents: int
    settled_up: bool


@dataclass
class BalanceResult:
    """Data returned from balance queries."""

    debts: list[dict]  # [{"debtor": str, "creditor": str, "amount_cents": int}]


def expense_to_dict(exp: Expense, number: int | None = None) -> dict:
    """Convert an Expense model to a structured dict."""
    payer = exp.payer.display_name
    shares = [
        {"name": p.member.display_name, "amount_cents": p.share_cents}
        for p in (exp.participants or [])
        if p.member
    ]
    d: dict = {
        "amount_cents": exp.amount_cents,
        "currency": exp.currency,
        "description": exp.description,
        "payer": payer,
        "shares": shares,
    }
    if number is not None:
        d["number"] = number
    return d


# ---------- Pure functions ----------


def calculate_even_split(amount_cents: int, num_participants: int) -> list[int]:
    """Split amount evenly, distributing remainder to first participants.

    E.g. 1000 cents / 3 = [334, 333, 333].
    """
    if num_participants <= 0:
        raise ExpenseError("Cannot split among zero participants")
    if amount_cents <= 0:
        raise ExpenseError("Amount must be positive")

    base = amount_cents // num_participants
    remainder = amount_cents % num_participants
    return [base + (1 if i < remainder else 0) for i in range(num_participants)]


def calculate_balances(
    expense_rows: list[tuple[uuid.UUID, uuid.UUID, int]],
    settlements: list[tuple[uuid.UUID, uuid.UUID, int]],
) -> dict[uuid.UUID, int]:
    """Calculate net balance per member.

    Positive = owed money (creditor). Negative = owes money (debtor).

    expense_rows: (payer_id, participant_member_id, share_cents)
    settlements: (payer_id, payee_id, amount_cents)
    """
    balances: dict[uuid.UUID, int] = {}

    for payer_id, participant_id, share_cents in expense_rows:
        balances[payer_id] = balances.get(payer_id, 0) + share_cents
        balances[participant_id] = balances.get(participant_id, 0) - share_cents

    for payer_id, payee_id, amount_cents in settlements:
        balances[payer_id] = balances.get(payer_id, 0) + amount_cents
        balances[payee_id] = balances.get(payee_id, 0) - amount_cents

    return balances


def simplify_debts(
    balances: dict[uuid.UUID, int],
) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
    """Greedy min-flow debt simplification.

    Returns list of (debtor_id, creditor_id, amount_cents) transactions.
    """
    debtors: list[tuple[uuid.UUID, int]] = []
    creditors: list[tuple[uuid.UUID, int]] = []

    for member_id, balance in balances.items():
        if balance < 0:
            debtors.append((member_id, -balance))
        elif balance > 0:
            creditors.append((member_id, balance))

    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    transactions: list[tuple[uuid.UUID, uuid.UUID, int]] = []
    di, ci = 0, 0

    while di < len(debtors) and ci < len(creditors):
        debtor_id, debt = debtors[di]
        creditor_id, credit = creditors[ci]
        amount = min(debt, credit)

        if amount > 0:
            transactions.append((debtor_id, creditor_id, amount))

        debt -= amount
        credit -= amount

        if debt == 0:
            di += 1
        else:
            debtors[di] = (debtor_id, debt)

        if credit == 0:
            ci += 1
        else:
            creditors[ci] = (creditor_id, credit)

    return transactions


# ---------- Async service functions ----------


async def add_expense(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    amount_cents: int,
    currency: str,
    description: str | None,
    shares: list[tuple[uuid.UUID, int]],
) -> ExpenseResult:
    """Create an expense with participants."""
    expense = await expense_repo.create_expense(
        session, group_id, payer_id, amount_cents, currency, description
    )
    await expense_repo.create_expense_participants(session, expense.id, shares)

    members = await get_all_members(session, group_id)
    mmap = _member_map(members)

    # Auto-note for knowledge base
    participant_names = [mmap[mid] for mid, _ in shares]
    note_content = _build_expense_note(
        description, amount_cents, currency,
        mmap[payer_id], participant_names,
    )
    await note_repo.create_note(
        session, group_id, payer_id,
        content=note_content, tag=description,
    )

    await session.commit()

    return ExpenseResult(
        expense=expense,
        payer_name=mmap[payer_id],
        shares=_named_shares(shares, mmap),
    )


async def get_balances(session: AsyncSession, group_id: uuid.UUID) -> BalanceResult:
    """Calculate net balances as simplified pairwise debts."""
    expense_rows = await expense_repo.get_expense_shares(session, group_id)
    settlements_raw = await expense_repo.get_settlements(session, group_id)
    settlement_tuples = [
        (s.payer_id, s.payee_id, s.amount_cents) for s in settlements_raw
    ]

    balances = calculate_balances(expense_rows, settlement_tuples)
    debts = simplify_debts(balances)

    members = await get_all_members(session, group_id)
    mmap = _member_map(members)

    return BalanceResult(debts=[
        {"debtor": mmap[d_id], "creditor": mmap[c_id], "amount_cents": amt}
        for d_id, c_id, amt in debts
    ])


async def record_settlement(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    payee_id: uuid.UUID,
    amount_cents: int,
    currency: str,
) -> SettlementResult:
    """Record a settlement payment."""
    await expense_repo.create_settlement(session, group_id, payer_id, payee_id, amount_cents)

    members = await get_all_members(session, group_id)
    mmap = _member_map(members)
    payer_name = mmap[payer_id]
    payee_name = mmap[payee_id]

    # Auto-note for knowledge base
    note_content = _build_settlement_note(payer_name, payee_name, amount_cents, currency)
    await note_repo.create_note(
        session, group_id, payer_id,
        content=note_content, tag="settlement",
    )

    await session.commit()

    # Calculate remaining balance between these two members
    expense_rows = await expense_repo.get_expense_shares(session, group_id)
    settlements_raw = await expense_repo.get_settlements(session, group_id)
    settlement_tuples = [
        (s.payer_id, s.payee_id, s.amount_cents) for s in settlements_raw
    ]
    balances = calculate_balances(expense_rows, settlement_tuples)
    debts = simplify_debts(balances)

    remaining_cents = 0
    for debtor_id, creditor_id, amt in debts:
        if debtor_id == payer_id and creditor_id == payee_id:
            remaining_cents = amt
            break

    return SettlementResult(
        payer_name=payer_name,
        payee_name=payee_name,
        amount_cents=amount_cents,
        currency=currency,
        remaining_cents=remaining_cents,
        settled_up=remaining_cents == 0,
    )


async def resolve_expense_by_number(
    session: AsyncSession, group_id: uuid.UUID, number: int
) -> Expense:
    """Resolve an expense by its 1-indexed list position.

    Raises NotFoundError if out of range.
    """
    expenses = await expense_repo.get_expenses(session, group_id)
    if number < 1 or number > len(expenses):
        raise NotFoundError("expense", number=number, total=len(expenses))
    return expenses[number - 1]


async def resolve_expense_by_description(
    session: AsyncSession, group_id: uuid.UUID, description: str
) -> Expense | list[Expense]:
    """Resolve an expense by description match.

    Returns single Expense if exactly one match.
    Returns list[Expense] if multiple matches (ambiguous).
    Raises NotFoundError if no matches.
    """
    matches = await expense_repo.find_expenses_by_description(
        session, group_id, description
    )
    if not matches:
        raise NotFoundError("expense", query=description)
    if len(matches) == 1:
        return matches[0]
    return matches


async def delete_expense(session: AsyncSession, expense: Expense) -> Expense:
    """Soft-delete an already-resolved expense."""
    expense.is_deleted = True
    await session.flush()
    await session.commit()
    return expense


async def update_expense(
    session: AsyncSession,
    expense: Expense,
    new_amount_cents: int | None = None,
    new_currency: str | None = None,
    new_description: str | None = None,
    new_payer_id: uuid.UUID | None = None,
    new_shares: list[tuple[uuid.UUID, int]] | None = None,
) -> tuple[Expense, list[dict]]:
    """Update fields on an already-resolved expense.

    Returns (expense, changes) where changes is a list of field change dicts.
    Raises ExpenseError if nothing to update.
    """
    has_changes = any(v is not None for v in (
        new_amount_cents, new_currency, new_description,
        new_payer_id, new_shares,
    ))
    if not has_changes:
        raise ExpenseError("nothing_to_update")

    members = await get_all_members(session, expense.group_id)
    mmap = _member_map(members)
    changes: list[dict] = []

    if new_description is not None:
        changes.append({
            "field": "description",
            "old": expense.description,
            "new": new_description,
        })
        from piazza.config.settings import settings
        from piazza.core.encryption import encrypt_nullable

        expense.description = encrypt_nullable(new_description, settings.encryption_key_bytes)  # type: ignore[assignment]

    if new_currency is not None:
        changes.append({"field": "currency", "old": expense.currency, "new": new_currency})
        expense.currency = new_currency

    if new_payer_id is not None:
        changes.append({
            "field": "payer",
            "old": mmap[expense.payer_id],
            "new": mmap[new_payer_id],
        })
        expense.payer_id = new_payer_id

    if new_amount_cents is not None:
        changes.append({
            "field": "amount",
            "old_cents": expense.amount_cents,
            "new_cents": new_amount_cents,
        })
        expense.amount_cents = new_amount_cents

    if new_shares is not None:
        await expense_repo.replace_expense_participants(
            session, expense.id, new_shares
        )
        changes.append({
            "field": "shares",
            "new_shares": _named_shares(new_shares, mmap),
        })

    await session.flush()
    await session.commit()

    return expense, changes


async def list_expenses(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Expense]:
    """List recent expenses."""
    return await expense_repo.get_expenses(session, group_id)
