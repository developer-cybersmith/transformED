"""Unit tests for PostHog event instrumentation across assessment actions (Story 3-22).

Test count: 6
Coverage:
- AC 13: quiz submit fires assessment_quiz_submitted
- AC 14: teachback submit fires assessment_teachback_submitted
- AC 15: onboarding complete fires assessment_onboarding_completed
- AC 16: session report viewed fires assessment_session_report_viewed
- AC 17: learner DNA viewed fires assessment_dna_viewed
- AC 18: no posthog call when POSTHOG_API_KEY is empty (default)

All tests are @pytest.mark.unit — no real Supabase, Redis, LLM, or PostHog connections.
asyncio.to_thread is shimmed synchronously via the _mock_to_thread autouse fixture.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.dependencies import get_current_user
from app.modules.assessment.router import router
from app.modules.assessment.schemas import OnboardingAnswer, QuizAnswer
from app.modules.assessment.service import grade_quiz, grade_teachback, process_onboarding

# ── Constants ─────────────────────────────────────────────────────────────────

SESSION_ID = "sess-ph01"
LESSON_ID = "less-ph01"
SEGMENT_ID = "seg-ph01"
USER_ID = "user-ph01"

# ── Minimal data fixtures ─────────────────────────────────────────────────────

_QUESTION: dict = {
    "question_id": "qph1",
    "type": "mcq",
    "question": "What is 2+2?",
    "options": ["3", "4", "5", "6"],
    "correct_index": 1,
    "explanation": "Basic arithmetic.",
    "difficulty": "easy",
}

_SEGMENT: dict = {
    "segment_id": SEGMENT_ID,
    "title": "Intro to Cells",
    "jargon": [],
    "teachback_prompt": "Explain in your own words.",
    "quiz": [_QUESTION],
}

_LESSON_CONTENT: dict = {"segments": [_SEGMENT]}

_SESSION_ROW: dict = {
    "session_id": SESSION_ID,
    "user_id": USER_ID,
    "lesson_id": LESSON_ID,
}

_VALID_ONBOARDING_RESPONSES: list[OnboardingAnswer] = [
    OnboardingAnswer(
        question_id=f"c{i}",
        dimension="cognitive",
        selected_index=2,
        selected_text="Sometimes",
        response_time_ms=1500,
    )
    for i in range(1, 9)
] + [
    OnboardingAnswer(
        question_id=f"e{i}",
        dimension="emotional",
        selected_index=3,
        selected_text="Often",
        response_time_ms=1200,
    )
    for i in range(1, 6)
] + [
    OnboardingAnswer(
        question_id=f"s{i}",
        dimension="self_direction",
        selected_index=1,
        selected_text="Rarely",
        response_time_ms=2000,
    )
    for i in range(1, 8)
]

# ── Router TestClient (for route-level PostHog assertions) ────────────────────

async def _fake_user() -> dict:
    return {"sub": USER_ID, "email": "test@example.com"}

_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

# ── Autouse fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_to_thread(monkeypatch):
    """Shim asyncio.to_thread to run synchronously so MagicMock chains resolve."""
    async def _sync_shim(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    """Inject settings so service layer does not require real env vars."""
    mock_s = MagicMock()
    mock_s.ces_weight_quiz = 0.35
    mock_s.ces_weight_teachback = 0.25
    mock_s.llm_mini = "gpt-4o-mini"
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_s)


@pytest.fixture(autouse=True)
def _enable_posthog_key(monkeypatch):
    """Set posthog.api_key to a non-empty value so capture_event does NOT short-circuit.

    posthog_client.capture_event guards on `posthog.api_key` being truthy.
    Setting it here ensures active tests reach posthog.capture.
    Tests verifying the no-op behaviour (AC 18) override via a second setattr("posthog.api_key","").
    """
    monkeypatch.setattr("posthog.api_key", "phc_test_key")


# ── Supabase mock builders ────────────────────────────────────────────────────


def _build_quiz_supabase() -> MagicMock:
    """4-call mock: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)."""
    supabase = MagicMock()

    session_m = MagicMock()
    session_m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW

    lesson_m = MagicMock()
    lesson_m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "content": _LESSON_CONTENT
    }

    count_m = MagicMock()
    count_m.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

    insert_m = MagicMock()
    insert_m.insert.return_value.execute.return_value.data = []
    insert_m.insert.return_value.execute.return_value.error = None

    supabase.table.side_effect = [session_m, lesson_m, count_m, insert_m]
    return supabase


def _build_teachback_supabase() -> MagicMock:
    """4-call mock: sessions → lessons → teachback_attempts(COUNT) → teachback_attempts(INSERT)."""
    supabase = MagicMock()

    session_m = MagicMock()
    session_m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW

    lesson_m = MagicMock()
    lesson_m.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "content": _LESSON_CONTENT
    }

    count_m = MagicMock()
    count_m.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

    insert_m = MagicMock()
    insert_m.insert.return_value.execute.return_value.data = []
    insert_m.insert.return_value.execute.return_value.error = None

    supabase.table.side_effect = [session_m, lesson_m, count_m, insert_m]
    return supabase


def _build_onboarding_supabase() -> MagicMock:
    """2-call mock: onboarding_responses(INSERT) → learner_dna(UPSERT)."""
    supabase = MagicMock()

    insert_m = MagicMock()
    insert_m.insert.return_value.execute.return_value.data = []
    insert_m.insert.return_value.execute.return_value.error = None

    upsert_m = MagicMock()
    upsert_m.upsert.return_value.execute.return_value.data = [{"user_id": USER_ID}]
    upsert_m.upsert.return_value.execute.return_value.error = None

    supabase.table.side_effect = [insert_m, upsert_m]
    return supabase


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_posthog_quiz_event_fired():
    """AC 13: grade_quiz() fires assessment_quiz_submitted with correct args."""
    supabase = _build_quiz_supabase()
    with patch("app.core.posthog_client.posthog.capture") as mock_capture:
        await grade_quiz(
            session_id=SESSION_ID,
            lesson_id=LESSON_ID,
            segment_id=SEGMENT_ID,
            answers=[QuizAnswer(question_id="qph1", response_index=1, response_time_ms=500)],
            user_id=USER_ID,
            supabase=supabase,
        )
    mock_capture.assert_called_once()
    pos_args = mock_capture.call_args[0]
    assert pos_args[0] == USER_ID, "distinct_id must be user_id"
    assert pos_args[1] == "assessment_quiz_submitted"
    props = pos_args[2]
    assert props["session_id"] == SESSION_ID
    assert "ces_contribution" in props
    assert "quiz_accuracy" in props


@pytest.mark.unit
async def test_posthog_teachback_event_fired():
    """AC 14: grade_teachback() fires assessment_teachback_submitted with correct args."""
    from app.modules.assessment.prompts import TeachbackScoreResult

    mock_score = TeachbackScoreResult(
        score=80,
        praise="Well done!",
        correction="",
        concepts_hit=["cells"],
        concepts_missed=[],
        accuracy_score=80.0,
        completeness_score=75.0,
        clarity_score=85.0,
    )
    supabase = _build_teachback_supabase()
    with patch("app.modules.assessment.service.OpenAILLMProvider") as mock_provider_cls:
        mock_provider_cls.return_value = MagicMock()
        with patch(
            "app.modules.assessment.service.score_teachback",
            new=AsyncMock(return_value=mock_score),
        ):
            with patch("app.core.posthog_client.posthog.capture") as mock_capture:
                await grade_teachback(
                    session_id=SESSION_ID,
                    lesson_id=LESSON_ID,
                    segment_id=SEGMENT_ID,
                    response_text="The cell has a nucleus.",
                    user_id=USER_ID,
                    supabase=supabase,
                )
    mock_capture.assert_called_once()
    pos_args = mock_capture.call_args[0]
    assert pos_args[0] == USER_ID
    assert pos_args[1] == "assessment_teachback_submitted"
    props = pos_args[2]
    assert props["session_id"] == SESSION_ID
    assert props["score"] == 80
    assert "attempt_number" in props


@pytest.mark.unit
async def test_posthog_onboarding_event_fired():
    """AC 15: process_onboarding() fires assessment_onboarding_completed with session_count."""
    supabase = _build_onboarding_supabase()
    with patch("app.modules.assessment.service.OpenAILLMProvider") as mock_provider_cls:
        mock_provider_cls.return_value = MagicMock()
        with patch(
            "app.modules.assessment.service.generate_onboarding_profile",
            new=AsyncMock(return_value="You are a pattern thinker. [DPDP disclaimer]"),
        ):
            with patch("app.core.posthog_client.posthog.capture") as mock_capture:
                await process_onboarding(
                    responses=_VALID_ONBOARDING_RESPONSES,
                    user_id=USER_ID,
                    supabase=supabase,
                )
    mock_capture.assert_called_once()
    pos_args = mock_capture.call_args[0]
    assert pos_args[0] == USER_ID
    assert pos_args[1] == "assessment_onboarding_completed"
    assert "session_count" in pos_args[2]


@pytest.mark.unit
def test_posthog_session_report_event_fired():
    """AC 16: GET /session/{id}/report route fires assessment_session_report_viewed."""
    from app.modules.assessment.router import SessionReport

    mock_report = SessionReport(
        session_id=SESSION_ID,
        user_id=USER_ID,
        lesson_id=LESSON_ID,
        ces_score=72.0,
        ces_breakdown={"quiz": 25.0, "teachback": 15.0, "behavioral": 0.0, "head_pose": 0.0, "blink": 0.0},
        interventions_count=1,
        quiz_score=80.0,
        teachback_score=75.0,
        duration_minutes=12.5,
        completed_at="2026-07-03T10:00:00+00:00",
    )

    with patch("app.modules.assessment.service.get_session_report", new=AsyncMock(return_value=mock_report)):
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            with patch("app.core.posthog_client.posthog.capture") as mock_capture:
                response = _client.get(f"/api/assessment/session/{SESSION_ID}/report")

    assert response.status_code == 200
    mock_capture.assert_called_once()
    pos_args = mock_capture.call_args[0]
    assert pos_args[0] == USER_ID
    assert pos_args[1] == "assessment_session_report_viewed"
    assert pos_args[2] == {"session_id": SESSION_ID}


@pytest.mark.unit
def test_posthog_dna_viewed_event_fired():
    """AC 17: GET /user/dna route fires assessment_dna_viewed with session_count."""
    mock_dna_row = {
        "user_id": USER_ID,
        "badge_labels": ["Pattern Thinker"],
        "profile_text": "You are a strong analytical thinker. [DPDP]",
        "session_count": 3,
        "reassessment_due": False,
        "last_updated": "2026-07-03T09:00:00+00:00",
    }

    with patch("app.modules.assessment.service.get_learner_dna_data", new=AsyncMock(return_value=mock_dna_row)):
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            with patch("app.core.posthog_client.posthog.capture") as mock_capture:
                response = _client.get("/api/assessment/user/dna")

    assert response.status_code == 200
    mock_capture.assert_called_once()
    pos_args = mock_capture.call_args[0]
    assert pos_args[0] == USER_ID
    assert pos_args[1] == "assessment_dna_viewed"
    assert pos_args[2]["session_count"] == 3


@pytest.mark.unit
async def test_posthog_no_call_when_api_key_empty(monkeypatch):
    """AC 18: capture_event is a no-op when posthog.api_key is empty string.

    The autouse _enable_posthog_key fixture sets posthog.api_key to a test
    key. This test overrides it to "" to verify the short-circuit path.
    """
    monkeypatch.setattr("posthog.api_key", "")
    supabase = _build_quiz_supabase()
    with patch("posthog.capture") as mock_capture:
        await grade_quiz(
            session_id=SESSION_ID,
            lesson_id=LESSON_ID,
            segment_id=SEGMENT_ID,
            answers=[QuizAnswer(question_id="qph1", response_index=1, response_time_ms=500)],
            user_id=USER_ID,
            supabase=supabase,
        )
    mock_capture.assert_not_called()
