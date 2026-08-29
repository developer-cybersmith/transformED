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
async def test_subscriber_handles_malformed_json(mocker) -> None:
    """Malformed JSON is logged and skipped -- never crashes, never forwards (AC3)."""
    from app.core.pubsub import _run_generation_progress_subscriber

    lesson_id = "lesson-bad-json"

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield _pmessage(f"generation_progress:{lesson_id}", {})  # placeholder, overwritten below
        raise asyncio.CancelledError

    # Overwrite with genuinely malformed data (not valid JSON at all).
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


@pytest.mark.unit
async def test_subscriber_zero_sessions_does_not_crash_or_send(mocker) -> None:
    """Zero waiting sessions is a normal outcome (AC4) -- no send, no exception."""
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
