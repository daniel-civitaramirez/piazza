"""Expense intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.core.exceptions import ExpenseError, NotFoundError
from piazza.db.models.expense import Expense
from piazza.db.repositories.member import (
    find_member_by_name,
    get_active_members,
)
from piazza.tools.expenses import service
from piazza.tools.responses import (
    Action,
    Entity,
    Reason,
    ambiguous_response,
    empty_response,
    error_response,
    list_response,
    not_found_response,
    ok_response,
)
from piazza.tools.schemas import Entities

# ---------- Private helpers ----------


def _group_member_names(members: list) -> list[str]:
    return [m.display_name for m in members]


def _not_found_from_exc(exc: NotFoundError) -> dict:
    return not_found_response(
        exc.entity,
        number=exc.number,
        total=exc.total,
        query=exc.query,
    )


def _ambiguous_response(matches: list[Expense]) -> dict:
    return ambiguous_response(
        Entity.EXPENSE,
        [service.expense_to_dict(exp, i) for i, exp in enumerate(matches[:5], 1)],
    )


async def _resolve_payer(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    paid_by: str | None,
) -> uuid.UUID | dict:
    """Resolve the payer name to a member ID.

    Returns payer member ID, or error response dict.
    """
    if not paid_by:
        return sender_id

    payer_member, _candidates = await find_member_by_name(
        session, group_id, paid_by
    )
    if payer_member is None:
        active_members = await get_active_members(session, group_id)
        return error_response(
            Reason.PAYER_NOT_FOUND,
            name=paid_by,
            group_members=_group_member_names(active_members),
        )
    return payer_member.id


async def _resolve_shares(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    amount_cents: int,
    participants: list[dict] | None,
) -> list[tuple[uuid.UUID, int]] | dict:
    """Resolve participant dicts to (member_id, share_cents) pairs.

    Returns shares list (including payer), or error response dict.
    Payer share = total minus sum of explicit participant amounts.
    """
    if not participants:
        return [(payer_id, amount_cents)]

    active_members = await get_active_members(session, group_id)

    resolved: list[tuple[uuid.UUID, int]] = []
    failed: list[str] = []

    for entry in participants:
        name = entry.get("name", "")
        raw_amount = entry.get("amount")
        if not name or raw_amount is None:
            continue

        member, _candidates = await find_member_by_name(session, group_id, name)
        if member is None:
            failed.append(name)
            continue

        entry_cents = int(round(float(raw_amount) * 100))
        if entry_cents <= 0:
            return error_response(Reason.NEGATIVE_AMOUNT, name=name)
        resolved.append((member.id, entry_cents))

    if failed:
        return error_response(
            Reason.PARTICIPANTS_NOT_FOUND,
            names=failed,
            group_members=_group_member_names(active_members),
        )

    # Compute payer share
    participant_total = sum(cents for _, cents in resolved)
    payer_share = amount_cents - participant_total
    if payer_share < 0:
        return error_response(Reason.PARTICIPANTS_EXCEED_TOTAL)

    return [(payer_id, payer_share)] + resolved


# ---------- Public handlers ----------


async def handle_expense_add(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Log a new expense."""
    if entities.amount is None:
        return error_response(Reason.MISSING_AMOUNT)

    amount_cents = int(round(entities.amount * 100))
    currency = entities.currency or settings.default_currency

    result = await _resolve_payer(session, group_id, sender_id, entities.paid_by)
    if isinstance(result, dict):
        return result
    payer_id = result

    result = await _resolve_shares(
        session, group_id, payer_id, amount_cents, entities.participants
    )
    if isinstance(result, dict):
        return result
    shares = result

    expense_result = await service.add_expense(
        session=session,
        group_id=group_id,
        payer_id=payer_id,
        amount_cents=amount_cents,
        currency=currency,
        description=entities.description,
        shares=shares,
    )
    return ok_response(
        Action.ADD_EXPENSE,
        payer=expense_result.payer_name,
        amount_cents=amount_cents,
        currency=currency,
        description=entities.description,
        shares=expense_result.shares,
    )


async def handle_expense_balance(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Show who owes what."""
    result = await service.get_balances(session, group_id)
    return ok_response(Action.GET_BALANCES, debts=result.debts)


async def handle_expense_settle(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Record a settlement payment."""
    if entities.amount is None:
        return error_response(Reason.MISSING_AMOUNT)

    amount_cents = int(round(entities.amount * 100))
    if amount_cents <= 0:
        return error_response(Reason.NEGATIVE_AMOUNT)

    currency = entities.currency or settings.default_currency

    if not entities.participants or len(entities.participants) != 1:
        return error_response(Reason.MISSING_SETTLEMENT_PAYEE)

    payee_name = str(entities.participants[0])
    payee, _candidates = await find_member_by_name(
        session, group_id, payee_name
    )
    if payee is None:
        active_members = await get_active_members(session, group_id)
        return error_response(
            Reason.PAYEE_NOT_FOUND,
            name=payee_name,
            group_members=_group_member_names(active_members),
        )

    result = await service.record_settlement(
        session=session,
        group_id=group_id,
        payer_id=sender_id,
        payee_id=payee.id,
        amount_cents=amount_cents,
        currency=currency,
    )
    return ok_response(
        Action.SETTLE_EXPENSE,
        payer=result.payer_name,
        payee=result.payee_name,
        amount_cents=result.amount_cents,
        currency=result.currency,
        remaining_cents=result.remaining_cents,
        settled_up=result.settled_up,
    )


async def handle_expense_delete(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Delete an expense by list number or description match."""
    try:
        if entities.item_number is not None:
            expense = await service.resolve_expense_by_number(
                session, group_id, entities.item_number
            )
        elif entities.description:
            result = await service.resolve_expense_by_description(
                session, group_id, entities.description
            )
            if isinstance(result, list):
                return _ambiguous_response(result)
            expense = result
        else:
            return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.EXPENSE)
    except NotFoundError as exc:
        return _not_found_from_exc(exc)

    await service.delete_expense(session, expense)
    return ok_response(
        Action.DELETE_EXPENSE,
        description=expense.description,
        amount_cents=expense.amount_cents,
        currency=expense.currency,
    )


async def handle_expense_update(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """Update an existing expense."""
    # Resolve target expense
    try:
        if entities.item_number is not None:
            expense = await service.resolve_expense_by_number(
                session, group_id, entities.item_number
            )
        elif entities.description:
            result = await service.resolve_expense_by_description(
                session, group_id, entities.description
            )
            if isinstance(result, list):
                return _ambiguous_response(result)
            expense = result
        else:
            return error_response(Reason.MISSING_IDENTIFIER, entity=Entity.EXPENSE)
    except NotFoundError as exc:
        return _not_found_from_exc(exc)

    new_amount_cents = (
        int(round(entities.amount * 100)) if entities.amount is not None else None
    )

    # Resolve new payer if provided
    new_payer_id = None
    if entities.paid_by:
        result = await _resolve_payer(session, group_id, sender_id, entities.paid_by)
        if isinstance(result, dict):
            return result
        new_payer_id = result

    # Resolve new shares if provided
    new_shares = None
    if entities.participants is not None:
        anchor_id = new_payer_id or expense.payer_id
        split_amount = new_amount_cents if new_amount_cents is not None else expense.amount_cents
        result = await _resolve_shares(
            session, group_id, anchor_id, split_amount, entities.participants
        )
        if isinstance(result, dict):
            return result
        new_shares = result

    try:
        expense, changes = await service.update_expense(
            session=session,
            expense=expense,
            new_amount_cents=new_amount_cents,
            new_currency=entities.currency,
            new_description=entities.new_description,
            new_payer_id=new_payer_id,
            new_shares=new_shares,
        )
    except ExpenseError:
        return error_response(Reason.NOTHING_TO_UPDATE)

    return ok_response(
        Action.UPDATE_EXPENSE,
        description=expense.description,
        amount_cents=expense.amount_cents,
        currency=expense.currency,
        changes=changes,
    )


async def handle_expense_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> dict:
    """List recent expenses."""
    expenses = await service.list_expenses(session, group_id)
    if not expenses:
        return empty_response(Entity.EXPENSES)

    return list_response(
        Entity.EXPENSES,
        [service.expense_to_dict(exp, i) for i, exp in enumerate(expenses, 1)],
    )
