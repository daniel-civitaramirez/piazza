"""Expense business logic."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.core.currency import normalize as normalize_currency
from piazza.core.exceptions import ExpenseError, NotFoundError
from piazza.core.fx import FxProvider
from piazza.db.models.expense import Expense
from piazza.db.repositories import expense as expense_repo
from piazza.db.repositories.member import get_all_members

# ---------- Private helpers ----------


def _member_map(members: list) -> dict[uuid.UUID, str]:
    return {m.id: m.display_name for m in members}


def _rescale_shares(
    expense: Expense, new_total_cents: int
) -> list[tuple[uuid.UUID, int]]:
    """Proportionally rescale existing participant shares to a new total.

    The remainder is absorbed into the largest share so the result still
    sums exactly to `new_total_cents`.
    """
    old_total = expense.amount_cents
    if old_total <= 0:
        return [(p.member_id, new_total_cents) for p in (expense.participants or [])][:1]

    rescaled: list[tuple[uuid.UUID, int]] = []
    for p in expense.participants or []:
        share = (p.share_cents * new_total_cents) // old_total
        rescaled.append((p.member_id, share))

    drift = new_total_cents - sum(s for _, s in rescaled)
    if drift and rescaled:
        # Absorb drift into the largest share to stay exact.
        idx = max(range(len(rescaled)), key=lambda i: rescaled[i][1])
        member_id, share = rescaled[idx]
        rescaled[idx] = (member_id, share + drift)
    return rescaled


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
    """Data returned from balance queries.

    `debts_by_currency` maps an ISO-4217 code to its simplified debt list.
    Each entry: {"debtor": str, "creditor": str, "amount_cents": int}.

    `converted` is set only when the caller asked for a single-currency
    consolidated view: {"currency": str, "debts": [...]}. Conversions use
    the live FX rate at query time and are advisory — the per-currency
    view is the authoritative ledger.
    """

    debts_by_currency: dict[str, list[dict]]
    converted: dict | None = None


def expense_to_dict(exp: Expense, number: int | None = None) -> dict:
    """Convert an Expense model to a structured dict."""
    payer = exp.payer.display_name
    shares = [
        {"name": p.member.display_name, "amount_cents": p.share_cents}
        for p in (exp.participants or [])
        if p.member
    ]
    d: dict = {
        "id": str(exp.id)[:8],
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
    expense_rows: list[tuple[uuid.UUID, uuid.UUID, int, str]],
    settlements: list[tuple[uuid.UUID, uuid.UUID, int, str]],
) -> dict[str, dict[uuid.UUID, int]]:
    """Calculate net balance per member, partitioned by currency.

    Positive = owed money (creditor). Negative = owes money (debtor).

    expense_rows: (payer_id, participant_member_id, share_cents, currency)
    settlements: (payer_id, payee_id, amount_cents, currency)
    """
    by_currency: dict[str, dict[uuid.UUID, int]] = {}

    for payer_id, participant_id, share_cents, currency in expense_rows:
        bucket = by_currency.setdefault(currency, {})
        bucket[payer_id] = bucket.get(payer_id, 0) + share_cents
        bucket[participant_id] = bucket.get(participant_id, 0) - share_cents

    for payer_id, payee_id, amount_cents, currency in settlements:
        bucket = by_currency.setdefault(currency, {})
        bucket[payer_id] = bucket.get(payer_id, 0) + amount_cents
        bucket[payee_id] = bucket.get(payee_id, 0) - amount_cents

    return by_currency


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
    currency = normalize_currency(currency)
    expense = await expense_repo.create_expense(
        session, group_id, payer_id, amount_cents, currency, description
    )
    await expense_repo.create_expense_participants(session, expense.id, shares)

    members = await get_all_members(session, group_id)
    mmap = _member_map(members)

    await session.commit()

    return ExpenseResult(
        expense=expense,
        payer_name=mmap[payer_id],
        shares=_named_shares(shares, mmap),
    )


async def get_balances(
    session: AsyncSession,
    group_id: uuid.UUID,
    *,
    convert_to: str | None = None,
    fx: FxProvider | None = None,
) -> BalanceResult:
    """Calculate net balances as simplified pairwise debts, per currency.

    When `convert_to` is given, also return a consolidated single-currency
    view with each per-currency net converted at the live FX rate.
    """
    expense_rows = await expense_repo.get_expense_shares(session, group_id)
    settlements_raw = await expense_repo.get_settlements(session, group_id)
    settlement_tuples = [
        (s.payer_id, s.payee_id, s.amount_cents, s.currency) for s in settlements_raw
    ]

    by_currency = calculate_balances(expense_rows, settlement_tuples)

    members = await get_all_members(session, group_id)
    mmap = _member_map(members)

    debts_by_currency: dict[str, list[dict]] = {}
    for currency, balances in by_currency.items():
        simplified = simplify_debts(balances)
        if not simplified:
            continue
        debts_by_currency[currency] = [
            {"debtor": mmap[d_id], "creditor": mmap[c_id], "amount_cents": amt}
            for d_id, c_id, amt in simplified
        ]

    converted: dict | None = None
    if convert_to is not None:
        target = normalize_currency(convert_to)
        if fx is None:
            raise ExpenseError("FX provider required to convert balances")
        merged: dict[uuid.UUID, int] = {}
        for currency, balances in by_currency.items():
            for member_id, cents in balances.items():
                if cents == 0:
                    continue
                if currency == target:
                    converted_cents = cents
                else:
                    sign = -1 if cents < 0 else 1
                    abs_converted, _ = await fx.convert(abs(cents), currency, target)
                    converted_cents = sign * abs_converted
                merged[member_id] = merged.get(member_id, 0) + converted_cents
        simplified = simplify_debts(merged)
        converted = {
            "currency": target,
            "debts": [
                {"debtor": mmap[d_id], "creditor": mmap[c_id], "amount_cents": amt}
                for d_id, c_id, amt in simplified
            ],
        }

    return BalanceResult(debts_by_currency=debts_by_currency, converted=converted)


async def record_settlement(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    payee_id: uuid.UUID,
    amount_cents: int,
    currency: str,
) -> SettlementResult:
    """Record a settlement payment."""
    currency = normalize_currency(currency)
    await expense_repo.create_settlement(
        session, group_id, payer_id, payee_id, amount_cents, currency
    )

    members = await get_all_members(session, group_id)
    mmap = _member_map(members)
    payer_name = mmap[payer_id]
    payee_name = mmap[payee_id]

    await session.commit()

    # Remaining debt is computed within the settlement's own currency.
    # Cross-currency settlement views land in commit 3 with the FX layer.
    expense_rows = await expense_repo.get_expense_shares(session, group_id)
    settlements_raw = await expense_repo.get_settlements(session, group_id)
    settlement_tuples = [
        (s.payer_id, s.payee_id, s.amount_cents, s.currency) for s in settlements_raw
    ]
    by_currency = calculate_balances(expense_rows, settlement_tuples)
    debts = simplify_debts(by_currency.get(currency, {}))

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
    fx: FxProvider | None = None,
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
        await expense_repo.update_description(session, expense, new_description)

    if new_currency is not None:
        new_currency = normalize_currency(new_currency)
        # Currency-only change: convert the amount at today's rate so the
        # stored figure keeps its real-world meaning. If the caller also
        # supplied a new amount, trust the caller's number verbatim.
        if new_amount_cents is None and new_currency != expense.currency:
            if fx is None:
                raise ExpenseError("FX provider required to convert currency")
            converted_cents, _ = await fx.convert(
                expense.amount_cents, expense.currency, new_currency
            )
            changes.append({
                "field": "amount",
                "old_cents": expense.amount_cents,
                "new_cents": converted_cents,
                "converted_from": expense.currency,
            })
            expense.amount_cents = converted_cents
            await expense_repo.replace_expense_participants(
                session,
                expense.id,
                _rescale_shares(expense, converted_cents),
            )
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
