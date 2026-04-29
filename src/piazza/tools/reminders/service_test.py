"""Tests for reminder business logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from piazza.core.exceptions import NotFoundError, PastTimeError, ReminderError
from piazza.db.repositories import reminder as queries
from piazza.tools.reminders import service
from piazza.tools.reminders.service import (
    _validate_rrule,
    next_occurrence,
    occurrences_between,
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

    @pytest.mark.asyncio
    async def test_set_reminder_in_past_raises(self, db_session, sample_group):
        """Datetime that resolves to the past raises PastTimeError."""
        with pytest.raises(PastTimeError):
            await service.set_reminder(
                db_session,
                sample_group.group_id,
                sample_group.alice.id,
                "x",
                "2020-01-01 12:00",
                tz="UTC",
            )

    @pytest.mark.asyncio
    async def test_set_reminder_past_does_not_persist(self, db_session, sample_group):
        """A rejected past reminder must not leave a row in the DB."""
        with pytest.raises(PastTimeError):
            await service.set_reminder(
                db_session,
                sample_group.group_id,
                sample_group.alice.id,
                "x",
                "2020-01-01 12:00",
                tz="UTC",
            )
        assert await service.list_reminders(db_session, sample_group.group_id) == []



class TestRecurringReminder:
    def test_validate_rrule_accepts_daily(self):
        _validate_rrule("FREQ=DAILY;BYHOUR=10;BYMINUTE=0")

    def test_validate_rrule_accepts_weekly(self):
        _validate_rrule("FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0")

    def test_validate_rrule_rejects_garbage(self):
        with pytest.raises(ReminderError, match="recurrence rule"):
            _validate_rrule("not a rule")

    def test_next_occurrence_daily(self):
        now = datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc)
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        nxt = next_occurrence(rule, now)
        assert nxt == datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)

    def test_next_occurrence_after_today_rolls_to_tomorrow(self):
        now = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        nxt = next_occurrence(rule, now)
        assert nxt == datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)

    def test_next_occurrence_honors_group_tz(self):
        # 10:00 America/New_York on 2026-04-25 == 14:00 UTC (EDT, UTC-4).
        now = datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc)
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        nxt = next_occurrence(rule, now, tz="America/New_York")
        assert nxt == datetime(2026, 4, 25, 14, 0, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_set_reminder_recurrence_uses_group_tz(self, db_session, sample_group):
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        reminder = await service.set_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "take pills", datetime_raw=None, tz="America/New_York", recurrence=rule,
        )
        # First fire should be at 10:00 local, which is 14:00 or 15:00 UTC depending on DST.
        assert reminder.trigger_at.hour in (14, 15)
        assert reminder.trigger_at.minute == 0

    @pytest.mark.asyncio
    async def test_set_reminder_with_recurrence_and_no_datetime(self, db_session, sample_group):
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        reminder = await service.set_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "take pills", datetime_raw=None, tz="UTC", recurrence=rule,
        )
        assert reminder.recurrence == rule
        assert reminder.trigger_at.hour == 10
        assert reminder.trigger_at.minute == 0
        assert reminder.trigger_at > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_set_reminder_with_explicit_datetime_and_recurrence(
        self, db_session, sample_group
    ):
        rule = "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"
        reminder = await service.set_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "standup", datetime_raw="tomorrow 9am", tz="UTC", recurrence=rule,
        )
        assert reminder.recurrence == rule
        assert reminder.trigger_at is not None

    @pytest.mark.asyncio
    async def test_set_reminder_invalid_rrule_raises(self, db_session, sample_group):
        with pytest.raises(ReminderError):
            await service.set_reminder(
                db_session, sample_group.group_id, sample_group.alice.id,
                "x", datetime_raw=None, tz="UTC", recurrence="garbage",
            )

    def test_occurrences_between_excludes_aligned_start(self):
        """An aligned `start` (i.e. equal to a rule occurrence) must NOT appear in the list.

        Regression: at the original `inc=True`, the worker counted the
        already-due `trigger_at` itself as a backfill occurrence, producing
        a duplicate fire on every recurring reminder.
        """
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        # `start` is exactly an occurrence (10:00 UTC on the dot).
        start = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
        assert occurrences_between(rule, start, end) == []

    def test_occurrences_between_includes_intermediate(self):
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        start = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 27, 11, 0, tzinfo=timezone.utc)
        # Aligned start excluded; next two daily occurrences included.
        assert occurrences_between(rule, start, end) == [
            datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc),
        ]

    @pytest.mark.asyncio
    async def test_set_reminder_no_time_no_recurrence_raises(self, db_session, sample_group):
        with pytest.raises(ReminderError):
            await service.set_reminder(
                db_session, sample_group.group_id, sample_group.alice.id,
                "x", datetime_raw=None, tz="UTC", recurrence=None,
            )


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

    @pytest.mark.asyncio
    async def test_one_time_due_marked_fired(self, db_session, sample_group):
        """One-time due reminder is marked fired and disappears from active list."""
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "one-time", past,
        )
        await db_session.flush()

        await fire_reminders(db_session)
        active = await queries.get_active_reminders(db_session, sample_group.group_id)
        assert active == []

    @pytest.mark.asyncio
    async def test_recurring_due_advances_trigger(self, db_session, sample_group):
        """Recurring due reminder fires once and is rescheduled to next occurrence."""
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "take pills", past, recurrence=rule,
        )
        await db_session.flush()

        payloads = await fire_reminders(db_session)
        assert len(payloads) == 1

        active = await queries.get_active_reminders(db_session, sample_group.group_id)
        assert len(active) == 1
        assert active[0].status == "active"
        assert active[0].recurrence == rule
        # SQLite drops tz-info; normalize for comparison.
        new_trigger = active[0].trigger_at
        if new_trigger.tzinfo is None:
            new_trigger = new_trigger.replace(tzinfo=timezone.utc)
        assert new_trigger > past

    @pytest.mark.asyncio
    async def test_recurring_backfills_missed_occurrences(self, db_session, sample_group):
        """A daily reminder scheduled 3 days ago fires once for each missed day."""
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3, minutes=5)
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "take pills", three_days_ago, recurrence=rule,
        )
        await db_session.flush()

        payloads = await fire_reminders(db_session)
        # Originally-scheduled fire + ~3 missed daily occurrences.
        assert len(payloads) >= 3

        active = await queries.get_active_reminders(db_session, sample_group.group_id)
        assert len(active) == 1
        new_trigger = active[0].trigger_at
        if new_trigger.tzinfo is None:
            new_trigger = new_trigger.replace(tzinfo=timezone.utc)
        assert new_trigger > datetime.now(timezone.utc)


    @pytest.mark.asyncio
    async def test_corrupt_recurrence_does_not_block_other_reminders(
        self, db_session, sample_group
    ):
        """A bad recurrence rule on one row must not poison the whole batch.

        Regression: the loop used a single trailing commit, so any exception
        (e.g. rrulestr() rejecting a corrupt rule) aborted the whole tick
        and prevented every other due reminder from firing.
        """
        past = datetime.now(timezone.utc) - timedelta(minutes=5)

        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "valid one-time A", past,
        )
        # Bypass _validate_rrule by writing a corrupt rule via the repo.
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "corrupt recurring", past, recurrence="THIS_IS_NOT_AN_RRULE",
        )
        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "valid one-time B", past,
        )
        await db_session.flush()

        payloads = await fire_reminders(db_session)
        texts = [t for _, t in payloads]
        assert any("valid one-time A" in t for t in texts)
        assert any("valid one-time B" in t for t in texts)
        assert not any("corrupt recurring" in t for t in texts)

        # Valid reminders are now fired; the corrupt one stays active.
        active = await queries.get_active_reminders(db_session, sample_group.group_id)
        assert [r.message for r in active] == ["corrupt recurring"]

    @pytest.mark.asyncio
    async def test_recurring_aligned_trigger_no_duplicate(self, db_session, sample_group):
        """Regression: an aligned trigger_at must not produce a duplicate fire.

        Recurring reminders' rescheduled trigger_at is always rule-aligned
        (computed via next_occurrence). On the next firing pass,
        occurrences_between(rule, trigger_at, now) must NOT count
        trigger_at itself, otherwise the user gets two ⏰ messages.
        """
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        # Pick an aligned past trigger: yesterday at 10:00 UTC.
        now = datetime.now(timezone.utc)
        aligned_past = (now - timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        # Ensure it's strictly in the past (in case it's before 10:00 today).
        if aligned_past >= now:
            aligned_past -= timedelta(days=1)

        await queries.create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "take pills", aligned_past, recurrence=rule,
        )
        await db_session.flush()

        payloads = await fire_reminders(db_session)
        # 1 for the aligned past trigger, plus any later real occurrences
        # that have also passed by `now`. With inc=False those later
        # occurrences are counted exactly once each.
        today_10 = now.replace(hour=10, minute=0, second=0, microsecond=0)
        expected_extra = 1 if today_10 <= now else 0
        assert len(payloads) == 1 + expected_extra
