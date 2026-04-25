"""Tests for reminder business logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from piazza.core.exceptions import NotFoundError, ReminderError
from piazza.db.repositories import reminder as queries
from piazza.tools.reminders import service
from piazza.tools.reminders.service import (
    parse_snooze_duration,
    parse_time,
)
from piazza.tools.reminders.tasks import fire_reminders

# ---------- Time parsing ----------


class TestParseTime:
    def test_in_2_hours(self):
        result = parse_time("in 2 hours", "UTC")
        now = datetime.now(timezone.utc)
        # Should be roughly 2 hours from now (within 5 min tolerance)
        diff = (result - now).total_seconds()
        assert 6600 < diff < 7800  # between 1h50 and 2h10

    def test_unparseable_raises(self):
        with pytest.raises(ReminderError, match="Couldn't understand"):
            parse_time("gobbledygook xyz not a time", "UTC")

    def test_returns_timezone_aware(self):
        result = parse_time("in 1 hour", "UTC")
        assert result.tzinfo is not None


# ---------- Snooze duration parsing ----------


class TestParseSnooze:
    def test_1h(self):
        assert parse_snooze_duration("1h") == timedelta(hours=1)

    def test_30m(self):
        assert parse_snooze_duration("30m") == timedelta(minutes=30)

    def test_2h30m(self):
        assert parse_snooze_duration("2h30m") == timedelta(hours=2, minutes=30)

    def test_invalid_raises(self):
        with pytest.raises(ReminderError, match="parse duration"):
            parse_snooze_duration("abc")


# ---------- DB-backed CRUD ----------


class TestReminderCRUD:
    @pytest.mark.asyncio
    async def test_create_reminder(self, db_session, sample_group):
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        r = await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "test reminder", trigger,
        )
        await db_session.flush()
        assert r.status == "active"
        assert r.trigger_at == trigger

    @pytest.mark.asyncio
    async def test_list_active_reminders(self, db_session, sample_group):
        trigger1 = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
        trigger2 = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "second", trigger1,
        )
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "first", trigger2,
        )
        await db_session.flush()

        reminders = await queries.get_active_reminders(db_session, sample_group.group_id)
        assert len(reminders) == 2
        # Should be ordered by trigger_at
        assert reminders[0].message == "first"

    @pytest.mark.asyncio
    async def test_cancel_by_number(self, db_session, sample_group):
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "to cancel", trigger,
        )
        await db_session.flush()

        cancelled = await queries.cancel_reminder(db_session, sample_group.group_id, 1)
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, db_session, sample_group):
        result = await queries.cancel_reminder(db_session, sample_group.group_id, 99)
        assert result is None


class TestSetReminder:
    @pytest.mark.asyncio
    async def test_set_reminder_returns_model(self, db_session, sample_group):
        """Setting a reminder returns the Reminder model."""
        reminder = await service.set_reminder(
            db_session,
            sample_group.group_id,
            sample_group.alice.id,
            "pack for trip",
            "in 2 hours",
            tz="UTC",
        )
        assert reminder.message == "pack for trip"
        assert reminder.trigger_at is not None



class TestReminderService:
    @pytest.mark.asyncio
    async def test_list_no_reminders(self, db_session, sample_group):
        result = await service.list_reminders(db_session, sample_group.group_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_returns_models(self, db_session, sample_group):
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "item one", trigger,
        )
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "item two", trigger + timedelta(hours=1),
        )
        await db_session.flush()

        result = await service.list_reminders(db_session, sample_group.group_id)
        assert len(result) == 2
        assert result[0].message == "item one"
        assert result[1].message == "item two"

    @pytest.mark.asyncio
    async def test_cancel_by_number_returns_model(self, db_session, sample_group):
        trigger = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "cancel me", trigger,
        )
        await db_session.flush()

        reminder = await service.cancel_by_number(db_session, sample_group.group_id, 1)
        assert reminder.message == "cancel me"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_number_raises(self, db_session, sample_group):
        with pytest.raises(NotFoundError) as exc_info:
            await service.cancel_by_number(db_session, sample_group.group_id, 5)
        assert exc_info.value.entity == "reminder"
        assert exc_info.value.number == 5


class TestSnooze:
    @pytest.mark.asyncio
    async def test_snooze_1h(self, db_session, sample_group):
        trigger = datetime(2025, 3, 15, 10, 0, tzinfo=timezone.utc)
        r = await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "snooze me", trigger,
        )
        await db_session.flush()

        reminder = await service.snooze(db_session, r.id, "1h")
        assert reminder.message == "snooze me"

    @pytest.mark.asyncio
    async def test_snooze_30m(self, db_session, sample_group):
        trigger = datetime(2025, 3, 15, 10, 0, tzinfo=timezone.utc)
        r = await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "snooze me", trigger,
        )
        await db_session.flush()

        reminder = await service.snooze(db_session, r.id, "30m")
        assert reminder.message == "snooze me"


# ---------- Fire reminders task ----------


class TestFireReminders:
    @pytest.mark.asyncio
    async def test_due_reminders_fired(self, db_session, sample_group):
        """Past-due reminders are returned and marked fired."""
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "overdue", past,
        )
        await db_session.flush()

        payloads = await fire_reminders(db_session)
        assert len(payloads) == 1
        assert "overdue" in payloads[0][1]

    @pytest.mark.asyncio
    async def test_future_reminders_not_fired(self, db_session, sample_group):
        """Reminders in the future are not returned."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "not yet", future,
        )
        await db_session.flush()

        payloads = await fire_reminders(db_session)
        assert len(payloads) == 0
