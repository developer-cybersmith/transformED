"""
Unit tests for Story BR-1: `generation_progress` Redis pub/sub -> WebSocket
forwarding transport (closes the Dev-4 half of W-D13).

Mirrors test_lesson_ready_pubsub.py's subscriber-behavior tests, with one
deliberate difference: these tests mock `app.core.db.get_supabase` DIRECTLY
rather than relying on `app.config.get_settings` patch-order to cascade into
it. D136 (docs/DEFECT-REGISTER.md) documents why the existing lesson_ready
subscriber tests are import-order-fragile when run in isolation; mocking
get_supabase directly here sidesteps that class of bug entirely rather than
inheriting it.

All tests are ``@pytest.mark.unit``. ``asyncio_mode = "auto"`` (pyproject.toml)
-- no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_supabase(session_ids: list[str]) -> MagicMock:
    """Supabase client stub for `_sessions_awaiting`'s sessions select.

    Mirrors `_sessions_awaiting`'s exact call chain:
    `.table("sessions").select("session_id").eq("lesson_id", lesson_id).execute()`
    -> `.data` is a list of dicts (per `app.core.db.rows`).
    """
    mock = MagicMock()
    resp = MagicMock()
    resp.data = [{"session_id": sid} for sid in session_ids]
    (mock.table.return_value.select.return_value.eq.return_value.execute.return_value) = resp
    return mock


def _pmessage(channel: str, payload: dict) -> dict:
    return {
        "type": "pmessage",
        "pattern": b"generation_progress:*",
        "channel": channel.encode(),
        "data": json.dumps(payload).encode(),
    }


def _patch_subscriber_deps(mocker, mock_sub_conn, mock_supabase):
    """Patch the two things `_run_generation_progress_subscriber` needs:
    the dedicated Redis connection factory, and the Supabase client used by
    the shared `_sessions_awaiting()` helper. Deliberately does NOT patch
    `app.config.get_settings` as the sole guard against real Settings()
    construction — patches `app.core.db.get_supabase` directly instead, so
    this suite cannot inherit D136's import-order fragility.
    """
    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn
    mocker.patch("app.core.db.get_supabase", return_value=mock_supabase)
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)


@pytest.mark.unit
async def test_subscriber_forwards_pmessage_to_manager(mocker) -> None:
    """A valid pmessage on generation_progress:{lesson_id} forwards verbatim
    to every session waiting on that lesson (AC2)."""
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-progress-1"
    session_id = "sess-1"
    payload = {
        "type": "generation_progress",
        "payload": {
            "lesson_id": lesson_id,
            "node": "tts_node",
            "progress": 0.5,
            "message": "Synthesising narration...",
        },
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield _pmessage(f"generation_progress:{lesson_id}", payload)
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase([session_id]))

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(mock_manager)

    mock_manager.send.assert_called_once_with(session_id, payload)
    mock_pubsub.psubscribe.assert_awaited_once_with("generation_progress:*")


@pytest.mark.unit
async def test_subscriber_forwards_to_multiple_waiting_sessions(mocker) -> None:
    """Two sessions waiting on the same lesson both receive the forward."""
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-progress-multi"
    payload = {
        "type": "generation_progress",
        "payload": {
            "lesson_id": lesson_id,
            "node": "slide_generator",
            "progress": 0.8,
            "message": "...",
        },
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield _pmessage(f"generation_progress:{lesson_id}", payload)
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase(["sess-a", "sess-b"]))

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(mock_manager)

    assert mock_manager.send.await_count == 2
    mock_manager.send.assert_any_await("sess-a", payload)
    mock_manager.send.assert_any_await("sess-b", payload)


@pytest.mark.unit
async def test_subscriber_handles_malformed_json(mocker, caplog) -> None:
    """Malformed JSON is logged at error level (AC3) and skipped -- never
    crashes, never forwards. Review finding (AC Completeness / Test Coverage):
    the earlier version of this test proved "skipped" but never asserted the
    "logged" half of the AC -- caplog closes that gap."""
    caplog.set_level(logging.ERROR, logger="app.core.pubsub")
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-bad-json"

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen_malformed():
        yield {
            "type": "pmessage",
            "pattern": b"generation_progress:*",
            "channel": f"generation_progress:{lesson_id}".encode(),
            "data": b"not-json",
        }
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen_malformed
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase(["sess-1"]))

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(mock_manager)

    mock_manager.send.assert_not_called()
    assert any(
        "malformed JSON" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records
    ), caplog.text


@pytest.mark.unit
async def test_subscriber_zero_sessions_does_not_crash_or_send(mocker, caplog) -> None:
    """Zero waiting sessions is a normal outcome (AC4) -- no send, no exception,
    logged as INFO, never as an error. Review finding (AC Completeness / Test
    Coverage): the earlier version only proved "no crash/no send"; caplog
    closes the "informational, never error" half."""
    caplog.set_level(logging.INFO, logger="app.core.pubsub")
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-nobody-waiting"
    payload = {
        "type": "generation_progress",
        "payload": {
            "lesson_id": lesson_id,
            "node": "quiz_generator",
            "progress": 0.2,
            "message": "...",
        },
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield _pmessage(f"generation_progress:{lesson_id}", payload)
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase([]))  # nobody waiting

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(mock_manager)

    mock_manager.send.assert_not_called()
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("0 sessions waiting" in r.getMessage() for r in info_records), caplog.text
    assert not any(r.levelno >= logging.ERROR for r in caplog.records), caplog.text


@pytest.mark.unit
async def test_subscriber_never_writes_a_cache_key(mocker) -> None:
    """Unlike lesson_ready, generation_progress has no caching side effect (AC2) --
    the dedicated connection's `.set()` must never be called."""
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-no-cache"
    payload = {
        "type": "generation_progress",
        "payload": {
            "lesson_id": lesson_id,
            "node": "narration_script",
            "progress": 0.3,
            "message": "...",
        },
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield _pmessage(f"generation_progress:{lesson_id}", payload)
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mock_sub_conn.set = AsyncMock()

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase(["sess-1"]))

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(mock_manager)

    mock_sub_conn.set.assert_not_called()


@pytest.mark.unit
async def test_subscriber_uses_its_own_dedicated_connection(mocker) -> None:
    """AC6: the generation_progress listener opens its OWN Redis.from_url()
    connection -- proven by asserting Redis.from_url was called with
    decode_responses=True, the same construction lesson_ready's listener uses,
    independent of the shared pool."""
    from app.core.pubsub import _run_generation_progress_subscriber

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _hang_listen():
        await asyncio.Event().wait()
        yield  # pragma: no cover -- unreachable (cancelled while waiting)

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _hang_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    mock_redis_cls = mocker.patch("app.core.pubsub.Redis")
    mock_redis_cls.from_url.return_value = mock_sub_conn
    mocker.patch("app.core.db.get_supabase", return_value=_make_mock_supabase([]))
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    task = asyncio.create_task(_run_generation_progress_subscriber(mock_manager))
    try:
        for _ in range(10):
            if mock_pubsub.psubscribe.await_count:
                break
            await asyncio.sleep(0)
        mock_redis_cls.from_url.assert_called_once_with(
            "redis://localhost:6379/0", decode_responses=True
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.unit
async def test_start_generation_progress_listener_returns_cancellable_task(mocker) -> None:
    """Lifespan-wiring contract, mirrors test_start_lesson_ready_listener_returns_cancellable_task:
    a named, cancellable asyncio.Task that actually schedules the generation_progress
    subscriber (proven by reaching psubscribe), not some other coroutine (AC1)."""
    mocker.patch("app.core.db.get_supabase", return_value=_make_mock_supabase([]))
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    async def _hang_listen():
        await asyncio.Event().wait()
        yield  # pragma: no cover -- unreachable (cancelled while waiting)

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _hang_listen

    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn

    from app.core.pubsub import start_generation_progress_listener

    task = await start_generation_progress_listener(MagicMock())
    try:
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "generation_progress_subscriber"

        for _ in range(10):
            if mock_pubsub.psubscribe.await_count:
                break
            await asyncio.sleep(0)
        mock_pubsub.psubscribe.assert_awaited_once_with("generation_progress:*")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# -- Review findings (2026-08-29, 8-layer BMAD review of PR #162) ------------
# 4 independent layers (AC Completeness, Story Quality, Edge Case Hunter, Test
# Coverage) flagged AC5's backoff/reconnect path as entirely untested; Edge
# Case Hunter additionally flagged the on_message hook's exception-safety path
# and the non-pmessage-filter / multi-message-in-one-loop edge cases as
# untested for this channel (lesson_ready has integration-level coverage for
# both via tests/integration/test_lesson_ready_integration.py; this channel
# had none). Closed here rather than deferred, since the logic under test is
# the shared `_run_pubsub_forwarder` and the fix is cheap.


@pytest.mark.unit
async def test_subscriber_crash_triggers_backoff_and_reconnects(mocker) -> None:
    """AC5: a generic Exception (not CancelledError) inside the loop closes
    the crashed connection, sleeps for `min(2**attempt, 30)`, then reconnects
    (psubscribe called again) -- rather than propagating or silently dying."""
    from app.core.pubsub import _run_generation_progress_subscriber

    attempt_counter = {"n": 0}

    async def _crash_then_cancel():
        attempt_counter["n"] += 1
        if attempt_counter["n"] == 1:
            raise RuntimeError("connection reset")
        raise asyncio.CancelledError
        yield  # pragma: no cover -- unreachable, makes this a real async generator

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _crash_then_cancel

    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mock_sub_conn.aclose = AsyncMock()

    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn
    mocker.patch("app.core.db.get_supabase", return_value=_make_mock_supabase([]))
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)
    mock_sleep = mocker.patch("app.core.pubsub.asyncio.sleep", new=AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(MagicMock())

    # attempt starts at 0 -> wait = min(2**0, 30) = 1.0
    mock_sleep.assert_awaited_once_with(1.0)
    # The connection is closed twice: once by the crash-recovery branch
    # (before sleeping/reconnecting), once more by the final CancelledError
    # shutdown -- both are correct (the latter is the review-fix for the
    # connection leak Blind Hunter found: shutdown must also close it).
    assert mock_sub_conn.aclose.await_count == 2
    # Reconnected: psubscribe ran again on the second while-loop iteration.
    assert mock_pubsub.psubscribe.await_count == 2


@pytest.mark.unit
async def test_on_message_hook_exception_does_not_escape_to_reconnect_handler(mocker) -> None:
    """A raising on_message hook is caught at the hook-call boundary and
    logged, not treated as a subscriber crash -- otherwise a hook-only
    failure would incorrectly trigger a full reconnect/backoff cycle."""
    from app.core.pubsub import _run_pubsub_forwarder

    lesson_id = "lesson-hook-raises"
    payload = {
        "type": "generation_progress",
        "payload": {"lesson_id": lesson_id, "node": "x", "progress": 0.1, "message": "m"},
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield _pmessage(f"br1test:{lesson_id}", payload)
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mock_sub_conn.aclose = AsyncMock()

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase(["sess-1"]))
    mock_sleep = mocker.patch("app.core.pubsub.asyncio.sleep", new=AsyncMock())

    async def _raising_hook(message, session_ids, sub_conn, lesson_id):
        raise ValueError("hook exploded")

    with pytest.raises(asyncio.CancelledError):
        await _run_pubsub_forwarder(
            mock_manager, channel_prefix="br1test", on_message=_raising_hook
        )

    # The message was still forwarded before the hook ran and raised.
    mock_manager.send.assert_called_once_with("sess-1", payload)
    # The hook's exception must NOT be treated as a subscriber crash -- no
    # backoff sleep (the exclusive signal of the except-Exception/crash
    # branch; aclose alone can't distinguish the two paths since the final
    # CancelledError shutdown also closes the connection, correctly).
    mock_sleep.assert_not_awaited()


@pytest.mark.unit
async def test_subscriber_ignores_non_pmessage_and_delivers_the_next_real_message(mocker) -> None:
    """A subscribe/psubscribe confirmation event (type != 'pmessage') is
    ignored -- no send, no crash -- and the loop keeps processing: the next
    real pmessage in the same listen() loop still delivers. Mirrors
    lesson_ready's own integration-level coverage of this exact scenario."""
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-with-confirmation"
    payload = {
        "type": "generation_progress",
        "payload": {"lesson_id": lesson_id, "node": "x", "progress": 0.4, "message": "m"},
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield {
            "type": "psubscribe",
            "pattern": b"generation_progress:*",
            "channel": b"generation_progress:*",
            "data": 1,
        }
        yield _pmessage(f"generation_progress:{lesson_id}", payload)
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    _patch_subscriber_deps(mocker, mock_sub_conn, _make_mock_supabase(["sess-1"]))

    with pytest.raises(asyncio.CancelledError):
        await _run_generation_progress_subscriber(mock_manager)

    mock_manager.send.assert_called_once_with("sess-1", payload)
