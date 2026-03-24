"""Expense intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.settings import settings
from piazza.db.repositories.member import (
    find_member_by_name,
    get_active_members,
)
from piazza.tools.expenses import service
from piazza.tools.schemas import Entities

# Keywords that mean "split between all group members"
_EVERYONE_KEYWORDS = frozenset({"everyone", "all", "the group", "group"})


async def _resolve_payer(
    session: AsyncSession,
    group_id: uuid.UUID,
    sender_id: uuid.UUID,
    paid_by: str | None,
) -> tuple[uuid.UUID, str | None]:
    """Resolve the payer name to a member ID.

    Returns (payer_id, error_message).
    Falls back to sender_id if paid_by is not provided.
    """
    if not paid_by:
        return sender_id, None

    payer_member, _candidates = await find_member_by_name(
        session, group_id, paid_by
    )
    if payer_member is None:
        active_members = await get_active_members(session, group_id)
        members_str = ", ".join(f"*{m.display_name}*" for m in active_members)
        return sender_id, (
            f"Could not find *{paid_by}* in this group.\n"
            f"Group members: {members_str}"
        )
    return payer_member.id, None


async def _resolve_participants(
    session: AsyncSession,
    group_id: uuid.UUID,
    payer_id: uuid.UUID,
    amount_cents: int,
    participants: list[dict | str] | None,
) -> tuple[list[tuple[uuid.UUID, int]], str | None]:
    """Resolve participant dicts to (member_id, share_cents) pairs.

    Returns (shares, error_message). Shares include the payer whose share is
    total minus the sum of explicit participant amounts.

    Each participant entry is expected to be {name: str, amount: float}.
    String entries trigger "everyone" expansion as a safety fallback.
    """
    if not participants:
        return [(payer_id, amount_cents)], None

    active_members = await get_active_members(session, group_id)

    # Safety fallback: if any entry is a bare string (e.g. "everyone"),
    # expand to all active members with an even split
    if any(isinstance(p, str) for p in participants):
        string_entries = [p for p in participants if isinstance(p, str)]
        if any(s.lower() in _EVERYONE_KEYWORDS for s in string_entries):
            if len(active_members) <= 1:
                return [(payer_id, amount_cents)], (
                    "I don't know all the group members yet. "
                    "Ask everyone to send a message in the group first, "
                    "or name participants explicitly."
                )
            from piazza.tools.expenses.service import calculate_even_split

            non_payer = [m for m in active_members if m.id != payer_id]
            per_person = calculate_even_split(amount_cents, len(non_payer) + 1)
            shares: list[tuple[uuid.UUID, int]] = [(payer_id, per_person[0])]
            for i, m in enumerate(non_payer):
                shares.append((m.id, per_person[i + 1]))
            return shares, None
        # Non-everyone string — can't resolve without amounts
        return [(payer_id, amount_cents)], (
            "Please specify how much each person owes. "
            "Example: _Bob 25, Charlie 10_"
        )

    # Resolve each {name, amount} dict
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
            return [(payer_id, amount_cents)], (
                f"Amount for *{name}* must be positive."
            )
        resolved.append((member.id, entry_cents))

    if failed:
        names_str = ", ".join(f"*{n}*" for n in failed)
        members_str = ", ".join(f"*{m.display_name}*" for m in active_members)
        return [(payer_id, amount_cents)], (
            f"Could not find {names_str} in this group.\n"
            f"Group members: {members_str}"
        )

    # Compute payer share
    participant_total = sum(cents for _, cents in resolved)
    payer_share = amount_cents - participant_total
    if payer_share < 0:
        return [(payer_id, amount_cents)], (
            "Participant amounts add up to more than the total expense."
        )

    return [(payer_id, payer_share)] + resolved, None


async def handle_expense_add(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Log a new expense."""
    if entities.amount is None:
        return "Please specify an amount. Example: _@Piazza I paid 50 for dinner_"

    amount_cents = int(round(entities.amount * 100))
    currency = entities.currency or settings.default_currency

    # Resolve payer
    payer_id, error = await _resolve_payer(
        session, group_id, sender_id, entities.paid_by
    )
    if error:
        return error

    # Resolve participants
    shares, error = await _resolve_participants(
        session, group_id, payer_id, amount_cents, entities.participants
    )
    if error:
        return error

    return await service.add_expense(
        session=session,
        group_id=group_id,
        payer_id=payer_id,
        amount_cents=amount_cents,
        currency=currency,
        description=entities.description,
        shares=shares,
    )


async def handle_expense_balance(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Show who owes what."""
    return await service.get_balance_summary(session, group_id)


async def handle_expense_settle(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Record a settlement payment, or show settle-up suggestions."""
    if entities.amount is not None:
        # Recording a payment: "Josh paid Mia 40"
        amount_cents = int(round(entities.amount * 100))
        currency = entities.currency or settings.default_currency

        if not entities.participants or len(entities.participants) != 1:
            return "Please specify who was paid. Example: _@Piazza Josh paid Mia 40_"

        payee, _candidates = await find_member_by_name(
            session, group_id, entities.participants[0]
        )
        if payee is None:
            active_members = await get_active_members(session, group_id)
            members_str = ", ".join(f"*{m.display_name}*" for m in active_members)
            return (
                f"Could not find *{entities.participants[0]}* in this group.\n"
                f"Group members: {members_str}"
            )

        return await service.record_settlement(
            session=session,
            group_id=group_id,
            payer_id=sender_id,
            payee_id=payee.id,
            amount_cents=amount_cents,
            currency=currency,
        )

    # No amount — show settle-up suggestions
    return await service.get_settle_suggestions(session, group_id)


async def handle_expense_delete(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Delete an expense by list number or description match."""
    if entities.item_number is not None:
        return await service.delete_expense_by_number(session, group_id, entities.item_number)
    if entities.description:
        return await service.delete_expense_by_description(
            session, group_id, entities.description
        )
    return (
        "Please specify which expense to delete. "
        "Example: _delete expense #3_ or _delete the dinner expense_"
    )


async def handle_expense_update(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Update an existing expense."""
    from piazza.db.repositories import expense as expense_repo
    from piazza.tools.expenses.formatter import format_expense_disambiguation

    # Resolve target expense: by number or by description
    if entities.item_number is not None:
        expenses = await expense_repo.get_expenses(session, group_id)
        number = entities.item_number
        if number < 1 or number > len(expenses):
            total = len(expenses)
            if total == 0:
                return "No expenses to update."
            return f"Expense #{number} not found. You have {total} recent expense(s)."
        expense = expenses[number - 1]
    elif entities.description:
        matches = await expense_repo.find_expenses_by_description(
            session, group_id, entities.description
        )
        if not matches:
            return f'No expense matching "{entities.description}" found.'
        if len(matches) > 1:
            return format_expense_disambiguation(matches)
        expense = matches[0]
    else:
        return (
            "Please specify which expense to update. "
            "Example: _update expense #3_ or _update the dinner expense to 60_"
        )

    new_amount_cents = (
        int(round(entities.amount * 100)) if entities.amount is not None else None
    )

    # Resolve new payer if provided
    new_payer_id = None
    if entities.paid_by:
        new_payer_id, error = await _resolve_payer(
            session, group_id, sender_id, entities.paid_by
        )
        if error:
            return error

    # Resolve new participants if provided
    new_shares = None
    if entities.participants is not None:
        anchor_id = new_payer_id or expense.payer_id
        split_amount = new_amount_cents if new_amount_cents is not None else expense.amount_cents
        new_shares, error = await _resolve_participants(
            session, group_id, anchor_id, split_amount, entities.participants
        )
        if error:
            return error

    return await service.update_expense(
        session=session,
        expense=expense,
        new_amount_cents=new_amount_cents,
        new_currency=entities.currency,
        new_description=entities.new_description,
        new_payer_id=new_payer_id,
        new_shares=new_shares,
    )


async def handle_expense_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """List recent expenses."""
    return await service.list_expenses(session, group_id)
