"""
Unit tests for Story 2-52 (S4-12): the two trigger points that enqueue
send_notification_email_job.

1. content_pipeline_job (apps/api/app/workers/jobs/content_pipeline.py) —
   runs INSIDE the ARQ worker process, so it enqueues via ctx["redis"]
   (arq's Worker auto-populates this with the same ArqRedis pool used to
   fetch jobs — confirmed at arq/worker.py:361, `self.ctx['redis'] = self.pool`).
2. session_end_node's _finalize_session
   (apps/api/app/modules/tutor/state_machine/graph.py) — runs in the
   FastAPI/WebSocket process, a genuinely different process than the ARQ
   worker, so it MUST enqueue via app.core.arq_pool.get_arq_pool() rather
   than any in-process function call.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

LESSON_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
USER_ID = "u1"
SESSION_ID = "sess-1"


# ── 1. content_pipeline_job → send_notification_email_job("lesson_ready") ────


async def test_content_pipeline_job_enqueues_lesson_ready_notification() -> None:
    from app.workers.jobs import content_pipeline as cp

    row: dict[str, Any] = {
        "lesson_id": LESSON_ID,
        "source_pdf_path": "p.pdf",
        "user_id": USER_ID,
        "book_id": "b1",
        "tier": "T2",
    }
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.maybe_single.return_value.execute.return_value.data = row
    chain.single.return_value.execute.return_value.data = row
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [row]

    arq_redis = AsyncMock()
    ctx = {"job_id": "j", "job_try": 1, "redis": arq_redis}

    with (
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(return_value={"lesson_id": LESSON_ID, "segments": []}),
        ),
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock(return_value=None)),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
    ):
        try:
            await cp.content_pipeline_job(ctx, LESSON_ID)
        except Exception:  # noqa: BLE001, S110 — only the enqueue call matters here
            pass

    arq_redis.enqueue_job.assert_awaited_once_with(
        "send_notification_email_job",
        USER_ID,
        "lesson_ready",
        LESSON_ID,
        _job_id=f"notify:lesson_ready:{LESSON_ID}",
    )


async def test_content_pipeline_job_does_not_crash_when_enqueue_fails() -> None:
    """A failure to enqueue the notification must not fail the pipeline job
    itself, which has already fully succeeded by this point."""
    from app.workers.jobs import content_pipeline as cp

    row: dict[str, Any] = {
        "lesson_id": LESSON_ID,
        "source_pdf_path": "p.pdf",
        "user_id": USER_ID,
        "book_id": "b1",
        "tier": "T2",
    }
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.maybe_single.return_value.execute.return_value.data = row
    chain.single.return_value.execute.return_value.data = row
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [row]

    arq_redis = AsyncMock()
    arq_redis.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))
    ctx = {"job_id": "j", "job_try": 1, "redis": arq_redis}

    with (
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(return_value={"lesson_id": LESSON_ID, "segments": []}),
        ),
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock(return_value=None)),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
    ):
        result = await cp.content_pipeline_job(ctx, LESSON_ID)

    assert result["lesson_id"] == LESSON_ID  # the pipeline job itself still succeeded


# ── 2. _finalize_session → send_notification_email_job("session_report") ────


async def test_finalize_session_enqueues_session_report_notification_via_arq_pool() -> None:
    from app.modules.tutor.state_machine.graph import _finalize_session

    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])

    supabase = MagicMock()
    supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"session_id": SESSION_ID, "user_id": USER_ID}])
    )

    arq_pool = AsyncMock()

    with patch("app.core.arq_pool.get_arq_pool", return_value=arq_pool):
        await _finalize_session(SESSION_ID, redis=redis, supabase=supabase)

    arq_pool.enqueue_job.assert_awaited_once_with(
        "send_notification_email_job",
        USER_ID,
        "session_report",
        SESSION_ID,
        _job_id=f"notify:session_report:{SESSION_ID}",
    )


async def test_finalize_session_does_not_raise_when_arq_pool_unavailable() -> None:
    """_finalize_session is fire-and-forget (asyncio.create_task) — an ARQ
    pool failure here must not propagate and must not prevent the DB write
    (already committed) from being treated as successful."""
    from app.modules.tutor.state_machine.graph import _finalize_session

    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])

    supabase = MagicMock()
    supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"session_id": SESSION_ID, "user_id": USER_ID}])
    )

    with patch("app.core.arq_pool.get_arq_pool", side_effect=RuntimeError("not initialised")):
        await _finalize_session(SESSION_ID, redis=redis, supabase=supabase)  # must not raise


async def test_finalize_session_skips_enqueue_when_update_response_has_no_user_id() -> None:
    from app.modules.tutor.state_machine.graph import _finalize_session

    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])

    supabase = MagicMock()
    supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])
    )

    arq_pool = AsyncMock()
    with patch("app.core.arq_pool.get_arq_pool", return_value=arq_pool):
        await _finalize_session(SESSION_ID, redis=redis, supabase=supabase)

    arq_pool.enqueue_job.assert_not_awaited()
