"""Unit tests for teach-back grading service (grade_teachback) and POST /teachback endpoint.

All tests are @pytest.mark.unit — no real Supabase or OpenAI connection required.
asyncio.to_thread is shimmed to run synchronously so MagicMock chain works correctly.
score_teachback is monkeypatched to return a fixed TeachbackScoreResult.

Non-negotiable rules enforced here:
  - No `transcript` field on TeachbackSubmission (typed teach-back only)
  - No `duration_seconds` field on TeachbackSubmission or TeachbackResult (no timer)
  - ces_contribution on the 0-100 CES point scale (max 25 pts at weight 0.25)
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.dependencies import get_current_user
from app.modules.assessment.router import router
from app.modules.assessment.schemas import TeachbackResult, TeachbackSubmission
from app.modules.assessment.service import grade_teachback
from app.modules.assessment.prompts import TeachbackScoreResult


# ── HTTP-layer client ─────────────────────────────────────────────────────────

async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}

_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_VALID_HTTP_PAYLOAD = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "segment_id": "seg-001",
    "response_text": "Plants use chlorophyll to capture sunlight and convert CO2 into glucose.",
}


# ── Test data constants ───────────────────────────────────────────────────────

_SESSION_ROW: dict = {
    "session_id": "sess-001",
    "user_id": "user-001",
    "lesson_id": "lesson-001",
}

_SEGMENT: dict = {
    "segment_id": "seg-001",
    "title": "Photosynthesis",
    "jargon": [
        {"term": "chlorophyll", "definition": "Green pigment in plants that absorbs light."},
        {"term": "ATP", "definition": "Adenosine triphosphate — the energy currency of cells."},
    ],
    "teachback_prompt": "Explain how plants convert sunlight into energy.",
    "quiz": [],
}

_LESSON_CONTENT: dict = {
    "lesson_id": "lesson-001",
    "segments": [_SEGMENT],
}

_MOCK_TB_RESULT = TeachbackScoreResult(
    score=75,
    accuracy_score=80,
    completeness_score=70,
    clarity_score=75,
    praise="Great job explaining the core concepts.",
    correction="You missed some details about ATP synthesis.",
    concepts_hit=["chlorophyll"],
    concepts_missed=["ATP"],
)

_MOCK_TB_RESULT_HIGH = TeachbackScoreResult(
    score=95,
    accuracy_score=95,
    completeness_score=95,
    clarity_score=95,
    praise="Excellent explanation with all key details covered.",
    correction="",
    concepts_hit=["chlorophyll", "ATP"],
    concepts_missed=[],
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    """Patch get_settings so unit tests don't need real environment variables."""
    mock_settings = MagicMock()
    mock_settings.ces_weight_teachback = 0.25
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)


@pytest.fixture
def mock_to_thread(monkeypatch):
    """Replace asyncio.to_thread with a synchronous shim and stub OpenAILLMProvider."""
    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)
    monkeypatch.setattr(
        "app.modules.assessment.service.OpenAILLMProvider",
        MagicMock(return_value=MagicMock()),
    )


@pytest.fixture
def mock_score_teachback(monkeypatch):
    """Replace score_teachback with a fixed async stub returning _MOCK_TB_RESULT."""
    async def _fake(*args, **kwargs):
        return _MOCK_TB_RESULT

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _fake)


@pytest.fixture
def mock_score_teachback_high(monkeypatch):
    """Replace score_teachback with a stub returning a high-score result (score=95)."""
    async def _fake(*args, **kwargs):
        return _MOCK_TB_RESULT_HIGH

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _fake)


def _build_supabase_tb(
    session_data=None,
    lesson_data=None,
    attempt_count: int = 0,
    insert_error=None,
) -> MagicMock:
    """Build a mock Supabase client for the grade_teachback call sequence.

    Call order inside grade_teachback:
      1. supabase.table("sessions")      — session ownership check
      2. supabase.table("lessons")       — load lesson JSONB
      3. supabase.table("teachback_attempts") — count existing attempts
      4. supabase.table("teachback_attempts") — insert new row
    """
    if session_data is None and lesson_data is None:
        session_data = _SESSION_ROW
        lesson_data = {"content": _LESSON_CONTENT}

    mock = MagicMock()

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = session_data

    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = lesson_data

    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = attempt_count

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = []
    insert_mock.insert.return_value.execute.return_value.error = insert_error  # None = success

    mock.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]
    return mock


def _default_supabase_tb() -> MagicMock:
    """Valid session + valid lesson, first attempt, clean insert."""
    return _build_supabase_tb(
        session_data=_SESSION_ROW,
        lesson_data={"content": _LESSON_CONTENT},
        attempt_count=0,
    )


# ── Non-negotiable schema rule tests ──────────────────────────────────────────

@pytest.mark.unit
def test_submission_has_no_transcript_or_duration_fields() -> None:
    """TeachbackSubmission must NOT have 'transcript' or 'duration_seconds' fields.

    STT is banned (CLAUDE.md). A timer implies test anxiety. Both fields are permanently banned.
    """
    fields = set(TeachbackSubmission.model_fields.keys())
    assert "transcript" not in fields, "transcript field is BANNED — teach-back is typed only"
    assert "duration_seconds" not in fields, "duration_seconds field is BANNED — implies a timer"


@pytest.mark.unit
def test_result_has_no_duration_seconds_field() -> None:
    """TeachbackResult must NOT have 'duration_seconds' — no timing in response either."""
    fields = set(TeachbackResult.model_fields.keys())
    assert "duration_seconds" not in fields, "duration_seconds field is BANNED from TeachbackResult"


# ── Session / auth validation tests ───────────────────────────────────────────

@pytest.mark.unit
async def test_session_not_found_returns_404(mock_to_thread, mock_score_teachback) -> None:
    """DB returns None for session → HTTP 404."""
    from fastapi import HTTPException
    supabase = _build_supabase_tb(session_data=None, lesson_data={"content": _LESSON_CONTENT})
    with pytest.raises(HTTPException) as exc_info:
        await grade_teachback(
            session_id="missing-sess",
            lesson_id="lesson-001",
            segment_id="seg-001",
            response_text="My explanation.",
            user_id="user-001",
            supabase=supabase,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
async def test_session_wrong_user_returns_403(mock_to_thread, mock_score_teachback) -> None:
    """session.user_id != JWT user_id → HTTP 403."""
    from fastapi import HTTPException
    other_session = {"session_id": "sess-001", "user_id": "attacker", "lesson_id": "lesson-001"}
    supabase = _build_supabase_tb(session_data=other_session, lesson_data={"content": _LESSON_CONTENT})
    with pytest.raises(HTTPException) as exc_info:
        await grade_teachback(
            session_id="sess-001",
            lesson_id="lesson-001",
            segment_id="seg-001",
            response_text="My explanation.",
            user_id="user-001",
            supabase=supabase,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.unit
async def test_idor_lesson_mismatch_returns_403(mock_to_thread, mock_score_teachback) -> None:
    """IDOR guard: session.lesson_id != request lesson_id → HTTP 403.

    An attacker cannot access another lesson's content by supplying a
    session they own but pairing it with a different lesson_id.
    """
    from fastapi import HTTPException
    supabase = _build_supabase_tb(
        session_data=_SESSION_ROW,  # lesson_id = "lesson-001"
        lesson_data={"content": _LESSON_CONTENT},
    )
    with pytest.raises(HTTPException) as exc_info:
        await grade_teachback(
            session_id="sess-001",
            lesson_id="ATTACKER-LESSON",  # mismatch
            segment_id="seg-001",
            response_text="My explanation.",
            user_id="user-001",
            supabase=supabase,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.unit
async def test_lesson_not_found_returns_404(mock_to_thread, mock_score_teachback) -> None:
    """lesson_resp.data is None → HTTP 404."""
    from fastapi import HTTPException
    supabase = _build_supabase_tb(session_data=_SESSION_ROW, lesson_data=None)
    with pytest.raises(HTTPException) as exc_info:
        await grade_teachback(
            session_id="sess-001",
            lesson_id="lesson-001",
            segment_id="seg-001",
            response_text="My explanation.",
            user_id="user-001",
            supabase=supabase,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
async def test_segment_not_found_returns_404(mock_to_thread, mock_score_teachback) -> None:
    """segment_id not in lesson.content.segments → HTTP 404."""
    from fastapi import HTTPException
    supabase = _build_supabase_tb(
        session_data=_SESSION_ROW,
        lesson_data={"content": _LESSON_CONTENT},
    )
    with pytest.raises(HTTPException) as exc_info:
        await grade_teachback(
            session_id="sess-001",
            lesson_id="lesson-001",
            segment_id="NONEXISTENT-SEG",
            response_text="My explanation.",
            user_id="user-001",
            supabase=supabase,
        )
    assert exc_info.value.status_code == 404


# ── Scoring and result shape tests ────────────────────────────────────────────

@pytest.mark.unit
async def test_happy_path_returns_teachback_result(mock_to_thread, mock_score_teachback) -> None:
    """Happy path: grade_teachback returns TeachbackResult with all required fields."""
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Chlorophyll captures sunlight...",
        user_id="user-001",
        supabase=supabase,
    )
    assert isinstance(result, TeachbackResult)
    assert result.session_id == "sess-001"
    assert "overall_score" in result.model_fields
    assert "ces_contribution" in result.model_fields
    assert "rubric_scores" in result.model_fields
    assert "feedback" in result.model_fields


@pytest.mark.unit
async def test_ces_contribution_at_full_score(mock_to_thread, monkeypatch) -> None:
    """score=100 → ces_contribution = 1.0 × ces_weight_teachback × 100 (max 25 pts)."""
    full_score_result = TeachbackScoreResult(
        score=100,
        accuracy_score=100,
        completeness_score=100,
        clarity_score=100,
        praise="Perfect!",
        correction="",
        concepts_hit=["chlorophyll", "ATP"],
        concepts_missed=[],
    )

    async def _fake(*args, **kwargs):
        return full_score_result

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _fake)
    monkeypatch.setattr(
        "app.modules.assessment.service.OpenAILLMProvider",
        MagicMock(return_value=MagicMock()),
    )

    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Perfect explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert result.ces_contribution == pytest.approx(1.0 * 0.25 * 100)


@pytest.mark.unit
async def test_ces_contribution_at_partial_score(mock_to_thread, monkeypatch) -> None:
    """score=50 → ces_contribution = 0.5 × ces_weight_teachback × 100 = 12.5 pts."""
    partial_result = TeachbackScoreResult(
        score=50,
        accuracy_score=50,
        completeness_score=50,
        clarity_score=50,
        praise="Some good points.",
        correction="Many key concepts missed.",
        concepts_hit=["chlorophyll"],
        concepts_missed=["ATP"],
    )

    async def _fake(*args, **kwargs):
        return partial_result

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _fake)
    monkeypatch.setattr(
        "app.modules.assessment.service.OpenAILLMProvider",
        MagicMock(return_value=MagicMock()),
    )

    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Partial explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert result.ces_contribution == pytest.approx(0.5 * 0.25 * 100)


@pytest.mark.unit
async def test_rubric_scores_contains_three_keys(mock_to_thread, mock_score_teachback) -> None:
    """rubric_scores must contain 'accuracy', 'completeness', 'clarity' as float keys."""
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert set(result.rubric_scores.keys()) == {"accuracy", "completeness", "clarity"}
    for key, val in result.rubric_scores.items():
        assert isinstance(val, float), f"rubric_scores['{key}'] must be float, got {type(val)}"
        assert 0.0 <= val <= 100.0, f"rubric_scores['{key}'] = {val} out of range [0, 100]"


@pytest.mark.unit
async def test_rubric_scores_match_llm_sub_scores(mock_to_thread, mock_score_teachback) -> None:
    """rubric_scores values match accuracy_score/completeness_score/clarity_score from LLM result."""
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert result.rubric_scores["accuracy"] == pytest.approx(float(_MOCK_TB_RESULT.accuracy_score))
    assert result.rubric_scores["completeness"] == pytest.approx(float(_MOCK_TB_RESULT.completeness_score))
    assert result.rubric_scores["clarity"] == pytest.approx(float(_MOCK_TB_RESULT.clarity_score))


# ── Feedback format tests ─────────────────────────────────────────────────────

@pytest.mark.unit
async def test_feedback_high_score_praise_only(mock_to_thread, mock_score_teachback_high) -> None:
    """score >= 90: feedback = praise only (correction is empty — no separator appended)."""
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Excellent explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert result.feedback == _MOCK_TB_RESULT_HIGH.praise
    assert "\n\n" not in result.feedback, "separator must not appear when correction is empty"


@pytest.mark.unit
async def test_feedback_low_score_praise_and_correction(mock_to_thread, mock_score_teachback) -> None:
    """score < 90: feedback = praise + '\\n\\n' + correction."""
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Partial explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    expected = f"{_MOCK_TB_RESULT.praise}\n\n{_MOCK_TB_RESULT.correction}"
    assert result.feedback == expected


@pytest.mark.unit
async def test_overall_score_matches_llm_score(mock_to_thread, mock_score_teachback) -> None:
    """TeachbackResult.overall_score = float(result.score) from LLM."""
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert result.overall_score == pytest.approx(float(_MOCK_TB_RESULT.score))


# ── DB write tests ────────────────────────────────────────────────────────────

@pytest.mark.unit
async def test_response_text_written_to_db(mock_to_thread, mock_score_teachback) -> None:
    """response_text from the request is persisted to teachback_attempts."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}
    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

    def _capture(row):
        captured_rows.append(row)
        m = MagicMock()
        m.execute.return_value.data = []
        m.execute.return_value.error = None
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    supabase.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]

    await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="My explanation about chlorophyll.",
        user_id="user-001",
        supabase=supabase,
    )
    assert len(captured_rows) == 1
    assert captured_rows[0]["response_text"] == "My explanation about chlorophyll."


@pytest.mark.unit
async def test_score_written_to_db(mock_to_thread, mock_score_teachback) -> None:
    """LLM result.score is persisted to teachback_attempts.score."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}
    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

    def _capture(row):
        captured_rows.append(row)
        m = MagicMock()
        m.execute.return_value.data = []
        m.execute.return_value.error = None
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    supabase.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]

    await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert captured_rows[0]["score"] == _MOCK_TB_RESULT.score


@pytest.mark.unit
async def test_concepts_written_to_db(mock_to_thread, mock_score_teachback) -> None:
    """concepts_hit and concepts_missed from LLM are persisted to teachback_attempts."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}
    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 0

    def _capture(row):
        captured_rows.append(row)
        m = MagicMock()
        m.execute.return_value.data = []
        m.execute.return_value.error = None
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    supabase.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]

    await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert captured_rows[0]["concepts_hit"] == _MOCK_TB_RESULT.concepts_hit
    assert captured_rows[0]["concepts_missed"] == _MOCK_TB_RESULT.concepts_missed


@pytest.mark.unit
async def test_attempt_number_increments(mock_to_thread, mock_score_teachback) -> None:
    """attempt_number = existing count + 1 (count=1 → attempt_number=2)."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}
    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 1  # one existing attempt

    def _capture(row):
        captured_rows.append(row)
        m = MagicMock()
        m.execute.return_value.data = []
        m.execute.return_value.error = None
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    supabase.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]

    await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Second attempt explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert captured_rows[0]["attempt_number"] == 2


@pytest.mark.unit
async def test_insert_error_raises_500(mock_to_thread, mock_score_teachback) -> None:
    """Supabase insert returns a truthy error → HTTP 500."""
    from fastapi import HTTPException
    supabase = _build_supabase_tb(
        session_data=_SESSION_ROW,
        lesson_data={"content": _LESSON_CONTENT},
        insert_error=MagicMock(),  # truthy → triggers 500
    )
    with pytest.raises(HTTPException) as exc_info:
        await grade_teachback(
            session_id="sess-001",
            lesson_id="lesson-001",
            segment_id="seg-001",
            response_text="Explanation.",
            user_id="user-001",
            supabase=supabase,
        )
    assert exc_info.value.status_code == 500


# ── HTTP-layer test ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_unauthenticated_request_returns_403() -> None:
    """No Authorization header → 401/403. HTTPBearer(auto_error=True) fires before business logic."""
    from fastapi import FastAPI as _FA
    from app.modules.assessment.router import router as _router
    _unauthed_app = _FA()
    _unauthed_app.include_router(_router, prefix="/api/assessment")
    _unauthed_client = TestClient(_unauthed_app, raise_server_exceptions=False)
    resp = _unauthed_client.post("/api/assessment/teachback", json=_VALID_HTTP_PAYLOAD)
    assert resp.status_code in {401, 403}


@pytest.mark.unit
def test_http_layer_post_teachback_returns_200(monkeypatch) -> None:
    """HTTP-layer: POST /api/assessment/teachback wires to grade_teachback correctly."""
    captured_kwargs: dict = {}

    async def _fake_grade_teachback(**kwargs):
        captured_kwargs.update(kwargs)
        return TeachbackResult(
            session_id=kwargs["session_id"],
            rubric_scores={"accuracy": 80.0, "completeness": 70.0, "clarity": 75.0},
            overall_score=75.0,
            ces_contribution=18.75,
            feedback="Good job.",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/teachback", json=_VALID_HTTP_PAYLOAD)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert captured_kwargs["user_id"] == "user-001"
    assert captured_kwargs["session_id"] == "sess-001"
    assert captured_kwargs["segment_id"] == "seg-001"
    assert captured_kwargs["lesson_id"] == "lesson-001"
    assert captured_kwargs["response_text"] == _VALID_HTTP_PAYLOAD["response_text"]
