"""HTTP-layer API contract tests for Dev 2 player integration — Demo T26 Phase L8.

Verifies the exact HTTP payload shapes, Pydantic validation boundaries, and
response field types for POST /sessions, POST /quiz, and POST /teachback.

These are the machine-executable integration requirements for Dev 2's lesson player.
They complement the service-layer tests in test_quiz_endpoint.py and
test_teachback_endpoint.py — no service-layer business logic is retested here.

All tests: @pytest.mark.unit — no real Supabase, Redis, or LLM connections required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user, get_settings
from app.modules.assessment.router import router
from app.modules.assessment.schemas import QuizResult, TeachbackResult

# ── Shared fake users ─────────────────────────────────────────────────────────


async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}


async def _non_approved_user() -> dict:
    return {"sub": "user-002", "email": "not_on_list@example.com"}


# ── Settings factories ────────────────────────────────────────────────────────


def _approved_settings() -> MagicMock:
    """test@example.com is on the allowlist — teachback happy path."""
    s = MagicMock()
    s.approved_emails = ["test@example.com"]
    return s


def _denied_settings() -> MagicMock:
    """No email is approved — teachback 403 path."""
    s = MagicMock()
    s.approved_emails = []
    return s


# ── Test clients ──────────────────────────────────────────────────────────────
#
# Separate apps are required because dependency_overrides are app-scoped.
# _client         — sessions + quiz (CurrentUser, approved settings harmless)
# _approved_client — teachback happy path (approved email)
# _denied_client   — teachback 403 path (non-approved email)

_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.dependency_overrides[get_settings] = _approved_settings
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_approved_app = FastAPI()
_approved_app.dependency_overrides[get_current_user] = _fake_user
_approved_app.dependency_overrides[get_settings] = _approved_settings
_approved_app.include_router(router, prefix="/api/assessment")
_approved_client = TestClient(_approved_app, raise_server_exceptions=False)

_denied_app = FastAPI()
_denied_app.dependency_overrides[get_current_user] = _non_approved_user
_denied_app.dependency_overrides[get_settings] = _denied_settings
_denied_app.include_router(router, prefix="/api/assessment")
_denied_client = TestClient(_denied_app, raise_server_exceptions=False)


# ── Valid payload templates ───────────────────────────────────────────────────

_VALID_SESSION_PAYLOAD = {"lesson_id": "lesson-001"}

_VALID_QUIZ_PAYLOAD = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "segment_id": "seg-001",
    "answers": [{"question_id": "q1", "response_index": 0, "response_time_ms": 1500}],
}

_VALID_TEACHBACK_PAYLOAD = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "segment_id": "seg-001",
    "response_text": "The mitochondria is the powerhouse of the cell.",
}


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — POST /sessions: lesson_id-only contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sessions_returns_201_with_correct_fields(monkeypatch) -> None:
    """AC1: POST /sessions with {lesson_id} only → 201 with {session_id, lesson_id, started_at}."""

    async def _fake_create(**kwargs):
        return {
            "session_id": "s-uuid-001",
            "lesson_id": kwargs["lesson_id"],
            "started_at": "2026-08-13T00:00:00Z",
        }

    monkeypatch.setattr("app.modules.assessment.service.create_session", _fake_create)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/sessions", json=_VALID_SESSION_PAYLOAD)

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "session_id" in body, "Response must include session_id"
    assert "lesson_id" in body, "Response must include lesson_id"
    assert "started_at" in body, "Response must include started_at"


@pytest.mark.unit
def test_sessions_missing_lesson_id_returns_422() -> None:
    """AC1: POST /sessions with no lesson_id → 422 (required field missing).

    Dev 2 must always include lesson_id. Omitting it causes Pydantic validation failure.
    """
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/sessions", json={})
    assert resp.status_code == 422, (
        f"Missing lesson_id must return 422. Got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
def test_sessions_extra_user_id_body_not_rejected(monkeypatch) -> None:
    """AC1 + AC7: POST /sessions with extra user_id in body → 201 (Pydantic discards it silently).

    Dev 2's player may accidentally include user_id. Pydantic's extra='ignore'
    discards it before the handler runs — never causes 422.
    """

    async def _fake_create(**kwargs):
        return {"session_id": "s-uuid-001", "lesson_id": kwargs["lesson_id"], "started_at": None}

    monkeypatch.setattr("app.modules.assessment.service.create_session", _fake_create)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post(
            "/api/assessment/sessions",
            json={"lesson_id": "lesson-001", "user_id": "attacker-id"},
        )

    assert resp.status_code == 201, (
        f"Extra user_id field must be silently discarded, not cause 422 or 400. "
        f"Got {resp.status_code}: {resp.text}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC8 — Security invariant: user_id from body is NEVER trusted
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_user_id_body_field_never_trusted(monkeypatch) -> None:
    """AC8: Security — user_id from body is silently discarded; session uses JWT sub.

    Dev 2 cannot inject a different user_id via the request body.
    The session is ALWAYS created under the verified JWT user's sub ('user-001'),
    never under an attacker-supplied body value ('attacker-id').

    This is independently auditable as a named security test.
    """
    captured: dict = {}

    async def _capture_create(**kwargs):
        captured.update(kwargs)
        return {"session_id": "s-uuid-001", "lesson_id": kwargs["lesson_id"], "started_at": None}

    monkeypatch.setattr("app.modules.assessment.service.create_session", _capture_create)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post(
            "/api/assessment/sessions",
            json={"lesson_id": "lesson-001", "user_id": "attacker-id"},
        )

    assert resp.status_code == 201
    # Security assertion: user_id reaching create_session must be the JWT sub
    assert captured.get("user_id") == "user-001", (
        f"Security: user_id passed to create_session must be JWT sub 'user-001', "
        f"not the body value 'attacker-id'. Got: {captured.get('user_id')!r}"
    )
    assert captured.get("user_id") != "attacker-id", (
        "Security: body user_id 'attacker-id' must never reach create_session"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — POST /quiz: answer list bounds and field validation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_quiz_empty_answers_returns_422() -> None:
    """AC2: answers: [] → 422 (min_length=1 violated).

    Dev 2 must send at least 1 answer. An empty list is always rejected.
    """
    payload = {**_VALID_QUIZ_PAYLOAD, "answers": []}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 422, (
        f"Empty answers must return 422 (min_length=1). Got {resp.status_code}"
    )


@pytest.mark.unit
def test_quiz_51_answers_returns_422() -> None:
    """AC2: 51 answers → 422 (max_length=50 violated).

    Dev 2 must cap the answers list at 50. A segment never exceeds 10 MCQs in practice;
    50 is the absolute ceiling enforced by the API.
    """
    payload = {
        **_VALID_QUIZ_PAYLOAD,
        "answers": [
            {"question_id": f"q{i}", "response_index": 0, "response_time_ms": 0}
            for i in range(51)
        ],
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 422, (
        f"51 answers must return 422 (max_length=50). Got {resp.status_code}"
    )


@pytest.mark.unit
def test_quiz_negative_response_index_returns_422() -> None:
    """AC2: response_index: -1 → 422 (ge=0 violated).

    Dev 2 must send 0 or a positive integer for response_index. Negative values
    are rejected by Pydantic at the HTTP layer before any service call.
    """
    payload = {
        **_VALID_QUIZ_PAYLOAD,
        "answers": [{"question_id": "q1", "response_index": -1, "response_time_ms": 0}],
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 422, (
        f"Negative response_index must return 422 (ge=0). Got {resp.status_code}"
    )


@pytest.mark.unit
def test_quiz_negative_response_time_ms_returns_422() -> None:
    """AC2: response_time_ms: -1 → 422 (ge=0 violated).

    Negative timing values are invalid. Dev 2 should send 0 if timing is unavailable.
    """
    payload = {
        **_VALID_QUIZ_PAYLOAD,
        "answers": [{"question_id": "q1", "response_index": 0, "response_time_ms": -1}],
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 422, (
        f"Negative response_time_ms must return 422 (ge=0). Got {resp.status_code}"
    )


@pytest.mark.unit
def test_quiz_omitted_response_time_ms_returns_200(monkeypatch) -> None:
    """AC2: omitting response_time_ms entirely → 200 (field has default=0, is optional).

    Dev 2's player does NOT need to include response_time_ms.
    When omitted, the server defaults it to 0 and accepts the submission.
    """

    async def _fake_grade_quiz(**kwargs):
        return QuizResult(
            session_id="sess-001",
            score=100.0,
            correct_count=1,
            total_count=1,
            ces_contribution=35.0,
            feedback=[{"question_id": "q1", "is_correct": True, "explanation": "Correct!"}],
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_quiz", _fake_grade_quiz)
    payload = {
        "session_id": "sess-001",
        "lesson_id": "lesson-001",
        "segment_id": "seg-001",
        "answers": [{"question_id": "q1", "response_index": 0}],  # no response_time_ms
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 200, (
        f"Omitting response_time_ms must be accepted (default=0 applies). "
        f"Got {resp.status_code}: {resp.text}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — POST /quiz: QuizResult.feedback is list[dict]
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_quiz_feedback_response_is_list(monkeypatch) -> None:
    """AC3: QuizResult.feedback is list[dict] — Dev 2 must iterate it, not read as string.

    Dev 2 must NOT access feedback as resp.feedback[0].message or resp.feedback.text.
    It is a list of dicts; iterate it with for item in feedback.
    """

    async def _fake_grade_quiz(**kwargs):
        return QuizResult(
            session_id="sess-001",
            score=80.0,
            correct_count=4,
            total_count=5,
            ces_contribution=28.0,
            feedback=[
                {"question_id": "q1", "is_correct": True, "explanation": "Well done!"},
                {"question_id": "q2", "is_correct": False, "explanation": "Review this topic."},
            ],
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_quiz", _fake_grade_quiz)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=_VALID_QUIZ_PAYLOAD)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    feedback = resp.json()["feedback"]
    assert isinstance(feedback, list), (
        f"QuizResult.feedback must be list[dict] at the HTTP level. "
        f"Dev 2 must iterate it — not access as string or single dict. "
        f"Got type: {type(feedback).__name__}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — POST /teachback: response_text bounds and banned field behaviour
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_empty_response_text_returns_422() -> None:
    """AC4: response_text: "" → 422 (min_length=1 violated).

    Dev 2 must ensure the student has typed something before submitting.
    An empty string is always rejected.
    """
    payload = {**_VALID_TEACHBACK_PAYLOAD, "response_text": ""}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _approved_client.post("/api/assessment/teachback", json=payload)
    assert resp.status_code == 422, (
        f"Empty response_text must return 422 (min_length=1). Got {resp.status_code}"
    )


@pytest.mark.unit
def test_teachback_too_long_response_text_returns_422() -> None:
    """AC4: response_text > 4000 chars → 422 (max_length=4000 violated).

    Dev 2 must enforce a 4000-character limit in the UI before submitting.
    This is approximately 500 words — sufficient for any teach-back response.
    """
    payload = {**_VALID_TEACHBACK_PAYLOAD, "response_text": "x" * 4001}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _approved_client.post("/api/assessment/teachback", json=payload)
    assert resp.status_code == 422, (
        f"response_text > 4000 chars must return 422 (max_length=4000). Got {resp.status_code}"
    )


@pytest.mark.unit
def test_teachback_transcript_field_silently_ignored(monkeypatch) -> None:
    """AC4: transcript field in body → 200, silently discarded (not 422).

    STT is permanently banned (CLAUDE.md). transcript is not in TeachbackSubmission.
    Pydantic extra='ignore' discards it before the handler runs.
    Dev 2 will NOT get a 422 if transcript is accidentally included.
    The transcript value is NOT passed to grade_teachback.
    """

    async def _fake_grade_teachback(**kwargs):
        return TeachbackResult(
            session_id="sess-001",
            rubric_scores={"accuracy": "Good", "completeness": "Fair", "clarity": "Good"},
            overall_score=75.0,
            ces_contribution=18.75,
            feedback="Good explanation. Consider adding more detail.",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    payload = {**_VALID_TEACHBACK_PAYLOAD, "transcript": "spoken text here"}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _approved_client.post("/api/assessment/teachback", json=payload)

    assert resp.status_code == 200, (
        f"transcript field must be silently ignored, not cause 422. "
        f"Got {resp.status_code}: {resp.text}"
    )
    assert "transcript" not in resp.json(), (
        "transcript must NOT appear in any response field"
    )


@pytest.mark.unit
def test_teachback_duration_seconds_field_silently_ignored(monkeypatch) -> None:
    """AC4: duration_seconds field in body → 200, silently discarded (not 422).

    No timer exists in teach-back (CLAUDE.md — creates test anxiety).
    duration_seconds is not in TeachbackSubmission or TeachbackResult.
    Dev 2 will NOT get a 422 if duration_seconds is accidentally included.
    """

    async def _fake_grade_teachback(**kwargs):
        return TeachbackResult(
            session_id="sess-001",
            rubric_scores={"accuracy": "Good", "completeness": "Good", "clarity": "Excellent"},
            overall_score=85.0,
            ces_contribution=21.25,
            feedback="Great work!",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    payload = {**_VALID_TEACHBACK_PAYLOAD, "duration_seconds": 120}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _approved_client.post("/api/assessment/teachback", json=payload)

    assert resp.status_code == 200, (
        f"duration_seconds field must be silently ignored, not cause 422. "
        f"Got {resp.status_code}: {resp.text}"
    )
    assert "duration_seconds" not in resp.json(), (
        "duration_seconds must NOT appear in any response field — no timer is implied"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC5 — POST /teachback: TeachbackResult.rubric_scores values are str labels
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_rubric_scores_values_are_string_labels(monkeypatch) -> None:
    """AC5: rubric_scores values are string labels, NOT floats.

    Dev 2 must render rubric_scores values as text, never as numeric bar charts.
    Story 3-14 B5: changed from dict[str, float] to dict[str, str].
    Example: {"accuracy": "Excellent", "completeness": "Good", "clarity": "Needs improvement"}
    """

    async def _fake_grade_teachback(**kwargs):
        return TeachbackResult(
            session_id="sess-001",
            rubric_scores={
                "accuracy": "Excellent",
                "completeness": "Good",
                "clarity": "Needs improvement",
            },
            overall_score=78.0,
            ces_contribution=19.5,
            feedback="Good explanation overall.",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _approved_client.post("/api/assessment/teachback", json=_VALID_TEACHBACK_PAYLOAD)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    rubric = resp.json()["rubric_scores"]
    assert isinstance(rubric, dict), (
        f"rubric_scores must be a dict. Got type: {type(rubric).__name__}"
    )
    for key, val in rubric.items():
        assert isinstance(val, str), (
            f"rubric_scores['{key}'] must be a string label (e.g. 'Excellent'), "
            f"NOT a numeric score. Got: {val!r} (type: {type(val).__name__}). "
            "Dev 2 must render these as text — never as numbers or progress bars "
            "(Story 3-14 B5, CLAUDE.md Learner DNA display rules)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# AC6 — POST /teachback: ApprovedUser gate (403 for non-approved email)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_non_approved_email_returns_403() -> None:
    """AC6: JWT email not on approved list → 403 (ApprovedUser dependency rejects).

    Dev 2 integration note: The approved email list is the APPROVED_EMAILS env var.
    For the demo, Dev 2's test account email must be added to this list.
    Coordinate with the project lead — Dev 3 does not own the approved list.
    """
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _denied_client.post("/api/assessment/teachback", json=_VALID_TEACHBACK_PAYLOAD)
    assert resp.status_code == 403, (
        f"Non-approved email must receive 403 from ApprovedUser gate. "
        f"Got {resp.status_code}: {resp.text}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC7 — Extra fields silently ignored on quiz and teachback endpoints
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_quiz_extra_client_fields_silently_ignored(monkeypatch) -> None:
    """AC7: Extra client metadata fields in quiz payload → 200 (not 422).

    Dev 2 does NOT need to strip client-side metadata before sending quiz payloads.
    Fields like client_timestamp, device_id, user_agent are silently discarded.
    """

    async def _fake_grade_quiz(**kwargs):
        return QuizResult(
            session_id="sess-001",
            score=80.0,
            correct_count=1,
            total_count=1,
            ces_contribution=28.0,
            feedback=[],
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_quiz", _fake_grade_quiz)
    payload = {
        **_VALID_QUIZ_PAYLOAD,
        "client_timestamp": "2026-08-13T10:00:00Z",
        "device_id": "player-browser-abc123",
        "user_agent": "Mozilla/5.0",
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)

    assert resp.status_code == 200, (
        f"Extra client fields in quiz payload must be silently ignored, not cause 422. "
        f"Got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
def test_teachback_extra_client_fields_silently_ignored(monkeypatch) -> None:
    """AC7: Extra client metadata fields in teachback payload → 200 (not 422).

    Dev 2 does NOT need to strip client-side metadata before sending teachback payloads.
    Fields like word_count, segment_title, client_timestamp are silently discarded.
    """

    async def _fake_grade_teachback(**kwargs):
        return TeachbackResult(
            session_id="sess-001",
            rubric_scores={"accuracy": "Good", "completeness": "Good", "clarity": "Good"},
            overall_score=80.0,
            ces_contribution=20.0,
            feedback="Good work!",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    payload = {
        **_VALID_TEACHBACK_PAYLOAD,
        "client_timestamp": "2026-08-13T10:00:00Z",
        "word_count": 47,
        "segment_title": "Photosynthesis",
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _approved_client.post("/api/assessment/teachback", json=payload)

    assert resp.status_code == 200, (
        f"Extra client fields in teachback payload must be silently ignored, not cause 422. "
        f"Got {resp.status_code}: {resp.text}"
    )
