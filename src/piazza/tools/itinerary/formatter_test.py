"""Tests for itinerary formatters."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from piazza.tools.itinerary.formatter import (
    TYPE_EMOJI,
    format_full_itinerary,
    format_item_confirmation,
)


class TestItineraryFormatters:
    def _mock_item(self, item_type, title, start_at=None, end_at=None, location=None):
        item = MagicMock()
        item.item_type = item_type
        item.title = title
        item.start_at = start_at
        item.end_at = end_at
        item.location = location
        return item

    def test_correct_emoji_per_type(self):
        for item_type, emoji in TYPE_EMOJI.items():
            item = self._mock_item(item_type, f"Test {item_type}")
            result = format_item_confirmation([item])
            assert emoji in result

    def test_itinerary_no_html(self):
        """Formatters should not produce HTML tags."""
        item = self._mock_item(
            "flight", "BA247",
            start_at=datetime(2025, 3, 15, 11, 0, tzinfo=timezone.utc),
            location="London to Barcelona",
        )
        result = format_full_itinerary([item])
        assert "<" not in result
        assert ">" not in result

    def test_itinerary_no_markdown_links(self):
        """No markdown links [text](url) in output."""
        item = self._mock_item(
            "hotel", "Hotel Arts",
            start_at=datetime(2025, 3, 15, 15, 0, tzinfo=timezone.utc),
            location="Barcelona",
        )
        result = format_full_itinerary([item])
        assert "](http" not in result

    def test_confirmation_with_time_range(self):
        item = self._mock_item(
            "flight", "BA247",
            start_at=datetime(2025, 3, 15, 11, 0),
            end_at=datetime(2025, 3, 15, 14, 0),
        )
        result = format_item_confirmation([item])
        assert "11:00" in result
        assert "14:00" in result
