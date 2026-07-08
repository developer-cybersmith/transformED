"""
Unit tests for stub contracts — tracks which endpoints are live vs. 501.

Verifies that:
- Live endpoints return non-501 (POST /quiz, POST /teachback, POST /onboarding/submit,
  GET /session/{id}/report, POST /api/analytics/events,
  GET /api/analytics/session/{id}/summary)
- The one remaining stub (GET /user/dna) still returns 501
- Pydantic models have exactly the required fields (no banned fields)
- No STT-related field names (transcript, duration_seconds) exist
- LearnerDNA response does not expose raw numeric dimension scores

These tests use @pytest.mark.unit and do NOT require any external services.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user
from app.modules.analytics.router import router as analytics_router
from app.modules.assessment.router import (
    LearnerDNA,
    OnboardingDiagnosticSubmission,
    QuizSubmission,
    TeachbackSubmission,
    router,
)

# ── Test client setup ─────────────────────────────────────────────────────────
# Override get_current_user so endpoint tests reach the route handler without
# a real JWT. The stubs raise 501 before any user data is used, so a fake
# payload is sufficient.

async def _fake_user() -> dict:  # type: ignore[type-arg]
    return {"sub": "test-user-id", "email": "test@example.com"}


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(router, prefix="/api/assessment")
client = TestClient(_app, raise_server_exceptions=False)

# Analytics contract test client (separate app — analytics module)
_analytics_app = FastAPI()
_analytics_app.dependency_overrides[get_current_user] = _fake_user
_analytics_app.include_router(analytics_router, prefix="/api/analytics")
analytics_client = TestClient(_analytics_app, raise_server_exceptions=False)

# Minimal valid payloads for POST endpoints
_QUIZ_PAYLOAD = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "segment_id": "seg-001",
    "answers": [
        {"question_id": "q1", "response_index": 0, "response_time_ms": 1500}
    ],
}

_TEACHBACK_PAYLOAD = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "segment_id": "seg-001",
    "response_text": "The mitochondria is the powerhouse of the cell.",
}

_ONBOARDING_PAYLOAD = {
    "responses": [
        {
            "question_id": "q1",
            "dimension": "processing_style",
            "selected_index": 2,
            "selected_text": "I prefer visual explanations",
        }
    ]
}


# ── Endpoint 501 tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_endpoint_is_live_not_501() -> None:
    """POST /api/assessment/teachback must NOT return 501 (implemented in Sprint 1).

    The endpoint is now live — it delegates to grade_teachback() in service.py.
    Without a real Supabase session it will return 4xx/5xx, but never 501.
    Full contract tests live in test_teachback_endpoint.py.
    """
    response = client.post("/api/assessment/teachback", json=_TEACHBACK_PAYLOAD)
    assert response.status_code != 501, (
        f"Teachback endpoint returned 501 — implementation is missing. "
        "Sprint 1 requires this endpoint to be live."
    )


@pytest.mark.unit
def test_report_endpoint_is_live_not_501() -> None:
    """GET /api/assessment/session/{session_id}/report must NOT return 501 (implemented in Sprint 2).

    The endpoint is now live — it delegates to get_session_report() in service.py.
    Without a real Supabase session it will return 4xx/5xx, but never 501.
    Full contract tests live in test_session_report_endpoint.py.
    """
    response = client.get("/api/assessment/session/test-id/report")
    assert response.status_code != 501, (
        f"Session report endpoint returned 501 — implementation is missing. "
        "Sprint 2 requires this endpoint to be live."
    )


@pytest.mark.unit
def test_dna_endpoint_returns_501() -> None:
    """GET /api/assessment/user/dna must return HTTP 501 NOT_IMPLEMENTED."""
    response = client.get("/api/assessment/user/dna")
    assert response.status_code == 501, (
        f"Expected 501, got {response.status_code}. "
        "Learner DNA endpoint must remain a stub until Sprint 2."
    )


@pytest.mark.unit
def test_onboarding_endpoint_is_live_not_501() -> None:
    """POST /api/assessment/onboarding/submit must NOT return 501 (implemented in Sprint 2, Story 3-18).

    The endpoint is now live — it delegates to process_onboarding() in service.py.
    Without a real Supabase/Redis session it will return 4xx/5xx, but never 501.
    Full contract tests live in test_onboarding_endpoint.py.
    """
    response = client.post("/api/assessment/onboarding/submit", json=_ONBOARDING_PAYLOAD)
    assert response.status_code != 501, (
        f"Onboarding endpoint returned 501 — implementation is missing. "
        "Story 3-18 requires this endpoint to be live."
    )


# ── Model field contract tests ────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_submission_has_response_text() -> None:
    """TeachbackSubmission must have a 'response_text' field (typed teach-back, no STT)."""
    fields = TeachbackSubmission.model_fields
    assert "response_text" in fields, (
        "TeachbackSubmission is missing 'response_text'. "
        "Per CLAUDE.md: teach-back input is always typed text (response_text, not transcript)."
    )


@pytest.mark.unit
def test_teachback_submission_no_transcript_field() -> None:
    """TeachbackSubmission must NOT have a 'transcript' field — STT is banned in MVP."""
    fields = TeachbackSubmission.model_fields
    assert "transcript" not in fields, (
        "TeachbackSubmission has a 'transcript' field — this implies STT which is banned. "
        "Use 'response_text' only."
    )


@pytest.mark.unit
def test_teachback_submission_no_duration_seconds() -> None:
    """TeachbackSubmission must NOT have 'duration_seconds' — no teach-back timer allowed."""
    fields = TeachbackSubmission.model_fields
    assert "duration_seconds" not in fields, (
        "TeachbackSubmission has 'duration_seconds' — this implies a teach-back timer, "
        "which creates test anxiety and is banned per CLAUDE.md."
    )


@pytest.mark.unit
def test_quiz_submission_has_segment_id() -> None:
    """QuizSubmission must have 'segment_id: str' field for per-segment quiz grading."""
    fields = QuizSubmission.model_fields
    assert "segment_id" in fields, (
        "QuizSubmission is missing 'segment_id'. "
        "Quiz grading is per-segment — segment_id is required."
    )


@pytest.mark.unit
def test_learner_dna_response_no_raw_scores() -> None:
    """LearnerDNA response must not expose raw numeric dimension scores to students.

    Per CLAUDE.md: 'Never return raw numeric dimension scores to students — descriptive text only.'
    The model must have badge_labels and profile_text, but no fields named *_score, *_dimension,
    iq_*, eq_*, sq_*, or raw_*.
    """
    fields = set(LearnerDNA.model_fields.keys())

    # Must have the safe display fields
    assert "badge_labels" in fields, "LearnerDNA missing 'badge_labels'"
    assert "profile_text" in fields, "LearnerDNA missing 'profile_text'"

    # Must NOT have raw numeric dimension fields
    banned_patterns = [
        "iq", "eq", "sq",
        "raw_score", "raw_dimension",
        "dimension_score", "dimension_scores",
        "numeric_score",
    ]
    for banned in banned_patterns:
        matching = [f for f in fields if banned in f.lower()]
        assert not matching, (
            f"LearnerDNA has banned field(s) {matching} that expose raw scores. "
            "Per CLAUDE.md: descriptive text only, no IQ/EQ/SQ language."
        )


# ── Analytics contract tests (Story 3-20 + Story 3-21) ───────────────────────


@pytest.mark.unit
def test_analytics_events_endpoint_is_live_not_501() -> None:
    """POST /api/analytics/events must NOT return 501 (implemented in Sprint 2, Story 3-20).

    The endpoint is now live — it delegates to ingest_events() in analytics/service.py.
    Without a real Supabase session it will return 4xx/5xx, but never 501.
    Full contract tests live in test_analytics_events_endpoint.py.
    """
    _mock_supabase = MagicMock()
    with patch("app.core.db.get_supabase", return_value=_mock_supabase):
        response = analytics_client.post(
            "/api/analytics/events",
            json={
                "events": [{
                    "session_id": "sess-stub-check",
                    "event_type": "segment_complete",
                    "payload": {},
                    "client_timestamp_ms": 1_700_000_000_000,
                }]
            },
        )
    assert response.status_code != 501, (
        f"Analytics events endpoint returned 501 — implementation is missing. "
        "Story 3-20 requires this endpoint to be live."
    )


@pytest.mark.unit
def test_analytics_summary_endpoint_is_live_not_501() -> None:
    """GET /api/analytics/session/{id}/summary must NOT return 501 (implemented in Sprint 2, Story 3-21).

    The endpoint is now live — it delegates to get_session_summary() in analytics/service.py.
    Without a real Supabase session it will return 4xx/5xx, but never 501.
    Full contract tests live in test_analytics_summary_endpoint.py.
    """
    _mock_supabase = MagicMock()
    with patch("app.core.db.get_supabase", return_value=_mock_supabase):
        response = analytics_client.get("/api/analytics/session/sess-stub-check/summary")
    assert response.status_code != 501, (
        f"Analytics summary endpoint returned {response.status_code} — expected non-501. "
        "Story 3-21 requires this endpoint to be live."
    )
