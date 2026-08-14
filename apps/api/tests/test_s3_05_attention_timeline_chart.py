"""Tests for Story 2-46 / S3-05: attention timeline chart backend fields.

Extends `get_session_report` with two new, additive, nullable SessionReport fields:
  - ces_timeline: list[{"minute": float, "ces": float}] | None
      Derived from the SAME Redis `ces_history` read `ces_history_summary` already
      performs (S3-50/D18) -- no second round trip. Chronological order (oldest
      first); `ces_history` is LPUSH'd (newest first) so the raw order is reversed.
  - intervention_events: list[{"minute": float, "type": str}] | None
      Derived from a new, bounded (.limit(20)) session_events query, using
      sessions.started_at for the same minute-offset math.

D109 (docs/DEFECT-REGISTER.md): ces_timeline can only ever cover the last
_CES_HISTORY_MAX=10 windows -- these tests assert that behavior explicitly rather
than assuming full-session coverage.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SETTINGS_KWARGS = dict(
    ces_weight_quiz=0.35,
    ces_weight_teachback=0.25,
    ces_weight_behavioral=0.20,
    ces_weight_head_pose=0.12,
    ces_weight_blink=0.08,
)

_STARTED_AT_ISO = "2026-08-12T10:00:00+00:00"
_STARTED_AT_UNIX = datetime.fromisoformat(_STARTED_AT_ISO).timestamp()

_SESSION_ROW = {
    "session_id": "ses-timeline-1",
    "user_id": "usr-1",
    "lesson_id": "les-1",
    "ces_final": 65.0,
    "started_at": _STARTED_AT_ISO,
    "ended_at": "2026-08-12T10:30:00+00:00",
}


def _redis_with_ces_history(entries: list[dict]) -> AsyncMock:
    """Redis mock returning JSON-encoded {"v","t"} ces_history entries.

    `entries` given oldest-first for readability; stored LPUSH-style (newest-first),
    matching real Redis semantics -- the service must reverse them back.
    """
    redis = AsyncMock()
    encoded = [json.dumps(e) for e in reversed(entries)]

    async def fake_lrange(key: str, start: int, stop: int) -> list[str]:
        if "ces_history" in key:
            return encoded
        return []

    redis.lrange = fake_lrange
    return redis


def _supabase_with_intervention_rows(
    intervention_rows: list[dict],
    *,
    raise_on_intervention_query: bool = False,
    session_row: dict | None = None,
) -> MagicMock:
    """Sequential .select() call mock: sessions, lessons(tier), quiz, teachback,
    session_events count, session_events raw rows (this story's new query).
    """
    supabase = MagicMock()
    call_count = 0
    captured: dict[str, MagicMock] = {}
    _session_row = session_row if session_row is not None else _SESSION_ROW

    def _select_side_effect(*args, **kwargs):
        nonlocal call_count
        mock = MagicMock()
        mock.eq.return_value = mock
        mock.maybe_single.return_value = mock
        mock.order.return_value = mock
        mock.limit.return_value = mock
        call_count += 1
        if call_count == 1:
            mock.execute.return_value = MagicMock(data=_session_row)
        elif call_count == 2:
            mock.execute.return_value = MagicMock(data=None)  # no tier row -> T2 default
        elif call_count == 3:
            mock.execute.return_value = MagicMock(data=[], count=0)  # quiz_attempts
        elif call_count == 4:
            mock.execute.return_value = MagicMock(data=[], count=0)  # teachback_attempts
        elif call_count == 5:
            mock.execute.return_value = MagicMock(data=[], count=len(intervention_rows))
        elif call_count == 6:
            # new raw-rows query -- captured so tests can assert on .order()/.limit()
            # call args, and so it can be made to raise on demand.
            if raise_on_intervention_query:
                mock.execute.side_effect = ConnectionError("supabase unavailable")
            else:
                mock.execute.return_value = MagicMock(data=intervention_rows)
            captured["intervention_query"] = mock
        else:
            mock.execute.return_value = MagicMock(data=None)  # learner_dna -- none
        return mock

    supabase.table.return_value.select.side_effect = _select_side_effect
    supabase._captured = captured
    return supabase


def _patched(
    *,
    redis,
    intervention_rows,
    raise_on_intervention_query: bool = False,
    session_row: dict | None = None,
):
    supabase = _supabase_with_intervention_rows(
        intervention_rows,
        raise_on_intervention_query=raise_on_intervention_query,
        session_row=session_row,
    )
    return (
        supabase,
        redis,
        (
            patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
            patch("app.core.db.single_row", return_value=session_row or _SESSION_ROW),
            patch("app.core.db.rows", side_effect=lambda resp: resp.data or []),
            patch("app.config.get_settings", return_value=MagicMock(**_SETTINGS_KWARGS)),
        ),
    )


# â”€â”€ ces_timeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_timeline_computed_chronologically_from_same_redis_read():
    """ces_timeline reflects real minute offsets from started_at, oldest first,
    reversed from ces_history's LPUSH (newest-first) storage order."""
    from app.modules.assessment.service import get_session_report

    entries_oldest_first = [
        {"v": 60.0, "t": _STARTED_AT_UNIX},
        {"v": 70.0, "t": _STARTED_AT_UNIX + 60},
        {"v": 80.0, "t": _STARTED_AT_UNIX + 120},
    ]
    redis = _redis_with_ces_history(entries_oldest_first)
    supabase, redis, patches = _patched(redis=redis, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=redis,
        )

    assert result.ces_timeline == [
        {"minute": 0.0, "ces": 60.0},
        {"minute": 1.0, "ces": 70.0},
        {"minute": 2.0, "ces": 80.0},
    ]
    # AC-2 non-regression: ces_history_summary is untouched by this extension.
    assert result.ces_history_summary == {
        "mean": 70.0, "min": 60.0, "max": 80.0, "window_count": 3,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_timeline_excludes_legacy_bare_float_entries_but_summary_still_counts_them():
    """Legacy bare-float ces_history entries (no timestamp) cannot be time-placed,
    so they're excluded from ces_timeline -- but ces_history_summary (AC-2) must
    still average them exactly as before this story."""
    from app.modules.assessment.service import get_session_report

    redis = AsyncMock()
    # newest-first storage: one real entry, one legacy bare-float entry
    encoded = [
        json.dumps({"v": 80.0, "t": _STARTED_AT_UNIX + 60}),
        "60.0",  # legacy bare-float
    ]

    async def fake_lrange(key, start, stop):
        return encoded if "ces_history" in key else []

    redis.lrange = fake_lrange
    supabase, redis, patches = _patched(redis=redis, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=redis,
        )

    assert result.ces_timeline == [{"minute": 1.0, "ces": 80.0}]
    assert result.ces_history_summary["window_count"] == 2
    assert result.ces_history_summary["mean"] == pytest.approx(70.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_rejects_non_finite_values_instead_of_producing_invalid_json():
    """Review finding: float("nan")/float("inf") don't raise, so an unguarded parse would
    let a stray non-finite value into the response -- FastAPI's default JSONResponse would
    then serialize a literal NaN/Infinity token, which is invalid JSON and breaks the
    frontend's JSON.parse for the WHOLE report, not just this field. A non-finite entry
    must be skipped, exactly like a corrupt/unparseable one."""
    from app.modules.assessment.service import get_session_report

    entries_oldest_first = [
        {"v": 60.0, "t": _STARTED_AT_UNIX},
        {"v": float("nan"), "t": _STARTED_AT_UNIX + 60},
        {"v": float("inf"), "t": _STARTED_AT_UNIX + 120},
        {"v": 80.0, "t": _STARTED_AT_UNIX + 180},
    ]
    redis = AsyncMock()
    encoded = [json.dumps(e) for e in reversed(entries_oldest_first)]

    async def fake_lrange(key, start, stop):
        return encoded if "ces_history" in key else []

    redis.lrange = fake_lrange
    supabase, redis, patches = _patched(redis=redis, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=redis,
        )

    assert result.ces_timeline == [
        {"minute": 0.0, "ces": 60.0},
        {"minute": 3.0, "ces": 80.0},
    ]
    assert result.ces_history_summary["window_count"] == 2
    assert result.ces_history_summary["mean"] == pytest.approx(70.0)
    for point in result.ces_timeline:
        assert math.isfinite(point["ces"])
        assert math.isfinite(point["minute"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_timeline_is_none_when_redis_unavailable():
    from app.modules.assessment.service import get_session_report

    supabase, _, patches = _patched(redis=None, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    assert result.ces_timeline is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_timeline_is_none_when_history_empty():
    from app.modules.assessment.service import get_session_report

    redis = _redis_with_ces_history([])
    supabase, redis, patches = _patched(redis=redis, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=redis,
        )

    assert result.ces_timeline is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_timeline_capped_at_ten_windows_d109():
    """D109: ces_timeline can never exceed _CES_HISTORY_MAX=10 entries -- this is the
    real, documented recency-window limitation, not a bug to hide."""
    from app.modules.assessment.service import get_session_report

    entries = [{"v": 50.0 + i, "t": _STARTED_AT_UNIX + i * 60} for i in range(10)]
    redis = _redis_with_ces_history(entries)
    supabase, redis, patches = _patched(redis=redis, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=redis,
        )

    assert len(result.ces_timeline) == 10


# â”€â”€ intervention_events â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_computed_with_minute_and_type():
    """Rows are fed newest-first, matching what a real `.order("created_at", desc=True)`
    query returns -- the service must reverse them back to chronological order."""
    from app.modules.assessment.service import get_session_report

    rows = [
        {
            "created_at": "2026-08-12T10:07:30+00:00",
            "payload": {"intervention_type": "fatigue", "ces_at_trigger": 28.0},
        },
        {
            "created_at": "2026-08-12T10:03:00+00:00",
            "payload": {"intervention_type": "distraction", "ces_at_trigger": 32.1},
        },
    ]
    supabase, redis, patches = _patched(redis=None, intervention_rows=rows)

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    assert result.intervention_events == [
        {"minute": 3.0, "type": "distraction"},
        {"minute": 7.5, "type": "fatigue"},
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_query_orders_by_created_at_desc_before_limiting():
    """Review finding: `.limit(20)` alone gives PostgREST no ordering guarantee. The
    query must explicitly order by created_at DESC so the cap keeps the true most-recent
    20 rows, not an arbitrary subset, once a session exceeds the natural bound (D64)."""
    from app.modules.assessment.service import get_session_report

    rows = [{"created_at": "2026-08-12T10:03:00+00:00", "payload": {"intervention_type": "distraction"}}]
    supabase, redis, patches = _patched(redis=None, intervention_rows=rows)

    with patches[0], patches[1], patches[2], patches[3]:
        await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    intervention_query = supabase._captured["intervention_query"]
    intervention_query.order.assert_called_once_with("created_at", desc=True)
    intervention_query.limit.assert_called_once_with(20)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_is_none_when_started_at_missing():
    """AC-1: None (not a crash, not an empty list masquerading as 'no data') when
    `started_at` can't be resolved -- minute-offset math has nothing to anchor to."""
    from app.modules.assessment.service import get_session_report

    session_row_no_started_at = {**_SESSION_ROW, "started_at": None}
    rows = [{"created_at": "2026-08-12T10:03:00+00:00", "payload": {"intervention_type": "distraction"}}]
    supabase, redis, patches = _patched(
        redis=None, intervention_rows=rows, session_row=session_row_no_started_at
    )

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    assert result.intervention_events is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_degrades_to_none_when_query_raises():
    """Review finding: a Supabase failure on this new, optional-data query must degrade
    gracefully (None), not propagate an unhandled exception that 500s the whole report --
    matching the Redis block's existing degrade-on-failure pattern."""
    from app.modules.assessment.service import get_session_report

    supabase, redis, patches = _patched(
        redis=None, intervention_rows=[], raise_on_intervention_query=True
    )

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    assert result.intervention_events is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_never_includes_ces_at_trigger():
    """AC-5: the raw CES value at trigger time must never reach the frontend --
    enforced at the contract level (only minute/type are ever extracted)."""
    from app.modules.assessment.service import get_session_report

    rows = [
        {
            "created_at": "2026-08-12T10:03:00+00:00",
            "payload": {"intervention_type": "distraction", "ces_at_trigger": 32.1},
        },
    ]
    supabase, redis, patches = _patched(redis=None, intervention_rows=rows)

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    for event in result.intervention_events:
        assert set(event.keys()) == {"minute", "type"}
        assert "ces_at_trigger" not in event
        assert 32.1 not in event.values()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_is_none_when_no_interventions():
    from app.modules.assessment.service import get_session_report

    supabase, redis, patches = _patched(redis=None, intervention_rows=[])

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    assert result.intervention_events is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_events_skips_row_with_missing_created_at():
    """A malformed row (no created_at) is skipped, not a crash -- degrade, don't 500."""
    from app.modules.assessment.service import get_session_report

    rows = [
        {"created_at": None, "payload": {"intervention_type": "distraction"}},
        {
            "created_at": "2026-08-12T10:05:00+00:00",
            "payload": {"intervention_type": "confusion"},
        },
    ]
    supabase, redis, patches = _patched(redis=None, intervention_rows=rows)

    with patches[0], patches[1], patches[2], patches[3]:
        result = await get_session_report(
            session_id="ses-timeline-1", user_id="usr-1", supabase=supabase, redis=None,
        )

    assert result.intervention_events == [{"minute": 5.0, "type": "confusion"}]


# â”€â”€ SessionReport model fields â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.mark.unit
def test_ces_timeline_and_intervention_events_fields_on_session_report_model():
    from app.modules.assessment.router import SessionReport

    fields = SessionReport.model_fields
    assert "ces_timeline" in fields
    assert fields["ces_timeline"].default is None
    assert "intervention_events" in fields
    assert fields["intervention_events"].default is None
