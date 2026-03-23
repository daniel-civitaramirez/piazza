"""Tests for reminder intent handlers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from piazza.db.repositories.reminder import create_reminder
from piazza.tools.reminders import handler
from piazza.tools.schemas import Entities


class TestHandleReminderCancel:
    @pytest.mark.asyncio
    async def test_cancel_by_number(self, db_session, sample_group):
        """Cancel reminder using item_number."""
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "dentist appointment", trigger,
        )
        await db_session.flush()

        entities = Entities(item_number=1)
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Cancelled" in result
        assert "dentist" in result

    @pytest.mark.asyncio
    async def test_cancel_by_message_text(self, db_session, sample_group):
        """Cancel reminder using natural language description."""
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "dentist appointment", trigger,
        )
        await db_session.flush()

        entities = Entities(description="dentist")
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Cancelled" in result
        assert "dentist" in result

    @pytest.mark.asyncio
    async def test_cancel_no_match_returns_error(self, db_session, sample_group):
        """No matching reminder returns error."""
        entities = Entities(description="nonexistent")
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No active reminder" in result

    @pytest.mark.asyncio
    async def test_cancel_ambiguous_returns_disambiguation(self, db_session, sample_group):
        """Multiple matches returns disambiguation list."""
        trigger1 = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        trigger2 = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "meeting with team", trigger1,
        )
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "meeting with client", trigger2,
        )
        await db_session.flush()

        entities = Entities(description="meeting")
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Multiple" in result
        assert "team" in result
        assert "client" in result

    @pytest.mark.asyncio
    async def test_cancel_missing_identifier_returns_error(self, db_session, sample_group):
        """No number or description returns helpful error."""
        entities = Entities()
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify" in result.lower()


class TestHandleReminderSnooze:
    @pytest.mark.asyncio
    async def test_snooze_by_number(self, db_session, sample_group):
        """Snooze using item_number + datetime_raw."""
        trigger1 = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        trigger2 = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "first reminder", trigger1,
        )
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "second reminder", trigger2,
        )
        await db_session.flush()

        entities = Entities(item_number=2, datetime_raw="1h")
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Snoozed" in result
        assert "second reminder" in result

    @pytest.mark.asyncio
    async def test_snooze_by_message_text(self, db_session, sample_group):
        """Snooze using natural language description + datetime_raw."""
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "dentist appointment", trigger,
        )
        await db_session.flush()

        entities = Entities(description="dentist", datetime_raw="30m")
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "Snoozed" in result
        assert "dentist" in result

    @pytest.mark.asyncio
    async def test_snooze_invalid_number_returns_error(self, db_session, sample_group):
        """Out-of-range number returns error."""
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "only one", trigger,
        )
        await db_session.flush()

        entities = Entities(item_number=5, datetime_raw="1h")
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_snooze_missing_duration_returns_error(self, db_session, sample_group):
        """Number but no duration returns error."""
        entities = Entities(item_number=2)
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "duration" in result.lower()

    @pytest.mark.asyncio
    async def test_snooze_missing_identifier_returns_error(self, db_session, sample_group):
        """Duration but no number or description returns error."""
        entities = Entities(datetime_raw="1h")
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "specify" in result.lower()

    @pytest.mark.asyncio
    async def test_snooze_no_active_reminders(self, db_session, sample_group):
        """Snoozing when no active reminders exist."""
        entities = Entities(item_number=1, datetime_raw="1h")
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No active" in result or "not found" in result

    @pytest.mark.asyncio
    async def test_snooze_by_message_no_match(self, db_session, sample_group):
        """Snooze by message text with no match returns error."""
        entities = Entities(description="nonexistent", datetime_raw="1h")
        result = await handler.handle_reminder_snooze(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert "No active reminder" in result
