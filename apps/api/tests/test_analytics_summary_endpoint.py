"""
Tests for GET /api/analytics/session/{session_id}/summary endpoint.

Story 3-21 — Analytics Session Summary

Test count: 31
All tests are @pytest.mark.unit — no external services required.

Coverage:
  - Happy path: 200 + all SessionSummary fields (ACs 1–9)
  - Zero / null states (ACs 10–12)
  - IDOR / not-found (SEC-006) (ACs 14–16)
  - Duration edge cases (AC 9, AC 17)
  - Rounding: 2dp duration, 4dp attention scores, fractional blink sum (ACs 9–12)
  - Process integrity: no LLM calls, correct DB call order, asyncio.to_thread × 3 (AC 15)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user
from app.modules.analytics.router import router as analytics_router

# ── Constants ─────────────────────────────────────────────────────────────────

USER_ID = "user-00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "user-00000000-0000-0000-0000-000000000002"
SESSION_ID = "sess-abc123"
LESSON_ID = "lesson-xyz789"

# ── Test client setup ─────────────────────────────────────────────────────────


async def _fake_user() -> dict:
    return {"sub": USER_ID, "email": "test@example.com"}


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(analytics_router, prefix="/api/analytics")
client = TestClient(_app, raise_server_exceptions=False)

_unauth_app = FastAPI()
_unauth_app.include_router(analytics_router, prefix="/api/analytics")
unauth_client = TestClient(_unauth_app, raise_server_exceptions=False)

# ── Baseline data ─────────────────────────────────────────────────────────────

_SESSION_ROW = {
    "session_id": SESSION_ID,
    "user_id": USER_ID,
    "lesson_id": LESSON_ID,
    "ces_final": 72.5,
    "started_at": "2026-07-01T10:00:00Z",
    "ended_at": "2026-07-01T10:30:00Z",
}

# 2 segment_complete, 1 tab_switch, 1 intervention_acknowledged, 1 jargon_hover
_EVENTS_DATA = [
    {"event_type": "segment_complete"},
    {"event_type": "segment_complete"},
    {"event_type": "tab_switch"},
    {"event_type": "intervention_acknowledged"},
    {"event_type": "jargon_hover"},
]

# gaze mean = 0.8, head_pose mean = 0.7, blink sum = 6.0 → total_blinks = 6
_ATTN_DATA = [
    {"gaze_score": 0.8, "head_pose_score": 0.7, "blink_rate": 2.0},
    {"gaze_score": 0.6, "head_pose_score": 0.5, "blink_rate": 3.0},
    {"gaze_score": 1.0, "head_pose_score": 0.9, "blink_rate": 1.0},
]


def _build_summary_supabase(*, session_data=_SESSION_ROW, events_data=None, attn_data=None):
    """Call-order-aware Supabase mock for the summary endpoint.

    DB call order:
      1 → sessions         .select(...).eq(...).maybe_single().execute()
      2 → session_events   .select("event_type").eq(...).limit(10_000).execute()
      3 → attention_events .select("gaze_score, head_pose_score, blink_rate")
                           .eq(...).limit(10_000).execute()
    """
    mock = MagicMock()
    call_count = [0]
    captured: dict[int, MagicMock] = {}

    def _table(name):
        call_count[0] += 1
        n = call_count[0]
        m = MagicMock()
        captured[n] = m
        if n == 1:
            chain = m.select.return_value.eq.return_value.maybe_single.return_value
            chain.execute.return_value.data = session_data
        elif n == 2:
            # .select().eq().limit().execute() — limit was added to cap unbounded fetches
            m.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
                events_data if events_data is not None else []
            )
        elif n == 3:
            m.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
                attn_data if attn_data is not None else []
            )
        return m

    mock.table.side_effect = _table
    mock._captured_mocks = captured
    return mock


@pytest.fixture(autouse=True)
def _mock_to_thread(monkeypatch):
    """Shim asyncio.to_thread so sync lambdas run inline in tests."""

    async def _run(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("app.modules.analytics.service.asyncio.to_thread", _run)


# ── 1. Authentication ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_unauthenticated_request_rejected():
    """No JWT → 401 or 403 (dependency rejects before reaching service)."""
    response = unauth_client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code in (401, 403), (
        f"Expected 401 or 403 for unauthenticated request, got {response.status_code}"
    )


# ── 2–11. Happy path ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_returns_200_with_full_summary_shape():
    """Happy path: 200, all 11 required fields present, and identity fields match DB values."""
    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA, attn_data=_ATTN_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")

    assert response.status_code == 200
    body = response.json()
    required_fields = {
        "session_id",
        "user_id",
        "lesson_id",
        "ces_score",
        "avg_attention",
        "distraction_events",
        "total_blinks",
        "avg_head_pose_score",
        "page_views",
        "duration_seconds",
        "events_count",
    }
    missing = required_fields - body.keys()
    assert not missing, f"Response missing fields: {missing}"
    # P10 — identity field values pinned (not just presence)
    assert body["session_id"] == SESSION_ID
    assert body["user_id"] == USER_ID
    assert body["lesson_id"] == LESSON_ID


@pytest.mark.unit
def test_ces_score_from_sessions_ces_final():
    """ces_score must equal sessions.ces_final (not recomputed)."""
    supabase_mock = _build_summary_supabase()
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["ces_score"] == pytest.approx(72.5)


@pytest.mark.unit
def test_avg_attention_is_mean_of_gaze_scores():
    """avg_attention = mean(gaze_score). 0.8+0.6+1.0=2.4 → 2.4/3 = 0.8."""
    supabase_mock = _build_summary_supabase(attn_data=_ATTN_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["avg_attention"] == pytest.approx(0.8, abs=1e-4)


@pytest.mark.unit
def test_distraction_events_tab_switch_and_intervention_acknowledged():
    """distraction_events = count(tab_switch) + count(intervention_acknowledged)."""
    # _EVENTS_DATA: 1 tab_switch + 1 intervention_acknowledged = 2
    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["distraction_events"] == 2


@pytest.mark.unit
def test_page_views_segment_complete_only():
    """page_views counts only event_type == 'segment_complete'."""
    # _EVENTS_DATA: 2 segment_complete
    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["page_views"] == 2


@pytest.mark.unit
def test_events_count_is_total_event_rows():
    """events_count = total row count regardless of event_type."""
    # _EVENTS_DATA has 5 rows
    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["events_count"] == 5


@pytest.mark.unit
def test_total_blinks_is_int_round_sum_blink_rate():
    """total_blinks = int(round(sum(blink_rate))). 2.0+3.0+1.0=6.0 → 6."""
    supabase_mock = _build_summary_supabase(attn_data=_ATTN_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_blinks"] == 6
    assert isinstance(body["total_blinks"], int)


@pytest.mark.unit
def test_avg_head_pose_score_mean_of_head_pose_scores():
    """avg_head_pose_score = mean(head_pose_score). 0.7+0.5+0.9=2.1 → 0.7."""
    supabase_mock = _build_summary_supabase(attn_data=_ATTN_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["avg_head_pose_score"] == pytest.approx(0.7, abs=1e-4)


@pytest.mark.unit
def test_duration_seconds_calculated_from_timestamps():
    """duration_seconds = (ended_at - started_at).total_seconds(). 30 min = 1800.0."""
    supabase_mock = _build_summary_supabase()
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["duration_seconds"] == pytest.approx(1800.0)


@pytest.mark.unit
def test_duration_seconds_handles_iso_string_timestamps():
    """ISO 8601 string timestamps ('Z' suffix) are parsed correctly."""
    session = {
        **_SESSION_ROW,
        "started_at": "2026-07-01T09:00:00Z",
        "ended_at": "2026-07-01T09:15:30Z",
    }
    supabase_mock = _build_summary_supabase(session_data=session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["duration_seconds"] == pytest.approx(930.0)


# ── 12–16. Zero / null states ─────────────────────────────────────────────────


@pytest.mark.unit
def test_zero_events_returns_zero_event_metrics():
    """No session_events → events_count=0, distraction_events=0, page_views=0."""
    supabase_mock = _build_summary_supabase(events_data=[])
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["events_count"] == 0
    assert body["distraction_events"] == 0
    assert body["page_views"] == 0


@pytest.mark.unit
def test_zero_attention_returns_zero_attention_metrics():
    """No attention_events → avg_attention=0.0, total_blinks=0, avg_head_pose_score=0.0."""
    supabase_mock = _build_summary_supabase(attn_data=[])
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["avg_attention"] == 0.0
    assert body["total_blinks"] == 0
    assert body["avg_head_pose_score"] == 0.0


@pytest.mark.unit
def test_null_gaze_scores_excluded_from_average():
    """Rows with gaze_score=None are excluded; only non-null values averaged."""
    attn = [
        {"gaze_score": None, "head_pose_score": 0.9, "blink_rate": 1.0},
        {"gaze_score": 0.6, "head_pose_score": 0.8, "blink_rate": 2.0},
    ]
    # Non-null gaze: [0.6] → avg = 0.6
    supabase_mock = _build_summary_supabase(attn_data=attn)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["avg_attention"] == pytest.approx(0.6)


@pytest.mark.unit
def test_null_head_pose_scores_excluded_from_average():
    """Rows with head_pose_score=None are excluded; only non-null values averaged."""
    attn = [
        {"gaze_score": 0.7, "head_pose_score": None, "blink_rate": 1.0},
        {"gaze_score": 0.5, "head_pose_score": 0.4, "blink_rate": 1.5},
    ]
    # Non-null head_pose: [0.4] → avg = 0.4
    supabase_mock = _build_summary_supabase(attn_data=attn)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["avg_head_pose_score"] == pytest.approx(0.4)


@pytest.mark.unit
def test_null_blink_rates_excluded_from_sum():
    """Rows with blink_rate=None are excluded from total_blinks sum."""
    attn = [
        {"gaze_score": 0.8, "head_pose_score": 0.7, "blink_rate": None},
        {"gaze_score": 0.6, "head_pose_score": 0.5, "blink_rate": 4.0},
    ]
    # Non-null blink: [4.0] → int(round(4.0)) = 4
    supabase_mock = _build_summary_supabase(attn_data=attn)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["total_blinks"] == 4


# ── 17–19. SEC-006 IDOR / not found ──────────────────────────────────────────


@pytest.mark.unit
def test_session_not_found_returns_404():
    """session_resp.data is None (session does not exist) → HTTP 404 with exact detail."""
    supabase_mock = _build_summary_supabase(session_data=None)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get("/api/analytics/session/nonexistent-session/summary")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found."  # P3 — pin exact string (AC 2)


@pytest.mark.unit
def test_session_owned_by_other_user_returns_404_not_403():
    """Session exists but belongs to different user → HTTP 404 (SEC-006 anti-enumeration)."""
    other_user_session = {**_SESSION_ROW, "user_id": OTHER_USER_ID}
    supabase_mock = _build_summary_supabase(session_data=other_user_session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 404, (
        f"Expected 404 for IDOR attempt (SEC-006 anti-enumeration), got {response.status_code}"
    )
    assert response.json()["detail"] == "Session not found."  # P3 — pin exact string (AC 3)


@pytest.mark.unit
def test_not_found_detail_strings_are_identical():
    """Both 404 paths (not found + IDOR) must return the exact same detail string."""
    # Path 1: session does not exist
    supabase_mock_1 = _build_summary_supabase(session_data=None)
    with patch("app.core.db.get_supabase", return_value=supabase_mock_1):
        resp_missing = client.get("/api/analytics/session/ghost-session/summary")

    # Path 2: session belongs to a different user
    other_user_session = {**_SESSION_ROW, "user_id": OTHER_USER_ID}
    supabase_mock_2 = _build_summary_supabase(session_data=other_user_session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock_2):
        resp_idor = client.get(f"/api/analytics/session/{SESSION_ID}/summary")

    assert resp_missing.status_code == 404
    assert resp_idor.status_code == 404
    # Both paths same detail AND pinned to exact string (P3)
    assert resp_missing.json()["detail"] == "Session not found."
    assert resp_missing.json()["detail"] == resp_idor.json()["detail"], (
        "Both 404 paths must return identical detail (SEC-006 anti-enumeration)"
    )


# ── 20–21. Duration edge cases ────────────────────────────────────────────────


@pytest.mark.unit
def test_duration_seconds_zero_when_ended_at_is_none():
    """ended_at=None (session in progress) → duration_seconds=0.0."""
    session = {**_SESSION_ROW, "ended_at": None}
    supabase_mock = _build_summary_supabase(session_data=session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["duration_seconds"] == 0.0


@pytest.mark.unit
def test_duration_seconds_zero_when_started_at_is_none():
    """started_at=None (corrupt row) → duration_seconds=0.0."""
    session = {**_SESSION_ROW, "started_at": None}
    supabase_mock = _build_summary_supabase(session_data=session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["duration_seconds"] == 0.0


# ── 22–24. Additional edge cases ─────────────────────────────────────────────


@pytest.mark.unit
def test_single_event_and_single_attention_row():
    """Edge: exactly 1 row in each table — verifies no off-by-one errors."""
    events = [{"event_type": "segment_complete"}]
    attn = [{"gaze_score": 0.75, "head_pose_score": 0.65, "blink_rate": 3.0}]
    supabase_mock = _build_summary_supabase(events_data=events, attn_data=attn)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["events_count"] == 1
    assert body["page_views"] == 1
    assert body["avg_attention"] == pytest.approx(0.75)
    assert body["total_blinks"] == 3


@pytest.mark.unit
def test_all_event_types_bucketed_correctly():
    """Multiple event types present: all three buckets computed simultaneously."""
    events = [
        {"event_type": "tab_switch"},
        {"event_type": "tab_switch"},
        {"event_type": "intervention_acknowledged"},
        {"event_type": "segment_complete"},
        {"event_type": "segment_complete"},
        {"event_type": "segment_complete"},
        {"event_type": "jargon_hover"},
        {"event_type": "quiz_skip"},
    ]
    # distraction=3, page_views=3, events_count=8
    supabase_mock = _build_summary_supabase(events_data=events)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["distraction_events"] == 3
    assert body["page_views"] == 3
    assert body["events_count"] == 8


@pytest.mark.unit
def test_ces_score_zero_is_valid():
    """ces_score=0.0 is a valid value and must be returned as-is (not coerced)."""
    session = {**_SESSION_ROW, "ces_final": 0.0}
    supabase_mock = _build_summary_supabase(session_data=session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["ces_score"] == 0.0


# ── 25–26. Process integrity ──────────────────────────────────────────────────


@pytest.mark.unit
def test_supabase_called_in_correct_table_order():
    """Service must query tables in order: sessions → session_events → attention_events."""
    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA, attn_data=_ATTN_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")

    assert response.status_code == 200
    assert supabase_mock.table.call_count == 3, (
        f"Expected 3 table() calls, got {supabase_mock.table.call_count}"
    )
    call_args = [c.args[0] for c in supabase_mock.table.call_args_list]
    assert call_args == ["sessions", "session_events", "attention_events"], (
        f"Wrong table call order: {call_args}"
    )


@pytest.mark.unit
def test_no_llm_calls_made_by_service():
    """Analytics summary is pure DB aggregation — no LLM calls allowed (AC 15 / process integrity).

    Patches OpenAILLMProvider.complete (not the constructor) to catch calls from any
    pre-instantiated singleton, not just newly constructed instances.
    """
    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA, attn_data=_ATTN_DATA)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        with patch("app.providers.llm.openai.OpenAILLMProvider.complete") as mock_complete:
            response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")

    assert response.status_code == 200
    mock_complete.assert_not_called()


# ── New patch-fix tests (code review P1, P4–P7) ───────────────────────────────


@pytest.mark.unit
def test_ces_score_zero_when_ces_final_is_null():
    """ces_final=NULL in DB → ces_score=0.0 (AC 4)."""
    session = {**_SESSION_ROW, "ces_final": None}
    supabase_mock = _build_summary_supabase(session_data=session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["ces_score"] == 0.0


@pytest.mark.unit
def test_asyncio_to_thread_called_three_times():
    """Service wraps all 3 DB calls in asyncio.to_thread.

    None may call supabase directly (AC 15).
    """
    call_count = [0]

    async def _counting_shim(fn, *args, **kwargs):
        call_count[0] += 1
        return fn(*args, **kwargs)

    supabase_mock = _build_summary_supabase(events_data=_EVENTS_DATA, attn_data=_ATTN_DATA)
    with patch("app.modules.analytics.service.asyncio.to_thread", new=_counting_shim):
        with patch("app.core.db.get_supabase", return_value=supabase_mock):
            response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")

    assert response.status_code == 200
    assert call_count[0] == 3, (
        f"Expected asyncio.to_thread called 3 times "
        f"(sessions + session_events + attention_events), got {call_count[0]}"
    )


@pytest.mark.unit
def test_total_blinks_rounds_fractional_sum():
    """total_blinks: int(round(sum(blink_rate))) rounds fractional totals correctly (AC 12)."""
    attn = [
        {"gaze_score": 0.8, "head_pose_score": 0.7, "blink_rate": 1.3},
        {"gaze_score": 0.6, "head_pose_score": 0.5, "blink_rate": 1.4},
    ]
    # 1.3 + 1.4 = 2.7 → int(round(2.7)) = 3
    supabase_mock = _build_summary_supabase(attn_data=attn)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_blinks"] == 3
    assert isinstance(body["total_blinks"], int)


@pytest.mark.unit
def test_duration_seconds_rounded_to_two_decimal_places():
    """duration_seconds rounds to 2dp: sub-second precision preserved (AC 9)."""
    session = {
        **_SESSION_ROW,
        "started_at": "2026-07-01T09:00:00Z",
        "ended_at": "2026-07-01T09:00:00.123456Z",
    }
    # (ended - started).total_seconds() = 0.123456 → round(2dp) = 0.12
    supabase_mock = _build_summary_supabase(session_data=session)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    assert response.json()["duration_seconds"] == pytest.approx(0.12, abs=1e-9)


@pytest.mark.unit
def test_avg_attention_and_head_pose_score_rounded_to_four_decimal_places():
    """avg_attention and avg_head_pose_score round to 4dp for non-terminating means (ACs 10–11)."""
    attn = [
        {"gaze_score": 0.1, "head_pose_score": 0.3, "blink_rate": 1.0},
        {"gaze_score": 0.2, "head_pose_score": 0.5, "blink_rate": 1.0},
        {"gaze_score": 0.4, "head_pose_score": 0.6, "blink_rate": 1.0},
    ]
    # gaze: 0.7/3 = 0.23333... → round(4dp) = 0.2333
    # head_pose: 1.4/3 = 0.46666... → round(4dp) = 0.4667
    supabase_mock = _build_summary_supabase(attn_data=attn)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        response = client.get(f"/api/analytics/session/{SESSION_ID}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["avg_attention"] == pytest.approx(0.2333, abs=1e-4)
    assert body["avg_head_pose_score"] == pytest.approx(0.4667, abs=1e-4)
