"""Expense business logic."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.exceptions import ExpenseError
from piazza.db.models.expense import Expense
from piazza.db.repositories import expense as expense_repo
from piazza.db.repositories import note as note_repo
from piazza.db.repositories.member import get_all_members
from piazza.tools.expenses import formatter

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
    desc = description or "expense"
    names = ", ".join(participant_names)
    return f"Expense: {desc} \u2014 {amount}, paid by {payer_name}, split with {names}"


def _build_settlement_note(
    payer_name: str,
    payee_name: str,
    amount_cents: int,
    currency: str,
) -> str:
    """Build a readable knowledge-base note from a settlement."""
    amount = f"{amount_cents / 100:.2f} {currency}"
    return f"Settlement: {payer_name} paid {payee_name} {amount}"


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
        # Payer paid on behalf of participant
        balances[payer_id] = balances.get(payer_id, 0) + share_cents
        balances[participant_id] = balances.get(participant_id, 0) - share_cents

    for payer_id, payee_id, amount_cents in settlements:
        # payer sent money to payee (reduces payer's debt, reduces payee's credit)
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

    # Sort descending by amount for greedy matching
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
    participant_ids: list[uuid.UUID],
) -> str:
    """Create an expense with participants and return confirmation string."""
    shares = calculate_even_split(amount_cents, len(participant_ids))

    expense = await expense_repo.create_expense(
        session, group_id, payer_id, amount_cents, currency, description, None, "even"
    )
    share_tuples = list(zip(participant_ids, shares))
    await expense_repo.create_expense_participants(session, expense.id, share_tuples)

    members = await get_all_members(session, group_id)
    member_map = {m.id: m.display_name for m in members}

    # Auto-note for knowledge base
    participant_names = [member_map.get(mid, "Unknown") for mid, _ in share_tuples]
    note_content = _build_expense_note(
        description, amount_cents, currency,
        member_map.get(payer_id, "Unknown"), participant_names,
    )
    await note_repo.create_note(
        session, group_id, payer_id,
        content=note_content, tag=description,
    )

    await session.commit()

    return formatter.format_expense_confirmation(
        amount_cents, currency, description, member_map.get(payer_id, "Unknown"),
        [(member_map.get(mid, "Unknown"), s) for mid, s in share_tuples],
    )


async def get_balance_summary(session: AsyncSession, group_id: uuid.UUID) -> str:
    """Calculate and format balance summary."""
    expense_rows = await expense_repo.get_expense_shares(session, group_id)
    settlements_raw = await expense_repo.get_settlements(session, group_id)
    settlement_tuples = [
        (s.payer_id, s.payee_id, s.amount_cents) for s in settlements_raw
    ]

    balances = calculate_balances(expense_rows, settlement_tuples)
    debts = simplify_debts(balances)

    members = await get_all_members(session, group_id)
    member_map = {m.id: m.display_name for m in members}

    return formatter.format_balance_summary(debts, member_map)


async def get_settle_suggestions(session: AsyncSession, group_id: uuid.UUID) -> str:
    """Calculate simplified debts and format suggestions."""
    expense_rows = await expense_repo.get_expense_shares(session, group_id)
    settlements_raw = await expense_repo.get_settlements(session, group_id)
    settlement_tuples = [
        (s.payer_id, s.payee_id, s.amount_cents) for s in settlements_raw
    ]

    balances = calculate_balances(expense_rows, settlement_tuples)
    debts = simplify_debts(balances)

    members = await get_all_members(session, group_id)
    member_map = {m.id: m.display_name for m in members}

    return formatter.format_settle_suggestions(debts, member_map)


async def record_settlement(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    payee_id: uuid.UUID,
    amount_cents: int,
    currency: str,
) -> str:
    """Record a settlement payment and return confirmation with remaining balance."""
    await expense_repo.create_settlement(session, group_id, payer_id, payee_id, amount_cents)

    members = await get_all_members(session, group_id)
    member_map = {m.id: m.display_name for m in members}
    payer_name = member_map.get(payer_id, "Unknown")
    payee_name = member_map.get(payee_id, "Unknown")

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

    # Remaining: if payer's balance is negative, they still owe.
    # But we want the pairwise debt, not aggregate.
    # Use simplified debts to find if payer still owes payee.
    debts = simplify_debts(balances)
    remaining_cents: int | None = None
    for debtor_id, creditor_id, amt in debts:
        if debtor_id == payer_id and creditor_id == payee_id:
            remaining_cents = amt
            break

    return formatter.format_settlement_confirmation(
        payer_name, payee_name, amount_cents, currency, remaining_cents
    )


async def delete_last_expense(session: AsyncSession, group_id: uuid.UUID) -> str:
    """Soft-delete the last expense."""
    expense = await expense_repo.delete_last_expense(session, group_id)
    if expense is None:
        return "No expenses to delete."
    await session.commit()
    desc = expense.description or "expense"
    amount = f"{expense.amount_cents / 100:.2f}"
    return f"Deleted: {desc} ({amount} {expense.currency})"


async def delete_expense_by_description(
    session: AsyncSession, group_id: uuid.UUID, description: str
) -> str:
    """Find and soft-delete expense by description match."""
    matches = await expense_repo.find_expenses_by_description(
        session, group_id, description
    )

    if not matches:
        return f'No expense matching "{description}" found.'

    if len(matches) == 1:
        matches[0].is_deleted = True
        await session.flush()
        await session.commit()
        desc = matches[0].description or "expense"
        amount = f"{matches[0].amount_cents / 100:.2f}"
        return f"Deleted: {desc} ({amount} {matches[0].currency})"

    return formatter.format_expense_disambiguation(matches)


async def update_expense(
    session: AsyncSession,
    expense: Expense,
    new_amount_cents: int | None = None,
    new_currency: str | None = None,
    new_description: str | None = None,
    new_payer_id: uuid.UUID | None = None,
    new_participant_ids: list[uuid.UUID] | None = None,
) -> str:
    """Update fields on an already-found expense."""
    has_changes = any(v is not None for v in (
        new_amount_cents, new_currency, new_description,
        new_payer_id, new_participant_ids,
    ))
    if not has_changes:
        return "Nothing to update. Specify a new amount, currency, or description."

    members = await get_all_members(session, expense.group_id)
    member_map = {m.id: m.display_name for m in members}
    changes: list[str] = []

    if new_description is not None:
        old_desc = expense.description or "expense"
        expense.description = new_description
        changes.append(f"Description: {old_desc} → {new_description}")

    if new_currency is not None:
        expense.currency = new_currency
        changes.append(f"Currency: → {new_currency}")

    if new_payer_id is not None:
        old_payer = member_map.get(expense.payer_id, "Unknown")
        new_payer = member_map.get(new_payer_id, "Unknown")
        expense.payer_id = new_payer_id
        changes.append(f"Payer: {old_payer} → {new_payer}")

    # Determine the amount for share calculation
    amount_for_split = expense.amount_cents

    if new_amount_cents is not None:
        old_amount = f"{expense.amount_cents / 100:.2f}"
        expense.amount_cents = new_amount_cents
        amount_for_split = new_amount_cents
        changes.append(f"Amount: {old_amount} → {new_amount_cents / 100:.2f}")

    if new_participant_ids is not None:
        # Replace participants entirely
        new_shares = calculate_even_split(
            amount_for_split, len(new_participant_ids)
        )
        share_tuples = list(zip(new_participant_ids, new_shares))
        await expense_repo.replace_expense_participants(
            session, expense.id, share_tuples
        )
        names = [member_map.get(mid, "Unknown") for mid in new_participant_ids]
        changes.append(f"Split: {', '.join(names)}")
    elif new_amount_cents is not None:
        # Amount changed but participants didn't — recalculate shares
        participants = list(expense.participants or [])
        if participants:
            new_shares = calculate_even_split(
                new_amount_cents, len(participants)
            )
            for participant, share in zip(participants, new_shares):
                participant.share_cents = share

    await session.flush()
    await session.commit()
    return formatter.format_update_confirmation(expense, changes)


async def list_expenses(session: AsyncSession, group_id: uuid.UUID) -> str:
    """List recent expenses."""
    expenses = await expense_repo.get_expenses(session, group_id)
    if not expenses:
        return "No expenses logged yet."
    return formatter.format_expense_list(expenses)
