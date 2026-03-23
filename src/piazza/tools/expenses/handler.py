"""Expense intent handlers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from piazza.config.constants import DEFAULT_CURRENCY
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
    participant_names: list[str] | None,
) -> tuple[list[uuid.UUID], str | None]:
    """Resolve participant names to member IDs.

    Returns (participant_ids, error_message). If error_message is not None,
    the expense should not be logged and the error should be returned to the user.

    The payer is always included in participant_ids.
    """
    participant_ids: list[uuid.UUID] = [payer_id]  # Payer always included

    if not participant_names:
        return participant_ids, None

    active_members = await get_active_members(session, group_id)

    # Safety fallback: if LLM returns "everyone" despite prompt instructions,
    # expand to all active members rather than trying to resolve it as a name
    if any(p.lower() in _EVERYONE_KEYWORDS for p in participant_names):
        if len(active_members) <= 1:
            return participant_ids, (
                "I don't know all the group members yet. "
                "Ask everyone to send a message in the group first, "
                "or name participants explicitly."
            )
        for m in active_members:
            if m.id != payer_id:
                participant_ids.append(m.id)
        return participant_ids, None

    # Resolve each name with fuzzy matching
    failed: list[str] = []

    for name in participant_names:
        member, _candidates = await find_member_by_name(
            session, group_id, name
        )
        if member and member.id != payer_id:
            participant_ids.append(member.id)
        elif member and member.id == payer_id:
            pass  # Payer already included
        else:
            failed.append(name)

    if failed:
        names_str = ", ".join(f"*{n}*" for n in failed)
        members_str = ", ".join(f"*{m.display_name}*" for m in active_members)
        return participant_ids, (
            f"Could not find {names_str} in this group.\n"
            f"Group members: {members_str}"
        )

    return participant_ids, None


async def handle_expense_add(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """Log a new expense."""
    if entities.amount is None:
        return "Please specify an amount. Example: _@Piazza I paid 50 for dinner_"

    amount_cents = int(round(entities.amount * 100))
    currency = entities.currency or DEFAULT_CURRENCY

    # Resolve payer
    payer_id, error = await _resolve_payer(
        session, group_id, sender_id, entities.paid_by
    )
    if error:
        return error

    # Resolve participants
    participant_ids, error = await _resolve_participants(
        session, group_id, payer_id, entities.participants
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
        participant_ids=participant_ids,
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
        currency = entities.currency or DEFAULT_CURRENCY

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
    new_participant_ids = None
    if entities.participants is not None:
        # Anchor on new payer, or existing expense payer
        anchor_id = new_payer_id or expense.payer_id
        new_participant_ids, error = await _resolve_participants(
            session, group_id, anchor_id, entities.participants
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
        new_participant_ids=new_participant_ids,
    )


async def handle_expense_list(
    session: AsyncSession, group_id: uuid.UUID, sender_id: uuid.UUID, entities: Entities
) -> str:
    """List recent expenses."""
    return await service.list_expenses(session, group_id)
