"""Unit tests for get_session_report service and GET /session/{id}/report router endpoint.

All tests are @pytest.mark.unit — no real Supabase connection required.
asyncio.to_thread is shimmed to run synchronously so MagicMock chain works correctly.

Covers:
  - AC 1: HTTP 200 + all 9 fields present
  - AC 2: SEC-006 (wrong-user → 404, not 403)
  - AC 3: Non-existent session → 404
  - AC 4: ces_score from sessions.ces_final (including NULL → 0.0)
  - AC 5: quiz_score from quiz_attempts
  - AC 6: teachback_score from teachback_attempts
  - AC 7: ces_breakdown has exactly 5 keys
  - AC 8: ces_breakdown["quiz"] formula
  - AC 9: ces_breakdown["teachback"] formula
  - AC 10: behavioral/head_pose/blink always 0.0
  - AC 11: interventions_count from session_events
  - AC 12: duration_minutes from timestamps
  - AC 13: completed_at as ISO string or None
  - AC 14: No LLM calls
  - AC 15: asyncio.to_thread used (mock_to_thread fixture required)
  - AC 16: Unauthenticated → HTTP 401
  - AC 17: user_id and lesson_id come from DB row, not JWT
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch

from app.dependencies import get_current_user
from app.modules.assessment.router import router


# ── HTTP-layer client (router integration) ────────────────────────────────────

async def _fake_user() -> dict:
    return {"sub": "user-report-001", "email": "report@example.com"}

_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_UNAUTH_APP = FastAPI()
_UNAUTH_APP.include_router(router, prefix="/api/assessment")
_unauth_client = TestClient(_UNAUTH_APP, raise_server_exceptions=False)


# ── Constants ──────────────────────────────────────────────────────────────────

_SESSION_ID = "session-report-001"
_USER_ID = "user-report-001"
_LESSON_ID = "lesson-report-001"

_STARTED_AT = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
_ENDED_AT = datetime(2026, 7, 2, 10, 30, 0, tzinfo=timezone.utc)  # 30 minutes

_SESSION_ROW = {
    "session_id": _SESSION_ID,
    "user_id": _USER_ID,
    "lesson_id": _LESSON_ID,
    "ces_final": 72.50,
    "started_at": _STARTED_AT.isoformat(),
    "ended_at": _ENDED_AT.isoformat(),
}

_QUIZ_ROWS_2_CORRECT_1_WRONG = [
    {"is_correct": True},
    {"is_correct": True},
    {"is_correct": False},
]  # 2/3 = 66.67%

_TEACHBACK_ROWS = [
    {"score": 80},
    {"score": 90},
]  # avg = 85.0

_INTERVENTION_COUNT = 2


# ── Mock builder ──────────────────────────────────────────────────────────────

def _build_report_supabase(
    session_data=_SESSION_ROW,
    quiz_rows=None,
    tb_rows=None,
    intervention_count=0,
) -> MagicMock:
    """Build a mock Supabase client for get_session_report.

    Table call order (must match service implementation exactly):
      1. sessions   — .maybe_single() → session_data
      2. quiz_attempts   — .execute() → data list
      3. teachback_attempts — .execute() → data list
      4. session_events — count query → .count
    """
    if quiz_rows is None:
        quiz_rows = []
    if tb_rows is None:
        tb_rows = []

    mock = MagicMock()
    call_count = [0]
    captured: dict[int, MagicMock] = {}

    def _table(name):
        call_count[0] += 1
        n = call_count[0]
        m = MagicMock()
        captured[n] = m
        if n == 1:
            # sessions — maybe_single
            m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = session_data
        elif n == 2:
            # quiz_attempts — list
            m.select.return_value.eq.return_value.execute.return_value.data = quiz_rows
        elif n == 3:
            # teachback_attempts — list
            m.select.return_value.eq.return_value.execute.return_value.data = tb_rows
        elif n == 4:
            # session_events — count (two .eq() filters: session_id, event_type)
            m.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = intervention_count
        return m

    mock.table.side_effect = _table
    mock._captured_mocks = captured
    return mock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    """Patch get_settings so unit tests don't need real env vars."""
    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)


@pytest.fixture
def mock_to_thread(monkeypatch):
    """Replace asyncio.to_thread with a synchronous shim."""
    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


# ── Service-layer tests ───────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_returns_200_with_all_fields(mock_to_thread):
    """AC 1: Happy path returns all 9 SessionReport fields."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(
        quiz_rows=_QUIZ_ROWS_2_CORRECT_1_WRONG,
        tb_rows=_TEACHBACK_ROWS,
        intervention_count=_INTERVENTION_COUNT,
    )
    result = await get_session_report(
        session_id=_SESSION_ID,
        user_id=_USER_ID,
        supabase=supabase,
    )

    assert result.session_id == _SESSION_ID
    assert result.user_id == _USER_ID
    assert result.lesson_id == _LESSON_ID
    assert result.ces_score is not None
    assert isinstance(result.ces_breakdown, dict)
    assert isinstance(result.interventions_count, int)
    assert result.duration_minutes is not None
    # quiz_score and completed_at may be non-None with data provided
    assert result.quiz_score is not None
    assert result.teachback_score is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_wrong_user_returns_404(mock_to_thread):
    """AC 2: SEC-006 — session owned by another user returns HTTP 404, not 403."""
    from fastapi import HTTPException
    from app.modules.assessment.service import get_session_report

    session_owned_by_other = {**_SESSION_ROW, "user_id": "other-user-999"}
    supabase = _build_report_supabase(session_data=session_owned_by_other)

    with pytest.raises(HTTPException) as exc_info:
        await get_session_report(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=supabase,
        )
    assert exc_info.value.status_code == 404
    # SEC-006: detail must be identical to the nonexistent-session path (no ownership leak)
    assert exc_info.value.detail == "Session not found."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_nonexistent_session_returns_404(mock_to_thread):
    """AC 3: Non-existent session_id returns HTTP 404."""
    from fastapi import HTTPException
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(session_data=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_session_report(
            session_id="nonexistent-session-xyz",
            user_id=_USER_ID,
            supabase=supabase,
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Session not found."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_score_from_sessions_ces_final(mock_to_thread):
    """AC 4: ces_score = float(sessions.ces_final) when not NULL."""
    from app.modules.assessment.service import get_session_report

    session = {**_SESSION_ROW, "ces_final": 83.75}
    supabase = _build_report_supabase(session_data=session)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.ces_score == pytest.approx(83.75)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_score_null_returns_zero(mock_to_thread):
    """AC 4: NULL ces_final → ces_score = 0.0."""
    from app.modules.assessment.service import get_session_report

    session = {**_SESSION_ROW, "ces_final": None}
    supabase = _build_report_supabase(session_data=session)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.ces_score == pytest.approx(0.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_quiz_score_calculated_from_attempts(mock_to_thread):
    """AC 5: quiz_score = (correct_count / total_count) * 100, rounded to 2 dp."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(quiz_rows=_QUIZ_ROWS_2_CORRECT_1_WRONG)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    # 2 correct / 3 total = 66.666... → 66.67
    assert result.quiz_score == pytest.approx(66.67, abs=0.01)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_quiz_score_none_when_no_attempts(mock_to_thread):
    """AC 5: quiz_score is None when session has no quiz_attempts."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(quiz_rows=[])
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.quiz_score is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_quiz_score_perfect(mock_to_thread):
    """AC 5: All correct → quiz_score = 100.0."""
    from app.modules.assessment.service import get_session_report

    all_correct = [{"is_correct": True}, {"is_correct": True}, {"is_correct": True}]
    supabase = _build_report_supabase(quiz_rows=all_correct)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.quiz_score == pytest.approx(100.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_teachback_score_calculated_from_attempts(mock_to_thread):
    """AC 6: teachback_score = AVG(score) from teachback_attempts."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(tb_rows=_TEACHBACK_ROWS)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    # AVG([80, 90]) = 85.0
    assert result.teachback_score == pytest.approx(85.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_teachback_score_none_when_no_attempts(mock_to_thread):
    """AC 6: teachback_score is None when session has no teachback_attempts."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(tb_rows=[])
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.teachback_score is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_has_exactly_5_keys(mock_to_thread):
    """AC 7: ces_breakdown has exactly 5 keys: quiz, teachback, behavioral, head_pose, blink."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase()
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert set(result.ces_breakdown.keys()) == {"quiz", "teachback", "behavioral", "head_pose", "blink"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_quiz_matches_formula(mock_to_thread):
    """AC 8: ces_breakdown["quiz"] = quiz_accuracy * ces_weight_quiz * 100."""
    from app.modules.assessment.service import get_session_report

    # 2/3 accuracy = 0.6667, weight=0.35 → 0.6667 * 0.35 * 100 = 23.3333
    supabase = _build_report_supabase(quiz_rows=_QUIZ_ROWS_2_CORRECT_1_WRONG)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    expected = round((2 / 3) * 0.35 * 100, 4)
    assert result.ces_breakdown["quiz"] == pytest.approx(expected, rel=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_quiz_zero_when_no_attempts(mock_to_thread):
    """AC 8: ces_breakdown["quiz"] = 0.0 when no quiz_attempts."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(quiz_rows=[])
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.ces_breakdown["quiz"] == pytest.approx(0.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_teachback_matches_formula(mock_to_thread):
    """AC 9: ces_breakdown["teachback"] = (avg_score/100) * ces_weight_teachback * 100."""
    from app.modules.assessment.service import get_session_report

    # AVG(80, 90) = 85.0 → (85/100) * 0.25 * 100 = 21.25
    supabase = _build_report_supabase(tb_rows=_TEACHBACK_ROWS)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    expected = round((85.0 / 100.0) * 0.25 * 100, 4)
    assert result.ces_breakdown["teachback"] == pytest.approx(expected, rel=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_teachback_zero_when_no_attempts(mock_to_thread):
    """AC 9: ces_breakdown["teachback"] = 0.0 when no teachback_attempts."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(tb_rows=[])
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.ces_breakdown["teachback"] == pytest.approx(0.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_attention_always_zero(mock_to_thread):
    """AC 10: behavioral, head_pose, blink are always 0.0 in Sprint 2."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(
        quiz_rows=_QUIZ_ROWS_2_CORRECT_1_WRONG,
        tb_rows=_TEACHBACK_ROWS,
        intervention_count=3,
    )
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.ces_breakdown["behavioral"] == pytest.approx(0.0)
    assert result.ces_breakdown["head_pose"] == pytest.approx(0.0)
    assert result.ces_breakdown["blink"] == pytest.approx(0.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_interventions_count_from_session_events(mock_to_thread):
    """AC 11: interventions_count = COUNT(*) from session_events WHERE event_type='intervention_triggered'."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(intervention_count=3)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.interventions_count == 3
    # Verify the event_type='intervention_triggered' filter was actually passed to the query
    events_mock = supabase._captured_mocks[4]
    second_eq = events_mock.select.return_value.eq.return_value.eq
    second_eq.assert_called_once_with("event_type", "intervention_triggered")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_interventions_count_zero_when_no_events(mock_to_thread):
    """AC 11: interventions_count = 0 (not None) when no matching events."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(intervention_count=0)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.interventions_count == 0
    assert isinstance(result.interventions_count, int)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_duration_minutes_computed_from_timestamps(mock_to_thread):
    """AC 12: duration_minutes = (ended_at - started_at) in minutes, rounded to 2 dp."""
    from app.modules.assessment.service import get_session_report

    # _ENDED_AT - _STARTED_AT = 30 minutes
    supabase = _build_report_supabase()
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.duration_minutes == pytest.approx(30.0, abs=0.01)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_duration_minutes_fractional(mock_to_thread):
    """AC 12: duration_minutes handles fractional minutes correctly."""
    from app.modules.assessment.service import get_session_report

    started = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
    ended = datetime(2026, 7, 2, 10, 12, 30, tzinfo=timezone.utc)  # 12.5 minutes
    session = {**_SESSION_ROW, "started_at": started.isoformat(), "ended_at": ended.isoformat()}
    supabase = _build_report_supabase(session_data=session)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.duration_minutes == pytest.approx(12.5, abs=0.01)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_duration_minutes_zero_when_ended_at_null(mock_to_thread):
    """AC 12: duration_minutes = 0.0 when ended_at is NULL."""
    from app.modules.assessment.service import get_session_report

    session = {**_SESSION_ROW, "ended_at": None}
    supabase = _build_report_supabase(session_data=session)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.duration_minutes == pytest.approx(0.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_completed_at_isoformat_when_ended_at_set(mock_to_thread):
    """AC 13: completed_at = ended_at.isoformat() when ended_at is not NULL."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase()
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.completed_at is not None
    # Must be a parseable ISO 8601 string
    parsed = datetime.fromisoformat(result.completed_at.replace("Z", "+00:00"))
    assert parsed is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_completed_at_none_when_ended_at_null(mock_to_thread):
    """AC 13: completed_at is None when ended_at is NULL."""
    from app.modules.assessment.service import get_session_report

    session = {**_SESSION_ROW, "ended_at": None}
    supabase = _build_report_supabase(session_data=session)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    assert result.completed_at is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_user_id_and_lesson_id_from_db_row(mock_to_thread):
    """AC 17: user_id and lesson_id come from the sessions DB row, not from the JWT sub."""
    from app.modules.assessment.service import get_session_report

    # JWT sub is "user-report-001" but sessions row has specific UUIDs
    db_user_id = "db-user-uuid-from-row"
    db_lesson_id = "db-lesson-uuid-from-row"
    session = {
        **_SESSION_ROW,
        "user_id": db_user_id,
        "lesson_id": db_lesson_id,
    }
    supabase = _build_report_supabase(session_data=session)
    result = await get_session_report(
        session_id=_SESSION_ID,
        user_id=db_user_id,  # ownership check passes (same user)
        supabase=supabase,
    )
    assert result.user_id == db_user_id
    assert result.lesson_id == db_lesson_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_no_llm_calls(mock_to_thread):
    """AC 14: get_session_report makes no LLM calls whatsoever."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase()
    with patch("app.modules.assessment.service.OpenAILLMProvider") as mock_llm:
        # If get_session_report ever instantiates OpenAILLMProvider it will be recorded
        # We guard against future regressions that accidentally add LLM calls
        try:
            await get_session_report(
                session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
            )
        except Exception:
            pass  # Import error is fine — we just care about no instantiation
        mock_llm.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_ces_breakdown_all_zeros_when_no_data(mock_to_thread):
    """AC 8+9+10: All ces_breakdown values are 0.0 when no quiz/teachback data."""
    from app.modules.assessment.service import get_session_report

    supabase = _build_report_supabase(quiz_rows=[], tb_rows=[], intervention_count=0)
    result = await get_session_report(
        session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase
    )
    for key in ("quiz", "teachback", "behavioral", "head_pose", "blink"):
        assert result.ces_breakdown[key] == pytest.approx(0.0), f"Expected 0.0 for {key!r}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_both_404_paths_return_identical_detail(mock_to_thread):
    """SEC-006: nonexistent session and wrong-user session return the SAME detail string."""
    from fastapi import HTTPException
    from app.modules.assessment.service import get_session_report

    # Path 1 — session does not exist
    supabase_none = _build_report_supabase(session_data=None)
    with pytest.raises(HTTPException) as exc_none:
        await get_session_report(
            session_id="ghost-session", user_id=_USER_ID, supabase=supabase_none
        )

    # Path 2 — session exists but belongs to a different user
    session_other_user = {**_SESSION_ROW, "user_id": "other-user-999"}
    supabase_other = _build_report_supabase(session_data=session_other_user)
    with pytest.raises(HTTPException) as exc_other:
        await get_session_report(
            session_id=_SESSION_ID, user_id=_USER_ID, supabase=supabase_other
        )

    assert exc_none.value.status_code == exc_other.value.status_code == 404
    assert exc_none.value.detail == exc_other.value.detail, (
        "Both 404 paths must return identical detail to prevent session enumeration oracle"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_report_asyncio_to_thread_called_4_times():
    """AC 15: get_session_report wraps all 4 DB calls in asyncio.to_thread."""
    from app.modules.assessment.service import get_session_report
    from unittest.mock import patch

    call_log: list[bool] = []

    async def _counting_shim(func, *args, **kwargs):
        call_log.append(True)
        return func(*args, **kwargs)

    supabase = _build_report_supabase(
        quiz_rows=_QUIZ_ROWS_2_CORRECT_1_WRONG,
        tb_rows=_TEACHBACK_ROWS,
        intervention_count=1,
    )
    with patch("app.modules.assessment.service.asyncio.to_thread", side_effect=_counting_shim):
        await get_session_report(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=supabase,
        )

    assert len(call_log) == 4, f"Expected 4 asyncio.to_thread calls, got {len(call_log)}"


# ── HTTP-layer tests ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_http_get_report_returns_200():
    """AC 1: HTTP-layer smoke test — endpoint returns 200 with SessionReport shape."""
    with (
        patch("app.modules.assessment.service.asyncio.to_thread") as mock_thread,
        patch("app.modules.assessment.service.get_settings") as mock_get_settings,
        patch("app.core.db.get_supabase") as mock_get_supabase,
    ):
        # Wire async shim
        async def _shim(func, *args, **kwargs):
            return func(*args, **kwargs)
        mock_thread.side_effect = _shim

        mock_settings = MagicMock()
        mock_settings.ces_weight_quiz = 0.35
        mock_settings.ces_weight_teachback = 0.25
        mock_get_settings.return_value = mock_settings

        mock_get_supabase.return_value = _build_report_supabase(
            quiz_rows=_QUIZ_ROWS_2_CORRECT_1_WRONG,
            tb_rows=_TEACHBACK_ROWS,
            intervention_count=1,
        )

        resp = _client.get(f"/api/assessment/session/{_SESSION_ID}/report")

    assert resp.status_code == 200
    body = resp.json()
    required_keys = {
        "session_id", "user_id", "lesson_id", "ces_score",
        "ces_breakdown", "interventions_count", "quiz_score",
        "teachback_score", "duration_minutes", "completed_at",
    }
    assert required_keys.issubset(body.keys())


@pytest.mark.unit
def test_http_get_report_unauthenticated_returns_401():
    """AC 16: Request without Bearer token is rejected (HTTPBearer returns 401 or 403).

    FastAPI's HTTPBearer(auto_error=True) fires 403 for missing Authorization header
    and 401 for invalid credentials — both indicate the request was correctly rejected.
    Consistent with test_auth.py::test_no_auth_header_rejected pattern.
    """
    resp = _unauth_client.get(f"/api/assessment/session/{_SESSION_ID}/report")
    assert resp.status_code in (401, 403)
