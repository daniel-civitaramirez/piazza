"""Tests for reminder repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from piazza.db.repositories.reminder import (
    cancel_active_reminder,
    cancel_reminder,
    create_reminder,
    get_active_reminders,
    get_due_reminders,
    update_active_reminder,
    update_reminder_status,
)


class TestCreateReminder:
    @pytest.mark.asyncio
    async def test_creates_active(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        reminder = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "test reminder", trigger,
        )
        assert reminder.status == "active"
        assert reminder.message == "test reminder"


class TestGetActiveReminders:
    @pytest.mark.asyncio
    async def test_excludes_cancelled(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "first", trigger,
        )
        r2 = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "second", trigger + timedelta(hours=1),
        )
        r2.status = "cancelled"
        await db_session.flush()

        active = await get_active_reminders(db_session, sample_group.group_id)
        assert len(active) == 1
        assert active[0].message == "first"

    @pytest.mark.asyncio
    async def test_ordered_by_trigger_at(self, db_session, sample_group):
        now = datetime.now(timezone.utc)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "later", now + timedelta(hours=2),
        )
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "sooner", now + timedelta(hours=1),
        )
        active = await get_active_reminders(db_session, sample_group.group_id)
        assert active[0].message == "sooner"


class TestGetDueReminders:
    @pytest.mark.asyncio
    async def test_returns_past_due(self, db_session, sample_group):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "overdue", past,
        )
        due = await get_due_reminders(db_session, datetime.now(timezone.utc))
        assert len(due) == 1

    @pytest.mark.asyncio
    async def test_excludes_future(self, db_session, sample_group):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "future", future,
        )
        due = await get_due_reminders(db_session, datetime.now(timezone.utc))
        assert len(due) == 0


class TestCancelReminder:
    @pytest.mark.asyncio
    async def test_cancel_valid(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "cancel me", trigger,
        )
        result = await cancel_reminder(db_session, sample_group.group_id, 1)
        assert result is not None
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_out_of_range(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "only one", trigger,
        )
        result = await cancel_reminder(db_session, sample_group.group_id, 5)
        assert result is None

    @pytest.mark.asyncio
    async def test_zero_returns_none(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "item", trigger,
        )
        result = await cancel_reminder(db_session, sample_group.group_id, 0)
        assert result is None


class TestRecurrenceColumn:
    @pytest.mark.asyncio
    async def test_round_trip(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        rule = "FREQ=DAILY;BYHOUR=10;BYMINUTE=0"
        created = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "take pills", trigger, recurrence=rule,
        )
        assert created.recurrence == rule

        active = await get_active_reminders(db_session, sample_group.group_id)
        assert active[0].recurrence == rule

    @pytest.mark.asyncio
    async def test_default_none(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        reminder = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "one-time", trigger,
        )
        assert reminder.recurrence is None


class TestCancelActiveReminder:
    @pytest.mark.asyncio
    async def test_cancels_active(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        r = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "active one", trigger,
        )
        ok = await cancel_active_reminder(db_session, r.id)
        assert ok is True

    @pytest.mark.asyncio
    async def test_skips_already_fired(self, db_session, sample_group):
        """Cannot cancel a reminder that the cron has already fired.

        Regression: the previous unguarded UPDATE would happily overwrite
        status='fired' back to 'cancelled', erasing the firing record.
        """
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        r = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "already fired", trigger,
        )
        await update_reminder_status(db_session, r.id, "fired")

        ok = await cancel_active_reminder(db_session, r.id)
        assert ok is False

        # Status remains 'fired', not 'cancelled'.
        await db_session.refresh(r)
        assert r.status == "fired"


class TestUpdateActiveReminder:
    @pytest.mark.asyncio
    async def test_updates_trigger_at(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        r = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "update me", trigger,
        )
        new_time = trigger + timedelta(hours=1)
        ok = await update_active_reminder(db_session, r.id, new_trigger_at=new_time)
        assert ok is True

        rows = await get_active_reminders(db_session, sample_group.group_id)
        assert rows[0].trigger_at == new_time

    @pytest.mark.asyncio
    async def test_updates_message(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        r = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "old text", trigger,
        )
        ok = await update_active_reminder(db_session, r.id, new_message="new text")
        assert ok is True

        rows = await get_active_reminders(db_session, sample_group.group_id)
        assert rows[0].message == "new text"

    @pytest.mark.asyncio
    async def test_skips_already_fired(self, db_session, sample_group):
        """Cannot update a reminder that the cron has already fired."""
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        r = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "fired one", trigger,
        )
        await update_reminder_status(db_session, r.id, "fired")

        new_time = trigger + timedelta(hours=2)
        ok = await update_active_reminder(db_session, r.id, new_trigger_at=new_time)
        assert ok is False
        await db_session.refresh(r)
        assert r.status == "fired"

    @pytest.mark.asyncio
    async def test_no_values_returns_false(self, db_session, sample_group):
        trigger = datetime.now(timezone.utc) + timedelta(hours=1)
        r = await create_reminder(
            db_session, sample_group.group_id, sample_group.alice.id,
            "x", trigger,
        )
        ok = await update_active_reminder(db_session, r.id)
        assert ok is False
