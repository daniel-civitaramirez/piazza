"""Tests for reminder intent handlers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from piazza.db.repositories.reminder import create_reminder
from piazza.tools.reminders import handler
from piazza.tools.schemas import Entities


class TestHandleReminderSet:
    @pytest.mark.asyncio
    async def test_recurring_only(self, db_session, sample_group):
        """Setting a recurring reminder with only a recurrence rule succeeds."""
        entities = Entities(
            description="take pills",
            recurrence="FREQ=DAILY;BYHOUR=10;BYMINUTE=0",
        )
        result = await handler.handle_reminder_set(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "set_reminder"
        assert result["recurrence"] == "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        assert "trigger_at" in result

    @pytest.mark.asyncio
    async def test_one_time(self, db_session, sample_group):
        entities = Entities(description="dentist", datetime_raw="in 2 hours")
        result = await handler.handle_reminder_set(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert "recurrence" not in result

    @pytest.mark.asyncio
    async def test_missing_both_time_and_recurrence(self, db_session, sample_group):
        entities = Entities(description="x")
        result = await handler.handle_reminder_set(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_time"

    @pytest.mark.asyncio
    async def test_invalid_rrule_returns_error(self, db_session, sample_group):
        entities = Entities(description="x", recurrence="garbage")
        result = await handler.handle_reminder_set(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "unparseable_time"

    @pytest.mark.asyncio
    async def test_past_datetime_returns_time_in_past(self, db_session, sample_group):
        entities = Entities(description="x", datetime_raw="2020-01-01 12:00")
        result = await handler.handle_reminder_set(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "time_in_past"
        assert result["raw"] == "2020-01-01 12:00"

    @pytest.mark.asyncio
    async def test_list_includes_recurrence(self, db_session, sample_group):
        entities = Entities(
            description="take pills",
            recurrence="FREQ=DAILY;BYHOUR=10;BYMINUTE=0",
        )
        await handler.handle_reminder_set(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )

        listing = await handler.handle_reminder_list(
            db_session, sample_group.group_id, sample_group.alice.id, Entities()
        )
        assert listing["status"] == "list"
        assert listing["reminders"][0]["recurrence"] == "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"


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
        assert result["status"] == "ok"
        assert result["action"] == "cancel_reminder"
        assert "dentist" in result["message"]

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
        assert result["status"] == "ok"
        assert result["action"] == "cancel_reminder"
        assert "dentist" in result["message"]

    @pytest.mark.asyncio
    async def test_cancel_no_match_returns_not_found(self, db_session, sample_group):
        """No matching reminder returns not_found dict."""
        entities = Entities(description="nonexistent")
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "reminder"
        assert result["query"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_cancel_ambiguous_returns_disambiguation(self, db_session, sample_group):
        """Multiple matches returns ambiguous dict."""
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
        assert result["status"] == "ambiguous"
        assert result["entity"] == "reminder"
        assert len(result["matches"]) == 2
        messages = [m["message"] for m in result["matches"]]
        assert "meeting with team" in messages
        assert "meeting with client" in messages

    @pytest.mark.asyncio
    async def test_cancel_missing_identifier_returns_error(self, db_session, sample_group):
        """No number or description returns missing_identifier error."""
        entities = Entities()
        result = await handler.handle_reminder_cancel(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"


class TestHandleReminderUpdate:
    @pytest.mark.asyncio
    async def test_update_time_by_number(self, db_session, sample_group):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "first reminder", future,
        )
        await db_session.flush()

        entities = Entities(item_number=1, datetime_raw="in 1 hour")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "update_reminder"
        assert "first reminder" in result["message"]

    @pytest.mark.asyncio
    async def test_rename_by_message_text(self, db_session, sample_group):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "dentist appointment", future,
        )
        await db_session.flush()

        entities = Entities(description="dentist", new_description="dental cleaning")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ok"
        assert result["action"] == "update_reminder"
        assert result["message"] == "dental cleaning"

    @pytest.mark.asyncio
    async def test_update_invalid_number_returns_not_found(self, db_session, sample_group):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "only one", future,
        )
        await db_session.flush()

        entities = Entities(item_number=5, datetime_raw="in 1 hour")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "reminder"
        assert result["number"] == 5
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_missing_identifier_returns_error(self, db_session, sample_group):
        entities = Entities(datetime_raw="in 1 hour")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "missing_identifier"

    @pytest.mark.asyncio
    async def test_nothing_to_update_returns_error(self, db_session, sample_group):
        entities = Entities(item_number=1)
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "nothing_to_update"

    @pytest.mark.asyncio
    async def test_update_to_past_returns_time_in_past(self, db_session, sample_group):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "x", future,
        )
        await db_session.flush()

        entities = Entities(item_number=1, datetime_raw="2020-01-01 12:00")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "error"
        assert result["reason"] == "time_in_past"

    @pytest.mark.asyncio
    async def test_ambiguous_returns_disambiguation(self, db_session, sample_group):
        future = datetime.now(timezone.utc) + timedelta(days=10)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "meeting with team", future,
        )
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "meeting with client", future + timedelta(hours=1),
        )
        await db_session.flush()

        entities = Entities(description="meeting", datetime_raw="in 2 hours")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "ambiguous"
        assert result["entity"] == "reminder"
        assert len(result["matches"]) == 2

    @pytest.mark.asyncio
    async def test_update_by_message_no_match(self, db_session, sample_group):
        entities = Entities(description="nonexistent", datetime_raw="in 1 hour")
        result = await handler.handle_reminder_update(
            db_session, sample_group.group_id, sample_group.alice.id, entities
        )
        assert result["status"] == "not_found"
        assert result["entity"] == "reminder"
        assert result["query"] == "nonexistent"
