"""
Unit tests for Story 3-48/3-54 (D53/D91): reap_stale_generating_lessons.

D53: nothing but content_pipeline_job itself ever transitions a lessons row
out of status='generating'. D91: the original reaper used lessons.created_at
(row-insert time) as its only staleness signal, conflating queue-wait time
with real run time -- a job whose ARQ retry was delayed before even being
dequeued could be falsely reaped while still genuinely alive. Now uses
lesson_jobs.started_at (the real run-start time) when available, falling
back to a more generous queue-wait-inclusive bound via created_at only for
jobs that never started running at all.

Covers:
- a job whose started_at is past the real run-time cutoff IS reaped
- a job whose started_at is recent (NOT past the run-time cutoff), even
  though it was created long ago, is NOT reaped -- the exact false-positive
  D91 exists to prevent, reproduced directly
- a job that never started (started_at null) past the generous queue-wait
  cutoff IS reaped
- no candidates -> no-op
- the query targets lesson_jobs (not lessons), filters status IN
  (pending, running), and is bounded (.limit())
- one row's reap failure does not stop the batch
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_supabase_with_candidates(rows: list[dict[str, Any]]) -> MagicMock:
    supabase = MagicMock()
    select_chain = supabase.table.return_value.select.return_value
    limit_chain = select_chain.in_.return_value.lt.return_value.limit.return_value
    limit_chain.execute.return_value = MagicMock(data=rows)
    return supabase


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reaps_a_job_whose_real_start_time_is_past_the_run_cutoff() -> None:
    """A job with started_at set, older than arq_job_timeout_s ago, is reaped
    via _update_lesson_status with a D53/D91-attributed error."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_candidates(
        [
            {
                "lesson_id": "stale-1",
                "started_at": "2020-01-01T00:00:00+00:00",
                "created_at": "2020-01-01T00:00:00+00:00",
            }
        ]
    )
    mock_update = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.workers.jobs.content_pipeline._update_lesson_status",
            new=mock_update,
        ),
    ):
        result = await reap_stale_generating_lessons({})

    mock_update.assert_awaited_once()
    call = mock_update.await_args
    assert call.args[0] is supabase
    assert call.args[1] == "stale-1"
    assert call.args[2] == "failed"
    assert "D53" in call.kwargs["error"] and "D91" in call.kwargs["error"]
    assert result == {"reaped_count": 1, "reaped_lesson_ids": ["stale-1"]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_does_not_reap_a_job_with_a_recent_real_start_despite_old_created_at() -> None:
    """D91's actual fix, reproduced directly: a job created long ago (so it
    passes the query's generous queue_cutoff filter and is fetched as a
    candidate) but whose started_at is RECENT -- it only just began actually
    running, e.g. after sitting queued for a long time -- must NOT be reaped.
    This is the exact false-positive observed live: the OLD created_at-only
    logic would have reaped this row; the new started_at-aware logic must not."""
    from datetime import UTC, datetime, timedelta

    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    recent_start = (datetime.now(tz=UTC) - timedelta(seconds=5)).isoformat()
    long_ago_created = "2020-01-01T00:00:00+00:00"

    supabase = _mock_supabase_with_candidates(
        [
            {
                "lesson_id": "actually-alive",
                "started_at": recent_start,
                "created_at": long_ago_created,
            }
        ]
    )
    mock_update = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.workers.jobs.content_pipeline._update_lesson_status",
            new=mock_update,
        ),
    ):
        result = await reap_stale_generating_lessons({})

    mock_update.assert_not_awaited()
    assert result == {"reaped_count": 0, "reaped_lesson_ids": []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reaps_a_never_started_job_past_the_generous_queue_cutoff() -> None:
    """A job with started_at still null (never reached content_pipeline_job's
    own 'running' write) is reaped once created_at is older than the
    generous queue-wait cutoff -- the query itself already guarantees this
    for every candidate it returns, so a null started_at alone is sufficient
    to reap."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_candidates(
        [
            {
                "lesson_id": "never-started",
                "started_at": None,
                "created_at": "2020-01-01T00:00:00+00:00",
            }
        ]
    )
    mock_update = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.workers.jobs.content_pipeline._update_lesson_status",
            new=mock_update,
        ),
    ):
        result = await reap_stale_generating_lessons({})

    mock_update.assert_awaited_once()
    assert result == {"reaped_count": 1, "reaped_lesson_ids": ["never-started"]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_candidates_is_a_pure_noop() -> None:
    """Zero rows returned by the query -> zero _update_lesson_status calls."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_candidates([])
    mock_update = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.workers.jobs.content_pipeline._update_lesson_status",
            new=mock_update,
        ),
    ):
        result = await reap_stale_generating_lessons({})

    mock_update.assert_not_awaited()
    assert result == {"reaped_count": 0, "reaped_lesson_ids": []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reap_query_targets_lesson_jobs_status_and_is_bounded() -> None:
    """The query must run against lesson_jobs (not lessons), filter
    status IN ('pending','running') via .in_(), and carry .limit()."""
    from app.workers.jobs.reap_stale_lessons import _REAP_BATCH_LIMIT, reap_stale_generating_lessons

    supabase = _mock_supabase_with_candidates([])

    with patch("app.core.db.get_supabase", return_value=supabase):
        await reap_stale_generating_lessons({})

    supabase.table.assert_called_once_with("lesson_jobs")
    select_chain = supabase.table.return_value.select
    select_chain.assert_called_once_with("lesson_id, started_at, created_at")
    select_chain.return_value.in_.assert_called_once_with("status", ["pending", "running"])
    limit_chain = select_chain.return_value.in_.return_value.lt.return_value
    limit_chain.limit.assert_called_once_with(_REAP_BATCH_LIMIT)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_bad_row_does_not_stop_the_batch() -> None:
    """A raising _update_lesson_status for row 1 must not prevent row 2 from
    being reaped -- one bad row must not break the whole batch."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_candidates(
        [
            {
                "lesson_id": "stale-bad",
                "started_at": "2020-01-01T00:00:00+00:00",
                "created_at": "2020-01-01T00:00:00+00:00",
            },
            {
                "lesson_id": "stale-good",
                "started_at": "2020-01-01T00:00:00+00:00",
                "created_at": "2020-01-01T00:00:00+00:00",
            },
        ]
    )
    mock_update = AsyncMock(side_effect=[RuntimeError("db write failed"), None])

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.workers.jobs.content_pipeline._update_lesson_status",
            new=mock_update,
        ),
    ):
        result = await reap_stale_generating_lessons({})

    assert mock_update.await_count == 2
    assert result == {"reaped_count": 1, "reaped_lesson_ids": ["stale-good"]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_full_batch_of_concurrently_stale_jobs_is_all_reaped_in_one_pass() -> None:
    """Story 5-2 AC-9: under real concurrent load, many lessons can go stale
    at once (S4-1 run #10 measured 41/50 lessons still generating at once) --
    every existing test here uses 1-2 candidate rows, never exercising the
    `_REAP_BATCH_LIMIT` boundary itself. Simulates exactly `_REAP_BATCH_LIMIT`
    (100) distinct stale rows in a single query result (what the DB's own
    `.limit()` would actually hand back if far more than 100 were stale at
    once) -- every one of the 100 must be reaped in this single pass, none
    dropped, none silently truncated short of the batch."""
    from app.workers.jobs.reap_stale_lessons import _REAP_BATCH_LIMIT, reap_stale_generating_lessons

    candidates = [
        {
            "lesson_id": f"stale-{i}",
            "started_at": "2020-01-01T00:00:00+00:00",
            "created_at": "2020-01-01T00:00:00+00:00",
        }
        for i in range(_REAP_BATCH_LIMIT)
    ]
    supabase = _mock_supabase_with_candidates(candidates)
    mock_update = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch("app.workers.jobs.content_pipeline._update_lesson_status", new=mock_update),
    ):
        result = await reap_stale_generating_lessons({})

    assert mock_update.await_count == _REAP_BATCH_LIMIT
    assert result["reaped_count"] == _REAP_BATCH_LIMIT
    assert len(result["reaped_lesson_ids"]) == _REAP_BATCH_LIMIT
    assert len(set(result["reaped_lesson_ids"])) == _REAP_BATCH_LIMIT, (
        "no lesson_id was duplicated or dropped across the full batch"
    )
