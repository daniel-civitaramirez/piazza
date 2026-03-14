"""Tests for expense formatters."""

from __future__ import annotations

import uuid

from piazza.tools.expenses.formatter import (
    format_balance_summary,
    format_expense_confirmation,
    format_settle_suggestions,
)


class TestExpenseFormatters:
    def test_confirmation_includes_amount_and_currency(self):
        result = format_expense_confirmation(
            5000, "EUR", "dinner", "Alice",
            [("Alice", 2500), ("Bob", 2500)],
        )
        assert "\u20ac" in result  # euro sign
        assert "50.00" in result
        assert "dinner" in result

    def test_confirmation_includes_participant_names(self):
        result = format_expense_confirmation(
            3000, "USD", "taxi", "Alice",
            [("Alice", 1000), ("Bob", 1000), ("Charlie", 1000)],
        )
        assert "Alice" in result
        assert "Bob" in result
        assert "Charlie" in result
        assert "$" in result

    def test_confirmation_usd_symbol(self):
        result = format_expense_confirmation(
            1000, "USD", "coffee", "Bob", [("Bob", 1000)],
        )
        assert "$10.00" in result

    def test_confirmation_gbp_symbol(self):
        result = format_expense_confirmation(
            2000, "GBP", "bus", "Alice", [("Alice", 2000)],
        )
        assert "\u00a3" in result  # pound sign

    def test_even_split_label(self):
        """When all shares are equal, should say 'Split evenly'."""
        result = format_expense_confirmation(
            3000, "EUR", "lunch", "Alice",
            [("Alice", 1000), ("Bob", 1000), ("Charlie", 1000)],
        )
        assert "Split evenly" in result

    def test_uneven_split_label(self):
        """When shares differ, should list individual amounts."""
        result = format_expense_confirmation(
            9000, "EUR", "hotel", "Alice",
            [("Alice", 3000), ("Bob", 6000)],
        )
        assert "Split:" in result

    def test_balance_summary_bold_names(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        member_map = {a: "Alice", b: "Bob"}
        debts = [(b, a, 1000)]  # Bob owes Alice 1000
        result = format_balance_summary(debts, member_map)
        assert "*Alice*" in result
        assert "*Bob*" in result
        assert "owes" in result

    def test_balance_summary_all_settled(self):
        result = format_balance_summary([], {})
        assert "settled" in result.lower()

    def test_settle_suggestions_format(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        debts = [(a, b, 1500)]
        member_map = {a: "Alice", b: "Bob"}
        result = format_settle_suggestions(debts, member_map)
        assert "*Alice*" in result
        assert "*Bob*" in result
        assert "pays" in result
        assert "15.00" in result

    def test_expense_formatter_no_html(self):
        result = format_expense_confirmation(
            5000, "EUR", "dinner<script>", "Alice",
            [("Alice", 2500), ("Bob", 2500)],
        )
        # The formatter doesn't strip HTML from descriptions,
        # but it shouldn't add any HTML of its own
        assert result.count("<") <= 1  # only the one in the description
