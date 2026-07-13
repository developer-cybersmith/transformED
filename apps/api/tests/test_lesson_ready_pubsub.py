"""
Unit tests for Bug #6: cross-process lesson_ready delivery via Redis pub/sub.

Covers five acceptance criteria:
  1. content_pipeline_job publishes to channel ``lesson_ready:{session_id}``
  2. Published message has the correct ws.ts shape (session_id + lesson_id in
     payload, no flat 'title' key)
  3. pubsub subscriber forwards a pmessage to manager.send(session_id, ...)
  4. pubsub subscriber handles malformed JSON without crashing
  5. Regression: routing reaches the correct WebSocket client when
     session_id != lesson_id

All tests are ``@pytest.mark.unit``.
``asyncio_mode = "auto"`` (pyproject.toml) -- no @pytest.mark.asyncio needed.

Patch-target note (mirrors test_websocket_session.py convention)
----------------------------------------------------------------
Lazy ``from X import Y`` inside a function resolves against the module
currently in sys.modules, so the effective patch target is always the
*source* module attribute, e.g. ``app.core.redis.get_redis``.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# -- Helpers -------------------------------------------------------------------


def _make_mock_supabase(session_id: str | None = None) -> MagicMock:
    """Supabase client stub returning a minimal lesson_jobs row.

    When *session_id* is provided, it is included in the row so the pipeline
    publishes to ``lesson_ready:{session_id}`` instead of falling back to
    ``lesson_ready:{lesson_id}``.  Omit it to exercise the fallback path.
    """
    mock = MagicMock()
    row: dict = {
        "user_id": "user-1",
        "extracted_text": "chapter text",
        "source_pdf_path": None,
    }
    if session_id is not None:
        row["session_id"] = session_id
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
        .data
    ) = row
    (
        mock.table.return_value
        .update.return_value
        .eq.return_value
        .execute.return_value
    ) = MagicMock()
    return mock


def _patch_pipeline_deps(mocker, mock_redis, mock_supabase, lesson_package):
    """Patch all lazy imports used inside content_pipeline_job."""
    mocker.patch("app.core.db.get_supabase", return_value=mock_supabase)
    mocker.patch(
        "app.modules.content.pipeline.graph.run_pipeline",
        new=AsyncMock(return_value=lesson_package),
    )
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    mocker.patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock())


# -- Tests 1 & 2: content_pipeline_job publish behaviour ----------------------


@pytest.mark.unit
async def test_publish_channel_uses_session_id(mocker) -> None:
    """publish() is called with channel ``lesson_ready:{session_id}``."""
    lesson_id = "lesson-abc-123"
    session_id = "lesson-abc-123"  # fallback: session_id == lesson_id when not in row
    # [DEV1-SPRINT2-PENDING] Fixture encodes today's flat package_builder_node
    # stub shape, not the frozen LessonPackage from Dev 1's real package_builder
    # (Story S2-11, not yet built). Do not build a parallel real-content path
    # against this fixture shape -- it will be reconciled when Sprint 2 lands.
    # Ping Dev 1 (developer1-cybersmith) before changing this shape.
    lesson_package: dict = {
        "lesson_plan": {"title": "Test Lesson"},
        "slides": [],
        "quiz_questions": [],
        "audio_assets": [],
    }

    mock_redis = AsyncMock()
    mock_supabase = _make_mock_supabase()  # no session_id in row -> falls back
    _patch_pipeline_deps(mocker, mock_redis, mock_supabase, lesson_package)

    from app.workers.jobs.content_pipeline import content_pipeline_job

    await content_pipeline_job(ctx={}, lesson_id=lesson_id)

    mock_redis.publish.assert_called_once()
    actual_channel = mock_redis.publish.call_args[0][0]
    assert actual_channel == f"lesson_ready:{session_id}"


@pytest.mark.unit
async def test_publish_message_has_correct_ws_shape(mocker) -> None:
    """Published JSON has session_id + lesson_id in payload; no flat 'title'."""
    lesson_id = "lesson-def-456"
    # [DEV1-SPRINT2-PENDING] Fixture encodes today's flat package_builder_node
    # stub shape, not the frozen LessonPackage from Dev 1's real package_builder
    # (Story S2-11, not yet built). Do not build a parallel real-content path
    # against this fixture shape -- it will be reconciled when Sprint 2 lands.
    # Ping Dev 1 (developer1-cybersmith) before changing this shape.
    lesson_package: dict = {
        "lesson_plan": {"title": "My Lesson"},
        "slides": [{"id": 1}],
        "quiz_questions": [],
        "audio_assets": [],
    }

    mock_redis = AsyncMock()
    mock_supabase = _make_mock_supabase()
    _patch_pipeline_deps(mocker, mock_redis, mock_supabase, lesson_package)

    from app.workers.jobs.content_pipeline import content_pipeline_job

    await content_pipeline_job(ctx={}, lesson_id=lesson_id)

    raw_json: str = mock_redis.publish.call_args[0][1]
    msg: dict = json.loads(raw_json)

    assert msg["type"] == "lesson_ready"
    assert "payload" in msg
    assert msg["payload"]["lesson_id"] == lesson_id
    assert msg["payload"]["session_id"] == lesson_id  # fallback path
    assert msg["payload"]["lesson"] == lesson_package
    assert "title" not in msg, "flat 'title' key must not appear at top level"


# -- Tests 3 & 4: pubsub subscriber behaviour ---------------------------------


@pytest.mark.unit
async def test_subscriber_forwards_pmessage_to_manager(mocker) -> None:
    """A valid pmessage causes manager.send(session_id, message) exactly once."""
    from app.core.pubsub import _run_lesson_subscriber

    session_id = "abc-123"
    payload = {
        "type": "lesson_ready",
        "payload": {"session_id": session_id, "lesson_id": session_id, "lesson": {}},
    }

    pmessage = {
        "type": "pmessage",
        "pattern": b"lesson_ready:*",
        "channel": f"lesson_ready:{session_id}".encode(),
        "data": json.dumps(payload).encode(),
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield pmessage
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen

    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn

    # _run_lesson_subscriber calls get_settings(); mock it so no real Settings()
    # (and no env vars) are required. Redis.from_url is already patched above, so
    # redis_url is never dialled — the stub only prevents Settings() construction.
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    with pytest.raises(asyncio.CancelledError):
        await _run_lesson_subscriber(mock_manager)

    mock_manager.send.assert_called_once_with(session_id, payload)


@pytest.mark.unit
async def test_subscriber_caches_lesson_package(mocker) -> None:
    """On a lesson_ready pmessage, the subscriber caches the package at lesson_package:{sid}."""
    from app.core.pubsub import _run_lesson_subscriber

    session_id = "cache-sess"
    payload = {
        "type": "lesson_ready",
        "payload": {"session_id": session_id, "lesson_id": session_id, "lesson": {"segments": []}},
    }
    pmessage = {
        "type": "pmessage",
        "pattern": b"lesson_ready:*",
        "channel": f"lesson_ready:{session_id}".encode(),
        "data": json.dumps(payload).encode(),
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield pmessage
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen

    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mock_sub_conn.set = AsyncMock()  # the cache write
    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn

    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    with pytest.raises(asyncio.CancelledError):
        await _run_lesson_subscriber(mock_manager)

    # Cached the package under the session-scoped key (in addition to forwarding it), with 24h TTL.
    mock_sub_conn.set.assert_called_once()
    args, kwargs = mock_sub_conn.set.call_args
    assert args[0] == f"lesson_package:{session_id}"
    assert json.loads(args[1]) == {"segments": []}  # cached value is the package JSON
    assert kwargs.get("ex") == 86400


@pytest.mark.unit
async def test_subscriber_handles_malformed_json(mocker) -> None:
    """Malformed JSON data is logged and does not propagate an exception."""
    from app.core.pubsub import _run_lesson_subscriber

    session_id = "bad-json-session"

    pmessage = {
        "type": "pmessage",
        "pattern": b"lesson_ready:*",
        "channel": f"lesson_ready:{session_id}".encode(),
        "data": b"not-json",
    }

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield pmessage
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen

    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub

    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn

    # _run_lesson_subscriber calls get_settings(); mock it so no real Settings()
    # (and no env vars) are required. Redis.from_url is already patched above, so
    # redis_url is never dialled — the stub only prevents Settings() construction.
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    with pytest.raises(asyncio.CancelledError):
        await _run_lesson_subscriber(mock_manager)

    mock_manager.send.assert_not_called()


# -- Test 5: regression -- session_id != lesson_id routing --------------------


@pytest.mark.unit
async def test_routing_reaches_correct_client_when_session_id_differs(mocker) -> None:
    """Regression: when session_id != lesson_id, the event reaches the WebSocket
    client identified by session_id, not lesson_id.

    Simulates the full pipeline path:
      - lesson_jobs row has an explicit session_id different from lesson_id
      - content_pipeline_job publishes to lesson_ready:{session_id}
      - subscriber extracts session_id from channel and calls manager.send(session_id, ...)
    """
    lesson_id = "lesson-uuid-999"
    session_id = "ws-session-uuid-111"  # genuinely different routing key

    # [DEV1-SPRINT2-PENDING] Fixture encodes today's flat package_builder_node
    # stub shape, not the frozen LessonPackage from Dev 1's real package_builder
    # (Story S2-11, not yet built). Do not build a parallel real-content path
    # against this fixture shape -- it will be reconciled when Sprint 2 lands.
    # Ping Dev 1 (developer1-cybersmith) before changing this shape.
    lesson_package: dict = {
        "lesson_plan": {"title": "Regression Lesson"},
        "slides": [],
        "quiz_questions": [],
        "audio_assets": [],
    }

    mock_redis = AsyncMock()
    # Row includes explicit session_id -- routes to the WebSocket client, not lesson_id
    mock_supabase = _make_mock_supabase(session_id=session_id)
    _patch_pipeline_deps(mocker, mock_redis, mock_supabase, lesson_package)

    from app.workers.jobs.content_pipeline import content_pipeline_job

    await content_pipeline_job(ctx={}, lesson_id=lesson_id)

    mock_redis.publish.assert_called_once()
    published_channel: str = mock_redis.publish.call_args[0][0]
    published_json: str = mock_redis.publish.call_args[0][1]
    published_msg: dict = json.loads(published_json)

    # Channel must route to the WebSocket session, NOT the lesson
    assert published_channel == f"lesson_ready:{session_id}", (
        f"expected channel lesson_ready:{session_id}, got {published_channel}"
    )
    assert published_channel != f"lesson_ready:{lesson_id}", (
        "channel must not fall back to lesson_id when session_id is present"
    )

    # Payload must carry both IDs so the client can correlate
    assert published_msg["payload"]["session_id"] == session_id
    assert published_msg["payload"]["lesson_id"] == lesson_id

    # Simulate the subscriber receiving this message and verify it dispatches
    # to manager.send with session_id (not lesson_id)
    from app.core.pubsub import _run_lesson_subscriber

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()

    async def _fake_listen():
        yield {
            "type": "pmessage",
            "pattern": b"lesson_ready:*",
            "channel": published_channel.encode(),
            "data": published_json.encode(),
        }
        raise asyncio.CancelledError

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _fake_listen
    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn

    # _run_lesson_subscriber calls get_settings(); mock it so no real Settings()
    # (and no env vars) are required. Redis.from_url is already patched above, so
    # redis_url is never dialled — the stub only prevents Settings() construction.
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    with pytest.raises(asyncio.CancelledError):
        await _run_lesson_subscriber(mock_manager)

    # manager.send must use session_id as the routing key
    mock_manager.send.assert_called_once_with(session_id, published_msg)
    # Sanity: it must NOT have been called with lesson_id
    first_arg = mock_manager.send.call_args[0][0]
    assert first_arg != lesson_id, "manager.send must not route to lesson_id"


# -- Test 6: lifespan wiring -- listener task start + clean cancel ------------


@pytest.mark.unit
async def test_start_lesson_ready_listener_returns_cancellable_task(mocker) -> None:
    """start_lesson_ready_listener schedules _run_lesson_subscriber as a named, cancellable task.

    Verifies the listener-factory contract that the lifespan relies on: the returned object is the
    named background asyncio.Task, the scheduled coroutine actually runs (it reaches psubscribe — so
    a broken factory that scheduled the wrong coroutine would be caught), and cancellation propagates
    CancelledError cleanly with no restart. (main.py's lifespan start/cancel is exercised end-to-end
    by the integration suite's ``running_listener``.)
    """
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    async def _hang_listen():
        # Park forever; the task is alive but idle until cancelled.
        await asyncio.Event().wait()
        yield  # pragma: no cover -- unreachable (cancelled while waiting)

    mock_pubsub = MagicMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.listen = _hang_listen

    mock_sub_conn = MagicMock()
    mock_sub_conn.pubsub.return_value = mock_pubsub
    mocker.patch("app.core.pubsub.Redis").from_url.return_value = mock_sub_conn

    from app.core.pubsub import start_lesson_ready_listener

    task = await start_lesson_ready_listener(MagicMock())
    try:
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "lesson_ready_subscriber"

        # Let the scheduled coroutine run up to its parked listen(); reaching psubscribe
        # proves _run_lesson_subscriber (not some unrelated coroutine) was scheduled.
        for _ in range(10):
            if mock_pubsub.psubscribe.await_count:
                break
            await asyncio.sleep(0)
        mock_pubsub.psubscribe.assert_awaited_once_with("lesson_ready:*")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
