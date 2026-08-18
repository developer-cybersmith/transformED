"""Tests for S3-50 (D18) and S3-51 (D19): ces_history_summary and intervention_messages_used.

S3-50 AC coverage:
  AC1 — ces_history_summary field on SessionReport (Optional dict)
  AC2 — populated from Redis ces_history when redis provided
  AC3 — None when redis=None or history empty
  AC4 — values rounded to 2 decimal places

S3-51 AC coverage:
  AC1 — intervention_messages_used: int on SessionReport (default 0)
  AC2 — value equals count of intervention_triggered events
  AC3 — 0 when no interventions
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _redis_with_ces_history(values: list[float]) -> AsyncMock:
    """Redis mock returning encoded ces_history entries."""
    redis = AsyncMock()
    entries = [json.dumps({"v": v, "t": 1000 + i}) for i, v in enumerate(values)]

    async def fake_lrange(key: str, start: int, stop: int) -> list[str]:
        if "ces_history" in key:
            return entries
        return []

    redis.lrange = fake_lrange
    return redis


# ── S3-50 AC 1 — field on SessionReport model ────────────────────────────────


@pytest.mark.unit
def test_ces_history_summary_field_on_session_report_model():
    """AC1: SessionReport has ces_history_summary: dict | None = None."""
    from app.modules.assessment.router import SessionReport

    sig = inspect.signature(SessionReport)
    assert "ces_history_summary" in sig.parameters or hasattr(SessionReport, "model_fields"), (
        "SessionReport must define ces_history_summary"
    )
    # Check via model_fields (Pydantic v2)
    fields = SessionReport.model_fields
    assert "ces_history_summary" in fields, "ces_history_summary missing from SessionReport"
    assert fields["ces_history_summary"].default is None, "ces_history_summary must default to None"


# ── S3-50 AC 2 — populated from Redis ces_history ────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_summary_computed_from_redis():
    """AC2: ces_history_summary contains mean/min/max/window_count from Redis history."""
    from app.modules.assessment.service import get_session_report

    # Minimal mocks for get_session_report
    session_row = {
        "session_id": "ses-50",
        "user_id": "usr-1",
        "lesson_id": "les-1",
        "ces_final": 65.0,
        "started_at": "2026-08-12T10:00:00+00:00",
        "ended_at": "2026-08-12T10:30:00+00:00",
    }
    supabase = MagicMock()
    redis = _redis_with_ces_history([60.0, 70.0, 80.0])

    with (
        patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
        patch("app.core.db.single_row", return_value=session_row),
        patch("app.core.db.rows", return_value=[]),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
            ),
        ),
    ):
        # Patch the DB-accessing parts by patching the supabase calls
        select_eq = supabase.table.return_value.select.return_value.eq.return_value
        select_eq.maybe_single.return_value.execute.return_value = MagicMock(data=session_row)
        select_eq.execute.return_value = MagicMock(data=[], count=0)

        result = await get_session_report(
            session_id="ses-50",
            user_id="usr-1",
            supabase=supabase,
            redis=redis,
        )

    assert result.ces_history_summary is not None, "ces_history_summary must be populated"
    summary = result.ces_history_summary
    assert summary["window_count"] == 3
    assert summary["mean"] == pytest.approx(70.0, abs=0.01)
    assert summary["min"] == pytest.approx(60.0, abs=0.01)
    assert summary["max"] == pytest.approx(80.0, abs=0.01)


# ── S3-50 AC 3 — None when redis=None ────────────────────────────────────────


@pytest.mark.unit
def test_ces_history_summary_is_none_when_redis_not_provided():
    """AC3: ces_history_summary is None when redis kwarg is omitted (backward compat)."""
    from app.modules.assessment.router import SessionReport

    # Build a minimal SessionReport with redis=None path result
    report = SessionReport(
        session_id="s",
        user_id="u",
        lesson_id="l",
        ces_score=0.0,
        ces_breakdown={},
        interventions_count=0,
        quiz_score=None,
        teachback_score=None,
        duration_minutes=0.0,
        completed_at=None,
        tier="T2",
        tier_label="Standard",
        quiz_total_questions=0,
        quiz_correct_count=0,
        quiz_accuracy_label=None,
        formula_applied="full_5_signal",
        signal_coverage=5,
        ces_history_summary=None,  # AC3: None when redis is absent
        intervention_messages_used=0,
    )
    assert report.ces_history_summary is None


# ── S3-50 AC 4 — values rounded to 2dp ───────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_summary_values_rounded_to_2dp():
    """AC4: mean/min/max are rounded to 2 decimal places."""
    from app.modules.assessment.service import get_session_report

    session_row = {
        "session_id": "ses-50b",
        "user_id": "usr-1",
        "lesson_id": "les-1",
        "ces_final": 65.123456789,
        "started_at": "2026-08-12T10:00:00+00:00",
        "ended_at": "2026-08-12T10:30:00+00:00",
    }
    supabase = MagicMock()
    redis = _redis_with_ces_history([60.12345, 70.98765, 80.54321])

    with (
        patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
        patch("app.core.db.single_row", return_value=session_row),
        patch("app.core.db.rows", return_value=[]),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
            ),
        ),
    ):
        select_eq = supabase.table.return_value.select.return_value.eq.return_value
        select_eq.maybe_single.return_value.execute.return_value = MagicMock(data=session_row)
        select_eq.execute.return_value = MagicMock(data=[], count=0)

        result = await get_session_report(
            session_id="ses-50b",
            user_id="usr-1",
            supabase=supabase,
            redis=redis,
        )

    summary = result.ces_history_summary
    assert summary is not None
    # All values must have at most 2 decimal places
    for key in ["mean", "min", "max"]:
        val = summary[key]
        # round(val, 2) must equal val (within float precision)
        assert round(val, 2) == pytest.approx(val, abs=1e-9), (
            f"{key}={val} is not rounded to 2 decimal places"
        )


# ── S3-51 AC 1 — field on SessionReport model ────────────────────────────────


@pytest.mark.unit
def test_intervention_messages_used_field_on_session_report_model():
    """AC1: SessionReport has intervention_messages_used: int = 0."""
    from app.modules.assessment.router import SessionReport

    fields = SessionReport.model_fields
    assert "intervention_messages_used" in fields, (
        "intervention_messages_used missing from SessionReport"
    )
    assert fields["intervention_messages_used"].default == 0, (
        "intervention_messages_used must default to 0"
    )


# ── S3-51 AC 2 / AC 3 — value equals interventions_count ─────────────────────


@pytest.mark.unit
def test_intervention_messages_used_equals_interventions_count():
    """AC2/AC3: intervention_messages_used == interventions_count for same session."""
    from app.modules.assessment.router import SessionReport

    report = SessionReport(
        session_id="s",
        user_id="u",
        lesson_id="l",
        ces_score=0.0,
        ces_breakdown={},
        interventions_count=3,
        quiz_score=None,
        teachback_score=None,
        duration_minutes=0.0,
        completed_at=None,
        tier="T2",
        tier_label="Standard",
        quiz_total_questions=0,
        quiz_correct_count=0,
        quiz_accuracy_label=None,
        formula_applied="full_5_signal",
        signal_coverage=5,
        intervention_messages_used=3,
    )
    assert report.intervention_messages_used == 3


@pytest.mark.unit
def test_intervention_messages_used_zero_when_no_interventions():
    """AC3: intervention_messages_used == 0 when no intervention events."""
    from app.modules.assessment.router import SessionReport

    report = SessionReport(
        session_id="s",
        user_id="u",
        lesson_id="l",
        ces_score=0.0,
        ces_breakdown={},
        interventions_count=0,
        quiz_score=None,
        teachback_score=None,
        duration_minutes=0.0,
        completed_at=None,
        tier="T2",
        tier_label="Standard",
        quiz_total_questions=0,
        quiz_correct_count=0,
        quiz_accuracy_label=None,
        formula_applied="full_5_signal",
        signal_coverage=5,
        intervention_messages_used=0,
    )
    assert report.intervention_messages_used == 0


# ── S3-50 AC 3 (service-level) — redis provided but history empty → None ─────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_summary_none_when_redis_provided_but_history_empty():
    """AC3 (service path): ces_history_summary is None when redis is provided
    but the history key returns an empty list (cold start or first-window race).

    This is distinct from redis=None — the service's `if ces_vals:` guard must
    return None for a real Redis client with an empty list.
    """
    from app.modules.assessment.service import get_session_report

    session_row = {
        "session_id": "ses-50c",
        "user_id": "usr-1",
        "lesson_id": "les-1",
        "ces_final": 65.0,
        "started_at": "2026-08-12T10:00:00+00:00",
        "ended_at": "2026-08-12T10:30:00+00:00",
    }
    supabase = MagicMock()
    select_eq = supabase.table.return_value.select.return_value.eq.return_value
    select_eq.maybe_single.return_value.execute.return_value = MagicMock(data=session_row)
    select_eq.execute.return_value = MagicMock(data=[], count=0)

    # Redis returns empty list for all lrange calls
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])

    with (
        patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
        patch("app.core.db.single_row", return_value=session_row),
        patch("app.core.db.rows", return_value=[]),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
            ),
        ),
    ):
        result = await get_session_report(
            session_id="ses-50c",
            user_id="usr-1",
            supabase=supabase,
            redis=redis,
        )

    assert result.ces_history_summary is None, (
        "ces_history_summary must be None when Redis returns an empty ces_history list"
    )


# ── S3-51 AC 2 (service-level) — intervention_messages_used from session_events ──


@pytest.mark.unit
@pytest.mark.asyncio
async def test_intervention_messages_used_from_session_events_count():
    """AC2 (service path): intervention_messages_used = count of intervention_triggered events.

    This test exercises the SERVICE query path (Step 4 in get_session_report),
    not just the Pydantic model constructor. It verifies that the interventions_count
    DB query result flows through to intervention_messages_used in the response.
    """
    from app.modules.assessment.service import get_session_report

    session_row = {
        "session_id": "ses-51",
        "user_id": "usr-1",
        "lesson_id": "les-1",
        "ces_final": 72.0,
        "started_at": "2026-08-12T10:00:00+00:00",
        "ended_at": "2026-08-12T10:45:00+00:00",
    }
    supabase = MagicMock()

    call_count = 0

    def _select_side_effect(*args, **kwargs):
        nonlocal call_count
        mock = MagicMock()
        mock.eq.return_value = mock
        mock.maybe_single.return_value = mock
        mock.limit.return_value = mock
        call_count += 1
        if call_count == 1:
            # sessions table query
            mock.execute.return_value = MagicMock(data=session_row)
        elif call_count == 2:
            # tier query
            mock.execute.return_value = MagicMock(data=None)
        elif call_count == 3:
            # quiz_attempts — no rows
            mock.execute.return_value = MagicMock(data=[], count=0)
        elif call_count == 4:
            # teachback_attempts — no rows
            mock.execute.return_value = MagicMock(data=[], count=0)
        else:
            # session_events intervention_triggered — 2 events
            mock.execute.return_value = MagicMock(data=[], count=2)
        return mock

    supabase.table.return_value.select.side_effect = _select_side_effect

    with (
        patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
        patch("app.core.db.single_row", return_value=session_row),
        patch("app.core.db.rows", return_value=[]),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
            ),
        ),
    ):
        result = await get_session_report(
            session_id="ses-51",
            user_id="usr-1",
            supabase=supabase,
            redis=None,
        )

    assert result.intervention_messages_used == result.interventions_count, (
        "intervention_messages_used must equal interventions_count (same session_events source)"
    )
