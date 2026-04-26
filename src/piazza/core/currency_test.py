"""Tests for currency normalization."""

from __future__ import annotations

import pytest

from piazza.core.currency import InvalidCurrencyError, normalize, normalize_or


class TestNormalize:
    def test_uppercases(self):
        assert normalize("usd") == "USD"

    def test_strips_whitespace(self):
        assert normalize("  eur ") == "EUR"

    def test_accepts_uppercase(self):
        assert normalize("GBP") == "GBP"

    @pytest.mark.parametrize("bad", ["US", "USDX", "1USD", "us d", ""])
    def test_rejects_non_iso(self, bad):
        with pytest.raises(InvalidCurrencyError):
            normalize(bad)

    def test_rejects_non_string(self):
        with pytest.raises(InvalidCurrencyError):
            normalize(None)  # type: ignore[arg-type]


class TestNormalizeOr:
    def test_uses_value_when_present(self):
        assert normalize_or("usd", "EUR") == "USD"

    def test_falls_back_when_none(self):
        assert normalize_or(None, "eur") == "EUR"

    def test_falls_back_when_blank(self):
        assert normalize_or("   ", "eur") == "EUR"

    def test_invalid_value_raises(self):
        with pytest.raises(InvalidCurrencyError):
            normalize_or("XX", "EUR")
