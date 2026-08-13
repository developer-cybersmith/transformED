"""
Unit tests for Story 3-48 (D53): reap_stale_generating_lessons.

D53: nothing but content_pipeline_job itself ever transitions a lessons row
out of status='generating'. router.py's _generating_cutoff_iso() already
stops a stale row from blocking a new generation or a concurrency slot
(query-level workaround) -- but the row itself never actually became
'failed'. This reaper closes that gap.

Covers:
- a stale row gets reaped via the SAME _update_lesson_status helper every
  other failure path uses (so cost persistence, lessons.status mirroring,
  etc. are inherited for free, not reimplemented)
- no stale rows -> no-op, zero calls
- the reap query is bounded (.limit()) and filters on status + the real
  staleness cutoff (not a locally-invented one)
- one row's reap failure does not stop the batch
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_supabase_with_stale_rows(rows: list[dict[str, Any]]) -> MagicMock:
    supabase = MagicMock()
    select_chain = supabase.table.return_value.select.return_value
    limit_chain = select_chain.eq.return_value.lt.return_value.limit.return_value
    limit_chain.execute.return_value = MagicMock(data=rows)
    return supabase


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reaps_a_stale_generating_lesson() -> None:
    """A stale row returned by the query is reaped via _update_lesson_status
    with status='failed' and a D53-attributed error message."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_stale_rows(
        [{"lesson_id": "stale-1", "created_at": "2020-01-01T00:00:00+00:00"}]
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
    assert "D53" in call.kwargs["error"]
    assert result == {"reaped_count": 1, "reaped_lesson_ids": ["stale-1"]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_stale_rows_is_a_pure_noop() -> None:
    """Zero rows returned -> zero _update_lesson_status calls, empty result."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_stale_rows([])
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
async def test_reap_query_filters_on_status_and_real_staleness_cutoff() -> None:
    """The query must filter status='generating' and use
    router._generating_cutoff_iso()'s own value for the staleness bound --
    not a locally re-derived one, so the reaper and the query-level
    idempotency/concurrency workaround can never silently drift apart on
    what counts as stale."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_stale_rows([])

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.content.router._generating_cutoff_iso",
            return_value="SENTINEL_CUTOFF",
        ),
    ):
        await reap_stale_generating_lessons({})

    table_mock = supabase.table.return_value
    table_mock.select.assert_called_once_with("lesson_id, created_at")
    table_mock.select.return_value.eq.assert_called_once_with("status", "generating")
    table_mock.select.return_value.eq.return_value.lt.assert_called_once_with(
        "created_at", "SENTINEL_CUTOFF"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reap_query_is_bounded_with_limit() -> None:
    """AC: the reap query must carry .limit() -- an unbounded scan across
    every stale lesson repo-wide would violate this codebase's bounded-query
    rule (tests/unit/test_unbounded_queries.py's own source scan)."""
    from app.workers.jobs.reap_stale_lessons import _REAP_BATCH_LIMIT, reap_stale_generating_lessons

    supabase = _mock_supabase_with_stale_rows([])

    with patch("app.core.db.get_supabase", return_value=supabase):
        await reap_stale_generating_lessons({})

    limit_chain = supabase.table.return_value.select.return_value.eq.return_value.lt.return_value
    limit_chain.limit.assert_called_once_with(_REAP_BATCH_LIMIT)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_bad_row_does_not_stop_the_batch() -> None:
    """A raising _update_lesson_status for row 1 must not prevent row 2 from
    being reaped -- one bad row must not break the whole batch."""
    from app.workers.jobs.reap_stale_lessons import reap_stale_generating_lessons

    supabase = _mock_supabase_with_stale_rows(
        [
            {"lesson_id": "stale-bad", "created_at": "2020-01-01T00:00:00+00:00"},
            {"lesson_id": "stale-good", "created_at": "2020-01-01T00:00:00+00:00"},
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
