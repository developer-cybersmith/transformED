"""
Integration tests for the lesson_ready Redis pub/sub bridge.

Architecture under test
-----------------------
    ARQ worker  ──publish──▶  Redis "lesson_ready:{session_id}"
                                      │
                                      ▼  (psubscribe "lesson_ready:*")
        app.core.pubsub._run_lesson_subscriber  (background asyncio.Task,
        started by app.core.pubsub.start_lesson_ready_listener during the
        FastAPI lifespan — see app.main.lifespan)
                                      │
                                      ▼
                       manager.send(session_id, message)  ──▶ WebSocket clients

These tests drive the *real* subscriber code (start_lesson_ready_listener →
_run_lesson_subscriber) and assert what reaches a mock ConnectionManager.

Redis transport
---------------
If ``fakeredis[aioredis]`` is installed, scenarios 1–4 run against a genuine
in-process Redis using real ``publish`` / ``psubscribe`` traffic.  When it is
not installed, the same scenarios run against a queue-backed fake connection
that feeds synthesized ``pmessage`` events into the real subscriber loop — so
the subscriber's branching (pmessage filter, prefix strip, JSON decode,
malformed-JSON recovery) is exercised identically in both modes.

``asyncio_mode = "auto"`` (pyproject.toml) — no @pytest.mark.asyncio needed.
Patch target note: the subscriber does ``from redis.asyncio import Redis`` at
module load, so the effective patch target is ``app.core.pubsub.Redis``.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import pathlib
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest

try:  # fakeredis[aioredis] is optional — fall back to a queue-backed fake.
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis

    HAS_FAKEREDIS = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_FAKEREDIS = False


# -- Helpers -------------------------------------------------------------------


def _make_mock_manager() -> MagicMock:
    """A ConnectionManager stub whose ``send`` is an awaitable mock."""
    manager = MagicMock()
    manager.send = AsyncMock()
    return manager


async def _wait_for(predicate, *, timeout: float = 1.0, interval: float = 0.005) -> bool:
    """Poll *predicate* until true or *timeout* elapses.

    Replaces a flat ``sleep(100ms)`` with a bounded poll: it returns as soon as
    the subscriber has dispatched, but still tolerates scheduler jitter on slow
    CI without sleeping the full budget on every run.
    """
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(interval)
        waited += interval
    return predicate()


class _QueuePubSub:
    """Minimal async pub/sub stand-in backed by an ``asyncio.Queue``.

    Mirrors the redis.asyncio pubsub surface the subscriber touches:
    ``psubscribe`` (awaited once) and ``listen`` (async iterator).  Unlike real
    Redis, the queue *buffers*, so a message enqueued before the consumer is
    ready is never dropped — keeping the no-fakeredis path deterministic.
    """

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self.psubscribe = AsyncMock()

    async def listen(self):  # noqa: ANN202 - async generator
        while True:
            yield await self._queue.get()


class _QueueConn:
    """Stand-in for the dedicated ``Redis.from_url(...)`` connection."""

    def __init__(self, queue: asyncio.Queue) -> None:
        self._pubsub = _QueuePubSub(queue)

    def pubsub(self):  # noqa: ANN201
        return self._pubsub

    async def aclose(self) -> None:  # used only on the reconnect path
        return None


@contextlib.asynccontextmanager
async def running_listener(manager: MagicMock):
    """Start the real lesson_ready listener and yield a ``publish`` callable.

    ``publish(channel, data, *, kind="pmessage")`` injects an event the way the
    ARQ worker would.  ``data`` may be ``str`` or ``bytes`` (the subscriber
    decodes bytes).  ``kind`` lets a test simulate a non-pmessage event such as
    a "subscribe"/"psubscribe" confirmation.

    On exit the background task is cancelled and awaited, mirroring the
    lifespan shutdown in app.main.
    """
    from app.core.pubsub import start_lesson_ready_listener

    # The subscriber only reads settings.redis_url, and Redis.from_url is patched
    # below — so stub get_settings to keep this test self-contained (no .env /
    # real secrets required to start the listener).
    stub_settings = SimpleNamespace(redis_url="redis://localhost:6379/0")
    settings_patch = mock.patch("app.config.get_settings", return_value=stub_settings)

    if HAS_FAKEREDIS:
        server = FakeServer()

        def _from_url(*_args, **kwargs):
            # Honour decode_responses so channel/data arrive as str, exactly as
            # production configures the dedicated connection.
            decode = kwargs.get("decode_responses", True)
            return FakeRedis(server=server, decode_responses=decode)

        publisher = FakeRedis(server=server, decode_responses=True)

        async def _publish(channel: str, data, *, kind: str = "pmessage") -> None:
            if kind != "pmessage":
                # Real subscribe/psubscribe confirmations are emitted by Redis
                # itself on (p)subscribe and are already exercised by the
                # listener start-up; there is nothing extra to publish here.
                return
            payload = data.decode() if isinstance(data, bytes) else data
            await publisher.publish(channel, payload)

        with settings_patch, mock.patch("app.core.pubsub.Redis.from_url", side_effect=_from_url):
            task = await start_lesson_ready_listener(manager)
            # Give psubscribe time to register before any publish (real pub/sub
            # drops messages with no live subscriber).
            await asyncio.sleep(0.05)
            try:
                yield _publish
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await publisher.aclose()
    else:
        queue: asyncio.Queue = asyncio.Queue()

        async def _publish(channel: str, data, *, kind: str = "pmessage") -> None:
            queue.put_nowait(
                {
                    "type": kind,
                    "pattern": "lesson_ready:*",
                    "channel": channel,
                    "data": data,
                }
            )

        def _from_url(*_args, **_kwargs):
            return _QueueConn(queue)

        with settings_patch, mock.patch("app.core.pubsub.Redis.from_url", side_effect=_from_url):
            task = await start_lesson_ready_listener(manager)
            try:
                yield _publish
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


# -- Scenario 1: end-to-end pub/sub delivery ----------------------------------


@pytest.mark.integration
async def test_end_to_end_pubsub_delivery() -> None:
    """A correctly-shaped lesson_ready message is delivered to manager.send."""
    manager = _make_mock_manager()
    session_id = "test-lesson-abc"
    message = {
        "type": "lesson_ready",
        "payload": {
            "session_id": session_id,
            "lesson_id": session_id,
            "lesson": {"slides": [], "quiz_questions": [], "audio_assets": []},
        },
    }

    async with running_listener(manager) as publish:
        await publish(f"lesson_ready:{session_id}", json.dumps(message))
        await _wait_for(lambda: manager.send.await_count >= 1)

    manager.send.assert_awaited_once_with(session_id, message)


# -- Scenario 2: message shape forwarded without mutation ---------------------


@pytest.mark.integration
async def test_message_shape_forwarded_without_mutation() -> None:
    """The subscriber forwards the published dict verbatim — no keys added or
    removed at any level."""
    manager = _make_mock_manager()
    session_id = "abc"
    message = {
        "type": "lesson_ready",
        "payload": {"lesson_id": "abc", "lesson": {"slides": []}},
    }

    async with running_listener(manager) as publish:
        await publish(f"lesson_ready:{session_id}", json.dumps(message))
        await _wait_for(lambda: manager.send.await_count >= 1)

    manager.send.assert_awaited_once()
    sent_session_id, sent_message = manager.send.await_args[0]

    assert sent_session_id == session_id
    # Exact structural equality — nothing mutated in transit.
    assert sent_message == message
    # Be explicit that no key was added or dropped at either level.
    assert set(sent_message.keys()) == {"type", "payload"}
    assert set(sent_message["payload"].keys()) == {"lesson_id", "lesson"}
    assert set(sent_message["payload"]["lesson"].keys()) == {"slides"}


# -- Scenario 3: malformed JSON does not kill the subscriber ------------------


@pytest.mark.integration
async def test_malformed_json_does_not_kill_subscriber() -> None:
    """A non-JSON payload is swallowed; a subsequent valid message still
    reaches manager.send (the listener survived the bad message)."""
    manager = _make_mock_manager()
    good_session = "good-session"
    good_message = {
        "type": "lesson_ready",
        "payload": {"session_id": good_session, "lesson_id": good_session, "lesson": {}},
    }

    async with running_listener(manager) as publish:
        # Bad message first — must not raise out of the subscriber loop.
        await publish("lesson_ready:bad", b"not-json")
        await asyncio.sleep(0.05)
        # Valid message after the crash-bait.
        await publish(f"lesson_ready:{good_session}", json.dumps(good_message))
        await _wait_for(lambda: manager.send.await_count >= 1)

    # The bad message produced no dispatch; the good one did.
    manager.send.assert_awaited_once_with(good_session, good_message)


# -- Scenario 4: non-pmessage events are ignored ------------------------------


@pytest.mark.integration
async def test_non_pmessage_events_ignored() -> None:
    """A subscribe/psubscribe confirmation (type != 'pmessage') never triggers
    a dispatch to manager.send."""
    manager = _make_mock_manager()

    async with running_listener(manager) as publish:
        # Simulate the confirmation event Redis emits on (p)subscribe.
        await publish(
            "lesson_ready:whatever", json.dumps({"type": "lesson_ready"}), kind="subscribe"
        )
        # Give the loop ample time to (not) act on it.
        await asyncio.sleep(0.1)

    manager.send.assert_not_awaited()


# -- Scenario 5: workers must not import the WebSocket manager ----------------


@pytest.mark.integration
def test_no_manager_import_in_workers() -> None:
    """Discipline guard: the worker job notifies clients via Redis pub/sub only.

    Importing ``app.core.websocket.manager`` into a worker process — or calling
    ``manager.send`` there — would couple the ARQ worker to in-process
    WebSocket state it does not own and cannot reach across processes.
    """
    job_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app"
        / "workers"
        / "jobs"
        / "content_pipeline.py"
    )
    source = job_path.read_text(encoding="utf-8")

    assert "from app.core.websocket import manager" not in source, (
        "workers must not import the WebSocket manager — notify via Redis pub/sub"
    )
    assert "manager.send" not in source, (
        "workers must not call manager.send — notify via Redis pub/sub"
    )

    # AST-level backstop: catch any import that binds the websocket manager,
    # regardless of import style/whitespace.
    tree = ast.parse(source, filename=str(job_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.core.websocket":
            imported = {alias.name for alias in node.names}
            assert "manager" not in imported, (
                "workers must not import 'manager' from app.core.websocket"
            )
