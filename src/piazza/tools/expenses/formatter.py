"""Expense response formatters (WhatsApp markdown)."""

from __future__ import annotations

import uuid

from piazza.db.models.expense import Expense


def _currency_symbol(currency: str) -> str:
    symbols = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3", "CHF": "CHF", "JPY": "\u00a5"}
    return symbols.get(currency, currency)


def _fmt_amount(cents: int, currency: str) -> str:
    symbol = _currency_symbol(currency)
    return f"{symbol}{cents / 100:.2f}"


def format_expense_confirmation(
    amount_cents: int,
    currency: str,
    description: str | None,
    payer_name: str,
    shares: list[tuple[str, int]],
) -> str:
    """Format an expense confirmation message."""
    desc = description or "expense"
    amount = _fmt_amount(amount_cents, currency)
    lines = [f"Logged: *{payer_name}* paid {amount} for {desc}"]

    if len(shares) == 1:
        name, s = shares[0]
        lines.append(f"Owed by {name}: {_fmt_amount(s, currency)}")
    else:
        names = [name for name, _ in shares]
        share_amt = _fmt_amount(shares[0][1], currency)
        # Check if all shares are equal
        if len(set(s for _, s in shares)) == 1:
            lines.append(f"Split evenly: {', '.join(names)} — {share_amt} each")
        else:
            parts = [f"{name}: {_fmt_amount(s, currency)}" for name, s in shares]
            lines.append("Split: " + ", ".join(parts))

    return "\n".join(lines)


def format_balance_summary(
    debts: list[tuple[uuid.UUID, uuid.UUID, int]],
    member_map: dict[uuid.UUID, str],
) -> str:
    """Format balance summary as pairwise debts."""
    if not debts:
        return "All settled up! No outstanding balances."

    lines = ["*Group Balances*\n"]
    for debtor_id, creditor_id, amount_cents in debts:
        debtor = member_map.get(debtor_id, "Unknown")
        creditor = member_map.get(creditor_id, "Unknown")
        lines.append(f"*{debtor}* owes *{creditor}* {amount_cents / 100:.2f}")

    return "\n".join(lines)


def format_settle_suggestions(
    debts: list[tuple[uuid.UUID, uuid.UUID, int]],
    member_map: dict[uuid.UUID, str],
) -> str:
    """Format settle-up suggestions."""
    if not debts:
        return "All settled up! No payments needed."

    lines = ["*Settle Up*\n"]
    for debtor_id, creditor_id, amount_cents in debts:
        debtor = member_map.get(debtor_id, "Unknown")
        creditor = member_map.get(creditor_id, "Unknown")
        lines.append(f"*{debtor}* pays *{creditor}* {amount_cents / 100:.2f}")

    return "\n".join(lines)


def format_settlement_confirmation(
    payer_name: str,
    payee_name: str,
    amount_cents: int,
    currency: str,
    remaining_cents: int | None,
) -> str:
    """Format a settlement confirmation message.

    remaining_cents: positive means payer still owes payee that amount,
                     zero/None means fully settled.
    """
    amount = _fmt_amount(amount_cents, currency)
    lines = [f"Payment recorded: *{payer_name}* paid *{payee_name}* {amount}"]

    if remaining_cents is not None and remaining_cents > 0:
        remaining = _fmt_amount(remaining_cents, currency)
        lines.append(f"Remaining: *{payer_name}* owes *{payee_name}* {remaining}")
    else:
        lines.append(f"*{payer_name}* and *{payee_name}* are now settled up!")

    return "\n".join(lines)


def format_expense_disambiguation(expenses: list[Expense]) -> str:
    """Format disambiguation for multiple matching expenses."""
    lines = ["Multiple expenses match. Use list_expenses to find the item number:\n"]
    for exp in expenses[:5]:
        desc = exp.description or "expense"
        amount = _fmt_amount(exp.amount_cents, exp.currency)
        lines.append(f"• {desc} ({amount})")
    return "\n".join(lines)


def format_update_confirmation(
    expense: Expense,
    changes: list[str],
) -> str:
    """Format an expense update confirmation."""
    desc = expense.description or "expense"
    amount = _fmt_amount(expense.amount_cents, expense.currency)
    lines = [f"Updated *{desc}* ({amount})"]
    for change in changes:
        lines.append(f"  • {change}")
    return "\n".join(lines)


def format_expense_list(expenses: list[Expense]) -> str:
    """Format a list of recent expenses."""
    lines = ["*Recent Expenses*\n"]
    for i, exp in enumerate(expenses, 1):
        desc = exp.description or "expense"
        amount = _fmt_amount(exp.amount_cents, exp.currency)
        payer = exp.payer.display_name if exp.payer else "Unknown"
        others = [
            p.member.display_name
            for p in (exp.participants or [])
            if p.member and p.member_id != exp.payer_id
        ]
        split_str = f", split with {', '.join(others)}" if others else ""
        lines.append(f"{i}. {amount} — {desc} (paid by {payer}{split_str})")

    return "\n".join(lines)
