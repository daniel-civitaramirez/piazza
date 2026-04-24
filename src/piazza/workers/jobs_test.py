"""Tests for arq job wrappers — lock serialization."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from piazza.core.exceptions import GENERIC_ERROR_RESPONSE


def _raw_message(group_jid: str = "120363001@g.us", text: str = "hello") -> dict:
    return {
        "sender_jid": "5511111111111@s.whatsapp.net",
        "sender_name": "Alice",
        "group_jid": group_jid,
        "text": text,
    }


@pytest.fixture
def _stub_externals():
    """Stub WhatsApp client and DB logging so jobs don't need real infra."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    with (
        patch(
            "piazza.messaging.whatsapp.client.send_typing",
            new_callable=AsyncMock,
        ),
        patch(
            "piazza.messaging.whatsapp.client.send_text",
            new_callable=AsyncMock,
            return_value="wa_msg_id",
        ),
        patch("piazza.db.engine.AsyncSessionFactory", return_value=mock_session),
        patch(
            "piazza.db.repositories.group.get_or_create_group",
            new_callable=AsyncMock,
            return_value=(AsyncMock(id="gid"), True),
        ),
        patch(
            "piazza.db.repositories.member.get_or_create_member",
            new_callable=AsyncMock,
            return_value=AsyncMock(id="mid"),
        ),
        patch(
            "piazza.db.repositories.message_log.create_entry",
            new_callable=AsyncMock,
        ),
    ):
        yield


class TestLockReleasedOnFailure:
    """Lock must be released after every failure mode so the next message proceeds."""

    @pytest.mark.asyncio
    async def test_llm_timeout_releases_lock(self, redis_client, _stub_externals):
        """AgentTimeoutError inside process_message does not strand the lock."""
        from piazza.agent.base import AgentTimeoutError
        from piazza.workers.jobs import process_message_job

        call_count = 0

        async def timeout_then_ok(msg, session, redis):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise AgentTimeoutError("ollama 10s timeout")
            return "recovered"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message", side_effect=timeout_then_ok
        ):
            r1 = await process_message_job(ctx, _raw_message())
            r2 = await process_message_job(ctx, _raw_message())

        assert r1 == GENERIC_ERROR_RESPONSE
        assert r2 == "recovered"

    @pytest.mark.asyncio
    async def test_llm_unavailable_releases_lock(self, redis_client, _stub_externals):
        """AgentUnavailableError inside process_message does not strand the lock."""
        from piazza.agent.base import AgentUnavailableError
        from piazza.workers.jobs import process_message_job

        call_count = 0

        async def unavailable_then_ok(msg, session, redis):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise AgentUnavailableError("ollama connection refused")
            return "recovered"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message",
            side_effect=unavailable_then_ok,
        ):
            r1 = await process_message_job(ctx, _raw_message())
            r2 = await process_message_job(ctx, _raw_message())

        assert r1 == GENERIC_ERROR_RESPONSE
        assert r2 == "recovered"

    @pytest.mark.asyncio
    async def test_db_error_releases_lock(self, redis_client, _stub_externals):
        """A database error during processing does not strand the lock."""
        from piazza.workers.jobs import process_message_job

        call_count = 0

        async def db_fail_then_ok(msg, session, redis):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("asyncpg: connection reset")
            return "recovered"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message",
            side_effect=db_fail_then_ok,
        ):
            r1 = await process_message_job(ctx, _raw_message())
            r2 = await process_message_job(ctx, _raw_message())

        assert r1 == GENERIC_ERROR_RESPONSE
        assert r2 == "recovered"

    @pytest.mark.asyncio
    async def test_cancelled_error_releases_lock(self, redis_client, _stub_externals):
        """asyncio.CancelledError (arq job timeout) does not strand the lock.

        arq cancels the task via CancelledError when job_timeout is exceeded.
        CancelledError is a BaseException, not Exception, so it bypasses
        'except Exception'. The lock must still be released via finally.
        """
        from piazza.workers.jobs import process_message_job

        async def hang_forever(msg, session, redis):
            await asyncio.sleep(999)
            return "never"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message", side_effect=hang_forever
        ):
            task = asyncio.create_task(process_message_job(ctx, _raw_message()))
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # Lock must be free — next message acquires immediately
        lock_key = "lock:group:120363001@g.us"
        lock = redis_client.lock(lock_key, timeout=5)
        acquired = await lock.acquire(blocking_timeout=0.1)
        assert acquired, "Lock should be free after CancelledError"
        await lock.release()

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_releases_lock(
        self, redis_client, _stub_externals
    ):
        """KeyboardInterrupt (BaseException) does not strand the lock."""
        from piazza.workers.jobs import process_message_job

        async def raise_kb(msg, session, redis):
            raise KeyboardInterrupt()

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message", side_effect=raise_kb
        ):
            with pytest.raises(KeyboardInterrupt):
                await process_message_job(ctx, _raw_message())

        lock_key = "lock:group:120363001@g.us"
        lock = redis_client.lock(lock_key, timeout=5)
        acquired = await lock.acquire(blocking_timeout=0.1)
        assert acquired, "Lock should be free after KeyboardInterrupt"
        await lock.release()


class TestLockUnderConcurrentLoad:
    """Verify lock behaviour under heavier concurrent scenarios."""

    @pytest.mark.asyncio
    async def test_burst_of_messages_all_complete(
        self, redis_client, _stub_externals, monkeypatch
    ):
        """Five rapid messages to the same group: each either processes or gets a timeout error."""
        from piazza.config.settings import settings
        from piazza.workers.jobs import process_message_job

        monkeypatch.setattr(settings, "group_lock_wait", 0.3)

        results: list[str] = []

        async def fast_process(msg, session, redis):
            await asyncio.sleep(0.05)
            return "ok"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message", side_effect=fast_process
        ):
            tasks = []
            for i in range(5):
                await asyncio.sleep(0.01)
                tasks.append(asyncio.create_task(process_message_job(ctx, _raw_message())))
            results = list(await asyncio.gather(*tasks))

        # Every result is either a successful response or the generic error
        for r in results:
            assert r in ("ok", GENERIC_ERROR_RESPONSE)
        # At least one must have succeeded
        assert "ok" in results

    @pytest.mark.asyncio
    async def test_failure_in_one_group_does_not_block_another(
        self, redis_client, _stub_externals
    ):
        """A crash in group A must not prevent group B from proceeding."""
        from piazza.workers.jobs import process_message_job

        async def dispatch(msg, session, redis):
            if msg.group_jid == "group_a@g.us":
                raise RuntimeError("group A exploded")
            return "group B ok"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message", side_effect=dispatch
        ):
            ra, rb = await asyncio.gather(
                process_message_job(ctx, _raw_message(group_jid="group_a@g.us")),
                process_message_job(ctx, _raw_message(group_jid="group_b@g.us")),
            )

        assert ra == GENERIC_ERROR_RESPONSE
        assert rb == "group B ok"

    @pytest.mark.asyncio
    async def test_alternating_failures_never_strand_lock(
        self, redis_client, _stub_externals
    ):
        """Alternating crash/success across 4 sequential messages never strands the lock."""
        from piazza.workers.jobs import process_message_job

        call_count = 0

        async def alternate(msg, session, redis):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 1:
                raise RuntimeError(f"crash #{call_count}")
            return f"ok #{call_count}"

        ctx = {"redis": redis_client}
        results = []
        with patch(
            "piazza.workers.process_message.process_message", side_effect=alternate
        ):
            for _ in range(4):
                results.append(await process_message_job(ctx, _raw_message()))

        assert results == [
            GENERIC_ERROR_RESPONSE,
            "ok #2",
            GENERIC_ERROR_RESPONSE,
            "ok #4",
        ]


class TestGroupLockConcurrency:
    """Verify per-group lock serialises concurrent messages."""

    @pytest.mark.asyncio
    async def test_concurrent_same_group_serialized(
        self, redis_client, _stub_externals
    ):
        """Two messages to the same group must not run process_message concurrently."""
        from piazza.workers.jobs import process_message_job

        call_order: list[str] = []

        async def slow_process(msg, session, redis):
            call_order.append("start")
            await asyncio.sleep(0.15)
            call_order.append("end")
            return "ok"

        ctx = {"redis": redis_client}
        with patch("piazza.workers.process_message.process_message", side_effect=slow_process):
            t1 = asyncio.create_task(process_message_job(ctx, _raw_message()))
            # Small stagger so t1 acquires first
            await asyncio.sleep(0.01)
            t2 = asyncio.create_task(process_message_job(ctx, _raw_message()))
            await asyncio.gather(t1, t2)

        # Serialised: start-end-start-end (no interleaving)
        assert call_order == ["start", "end", "start", "end"]

    @pytest.mark.asyncio
    async def test_concurrent_different_groups_parallel(
        self, redis_client, _stub_externals
    ):
        """Messages to different groups must run in parallel, not serialised."""
        from piazza.workers.jobs import process_message_job

        running = asyncio.Event()
        other_saw_running = False

        async def process_group_a(msg, session, redis):
            running.set()
            await asyncio.sleep(0.15)
            return "ok"

        async def process_group_b(msg, session, redis):
            nonlocal other_saw_running
            # Wait briefly for group A to start
            await asyncio.sleep(0.02)
            other_saw_running = running.is_set()
            return "ok"

        call_count = 0

        async def dispatch_process(msg, session, redis):
            nonlocal call_count
            call_count += 1
            if msg.group_jid == "group_a@g.us":
                return await process_group_a(msg, session, redis)
            return await process_group_b(msg, session, redis)

        ctx = {"redis": redis_client}
        with patch("piazza.workers.process_message.process_message", side_effect=dispatch_process):
            await asyncio.gather(
                process_message_job(ctx, _raw_message(group_jid="group_a@g.us")),
                process_message_job(ctx, _raw_message(group_jid="group_b@g.us")),
            )

        assert call_count == 2
        assert other_saw_running, "Group B should have run while Group A was still processing"

    @pytest.mark.asyncio
    async def test_lock_timeout_returns_error(self, redis_client, _stub_externals):
        """When a second message can't acquire the lock in time, it returns the error response."""
        from piazza.config.settings import settings
        from piazza.workers.jobs import process_message_job

        original_wait = settings.group_lock_wait

        async def hold_lock_long(msg, session, redis):
            await asyncio.sleep(0.5)
            return "ok"

        ctx = {"redis": redis_client}
        # Use a very short wait so the second message times out quickly
        settings.group_lock_wait = 0.05
        try:
            with patch(
                "piazza.workers.process_message.process_message", side_effect=hold_lock_long
            ):
                t1 = asyncio.create_task(process_message_job(ctx, _raw_message()))
                await asyncio.sleep(0.01)
                t2 = asyncio.create_task(process_message_job(ctx, _raw_message()))
                r1, r2 = await asyncio.gather(t1, t2)
        finally:
            settings.group_lock_wait = original_wait

        assert r1 == "ok"
        assert r2 == GENERIC_ERROR_RESPONSE

    @pytest.mark.asyncio
    async def test_lock_released_after_exception(self, redis_client, _stub_externals):
        """Lock is released even when process_message raises, so the next message proceeds."""
        from piazza.workers.jobs import process_message_job

        call_count = 0

        async def fail_then_succeed(msg, session, redis):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            return "recovered"

        ctx = {"redis": redis_client}
        with patch(
            "piazza.workers.process_message.process_message", side_effect=fail_then_succeed
        ):
            r1 = await process_message_job(ctx, _raw_message())
            r2 = await process_message_job(ctx, _raw_message())

        assert r1 == GENERIC_ERROR_RESPONSE
        assert r2 == "recovered"

    @pytest.mark.asyncio
    async def test_no_redis_skips_lock(self, _stub_externals):
        """When Redis is unavailable, processing proceeds without locking."""
        from piazza.workers.jobs import process_message_job

        async def echo(msg, session, redis):
            return "no-lock-ok"

        ctx: dict = {"redis": None}
        with patch("piazza.workers.process_message.process_message", side_effect=echo):
            result = await process_message_job(ctx, _raw_message())

        assert result == "no-lock-ok"
