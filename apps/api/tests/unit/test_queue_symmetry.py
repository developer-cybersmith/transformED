"""
AC-1 (Story 2-0) — queue-name symmetry between enqueue and consume sides.

The 2026-07-08 live E2E proved 0% of uploads executed because the API enqueued
to arq's default queue while the worker consumed "hie:pipeline". These tests
pin both sides to the single constant in app.core.queues so the names can
never silently drift again.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.queues import PIPELINE_QUEUE
from app.workers.main import WorkerSettings

try:  # fakeredis is optional in this repo (see test_lesson_ready_integration)
    from fakeredis.aioredis import FakeRedis

    HAS_FAKEREDIS = True
except ImportError:  # pragma: no cover - depends on environment
    HAS_FAKEREDIS = False


def test_pipeline_queue_constant_value() -> None:
    """The constant itself is the agreed wire-level queue name."""
    assert PIPELINE_QUEUE == "hie:pipeline"


def test_worker_consumes_pipeline_queue() -> None:
    """Consume side: WorkerSettings.queue_name IS the shared constant."""
    assert WorkerSettings.queue_name == PIPELINE_QUEUE


def test_enqueue_pool_uses_pipeline_queue() -> None:
    """Enqueue side: app.main.lifespan builds its ARQ pool with
    default_queue_name=PIPELINE_QUEUE.

    Source-level assertion rather than a live round-trip: create_pool()
    requires a reachable Redis server (fakeredis cannot back arq's
    ArqRedis pool creation reliably), and unit CI has no Redis. Asserting
    the lifespan source passes the shared constant — combined with
    test_worker_consumes_pipeline_queue above — proves both sides resolve
    to the same name, which is the symmetry AC-1 requires.

    Read as file text (not inspect.getsource on an imported app.main):
    importing app.main pulls every module router, so an unrelated import
    error elsewhere would mask this AC-1 regression signal.
    """
    main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
    source = main_py.read_text(encoding="utf-8")

    lifespan_src = source.split("async def lifespan", 1)[1]
    lifespan_src = lifespan_src.split("\ndef ", 1)[0]  # up to next top-level def

    assert "default_queue_name=PIPELINE_QUEUE" in lifespan_src, (
        "app.main.lifespan must pass default_queue_name=PIPELINE_QUEUE "
        "to arq.create_pool — jobs enqueued via app.state.arq_redis must "
        "land on the queue the worker consumes"
    )
    # The constant must come from the single source of truth, not a local copy.
    assert "from app.core.queues import PIPELINE_QUEUE" in lifespan_src


def test_worker_source_references_pipeline_queue() -> None:
    """Consume side, source-level: WorkerSettings.queue_name must be assigned
    the shared constant in the source text — mirror of the enqueue-side grep
    above. A literal like queue_name = "hie:pipeline" would still satisfy the
    runtime equality test, but drifts silently the moment either side edits
    the string; this pins the *reference*, not just today's value.
    """
    worker_py = Path(__file__).resolve().parents[2] / "app" / "workers" / "main.py"
    source = worker_py.read_text(encoding="utf-8")

    assert "queue_name: str = PIPELINE_QUEUE" in source, (
        "WorkerSettings.queue_name must reference PIPELINE_QUEUE, "
        "not duplicate the queue-name literal"
    )
    # The constant must come from the single source of truth, not a local copy.
    assert "from app.core.queues import PIPELINE_QUEUE" in source


def test_fakeredis_available_in_ci() -> None:
    """The round-trip proof below must never silently skip in CI — if the CI
    env var is set, fakeredis has to be installed."""
    if os.environ.get("CI"):
        assert HAS_FAKEREDIS, (
            "fakeredis is not importable in CI — the AC-1 queue round-trip "
            "test would silently skip; add fakeredis to the test dependencies"
        )


@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_enqueue_roundtrip_lands_on_worker_queue() -> None:
    """Full round-trip proof against an in-process Redis: a job enqueued
    through an ArqRedis pool configured exactly like app.main's
    (default_queue_name=PIPELINE_QUEUE) is visible on the key the worker
    polls (WorkerSettings.queue_name)."""
    from arq.connections import ArqRedis

    fake = FakeRedis()
    pool = ArqRedis(
        connection_pool=fake.connection_pool,
        default_queue_name=PIPELINE_QUEUE,
    )
    try:
        job = await pool.enqueue_job("content_pipeline_job", "lesson-roundtrip")
        assert job is not None

        # The worker polls the sorted set named WorkerSettings.queue_name.
        queued = await fake.zcard(WorkerSettings.queue_name)
        assert queued == 1
    finally:
        await fake.aclose()
