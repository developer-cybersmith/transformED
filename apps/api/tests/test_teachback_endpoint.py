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
    """AC 11: session.user_id != JWT user_id → HTTP 404 (changed from 403 per SEC-006).

    Returns 404 instead of 403 to prevent session enumeration oracle attacks.
    Attacker cannot distinguish "no such session" from "session exists but not yours".
    """
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
    assert exc_info.value.status_code == 404


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
async def test_lesson_no_content_returns_404(mock_to_thread, mock_score_teachback) -> None:
    """lesson_resp.data exists but content is None → HTTP 404.

    This is the 'lesson created but pipeline not yet complete' scenario.
    Code path: lesson_resp.data.get('content') is None.
    """
    from fastapi import HTTPException
    supabase = _build_supabase_tb(session_data=_SESSION_ROW, lesson_data={"content": None})
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
    """AC 10: Happy path — grade_teachback returns TeachbackResult with correct values (not just field existence)."""
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
    # Value assertions — not just schema-membership assertions
    assert result.overall_score == pytest.approx(float(_MOCK_TB_RESULT.score))
    assert result.ces_contribution == pytest.approx(round((_MOCK_TB_RESULT.score / 100.0) * 0.25 * 100, 4))
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


# ── AC 6 / AC 7: LLM call argument verification ───────────────────────────────

@pytest.mark.unit
async def test_score_teachback_called_with_correct_args(mock_to_thread) -> None:
    """AC 6: score_teachback() receives topic, key_concepts, response_text from the segment."""
    captured_kwargs: dict = {}

    async def _capture_score_teachback(**kwargs):
        captured_kwargs.update(kwargs)
        return _MOCK_TB_RESULT

    import pytest as _pt
    from unittest.mock import patch as _patch

    with _patch("app.modules.assessment.service.score_teachback", _capture_score_teachback):
        supabase = _default_supabase_tb()
        await grade_teachback(
            session_id="sess-001",
            lesson_id="lesson-001",
            segment_id="seg-001",
            response_text="Chlorophyll captures sunlight for photosynthesis.",
            user_id="user-001",
            supabase=supabase,
        )

    assert captured_kwargs["topic"] == "Photosynthesis", (
        f"topic must be segment['title'], got {captured_kwargs.get('topic')!r}"
    )
    assert captured_kwargs["key_concepts"] == ["chlorophyll", "ATP"], (
        f"key_concepts must be [j['term'] for j in jargon], got {captured_kwargs.get('key_concepts')!r}"
    )
    assert captured_kwargs["response_text"] == "Chlorophyll captures sunlight for photosynthesis."


@pytest.mark.unit
async def test_llm_provider_constructed_with_lesson_id(mock_to_thread, mock_score_teachback) -> None:
    """AC 7: OpenAILLMProvider is constructed with lesson_id so cost is tracked per lesson."""
    from unittest.mock import patch as _patch, MagicMock as _MM, call as _call

    provider_mock_cls = _MM()
    provider_mock_cls.return_value = _MM()

    with _patch("app.modules.assessment.service.OpenAILLMProvider", provider_mock_cls):
        supabase = _default_supabase_tb()
        await grade_teachback(
            session_id="sess-001",
            lesson_id="lesson-001",
            segment_id="seg-001",
            response_text="My explanation.",
            user_id="user-001",
            supabase=supabase,
        )

    provider_mock_cls.assert_called_once()
    assert provider_mock_cls.call_args.kwargs.get("lesson_id") == "lesson-001", (
        f"OpenAILLMProvider must be constructed with lesson_id='lesson-001', "
        f"got kwargs={provider_mock_cls.call_args.kwargs!r}"
    )


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
    # AC 13: feedback_praise and feedback_correction also persisted separately
    assert captured_rows[0]["feedback_praise"] == _MOCK_TB_RESULT.praise
    assert captured_rows[0]["feedback_correction"] == _MOCK_TB_RESULT.correction


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


# ── AC 1: Field bounds tests (SEC-002 + TQ-002) ──────────────────────────────

@pytest.mark.unit
def test_empty_response_text_rejected() -> None:
    """AC 1: response_text="" → HTTP 422 (min_length=1 violated)."""
    payload = {**_VALID_HTTP_PAYLOAD, "response_text": ""}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/teachback", json=payload)
    assert resp.status_code == 422, f"Expected 422 for empty response_text, got {resp.status_code}"


@pytest.mark.unit
def test_response_text_too_long_rejected() -> None:
    """AC 1: response_text with 4001 chars → HTTP 422 (max_length=4000 violated)."""
    payload = {**_VALID_HTTP_PAYLOAD, "response_text": "x" * 4001}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/teachback", json=payload)
    assert resp.status_code == 422, f"Expected 422 for 4001-char response_text, got {resp.status_code}"


@pytest.mark.unit
def test_response_text_at_max_length_accepted(monkeypatch) -> None:
    """AC 1: response_text with exactly 4000 chars → HTTP 200 (boundary accepted)."""
    async def _fake_grade_teachback(**kwargs):
        return TeachbackResult(
            session_id=kwargs["session_id"],
            rubric_scores={"accuracy": 80.0, "completeness": 70.0, "clarity": 75.0},
            overall_score=75.0,
            ces_contribution=18.75,
            feedback="Good job.",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    payload = {**_VALID_HTTP_PAYLOAD, "response_text": "x" * 4000}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/teachback", json=payload)
    assert resp.status_code == 200, f"Expected 200 for 4000-char response_text, got {resp.status_code}"


@pytest.mark.unit
def test_response_text_single_char_accepted(monkeypatch) -> None:
    """AC 1: response_text="x" (single char) → HTTP 200 (min valid)."""
    async def _fake_grade_teachback(**kwargs):
        return TeachbackResult(
            session_id=kwargs["session_id"],
            rubric_scores={"accuracy": 80.0, "completeness": 70.0, "clarity": 75.0},
            overall_score=75.0,
            ces_contribution=18.75,
            feedback="Good job.",
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_teachback", _fake_grade_teachback)
    payload = {**_VALID_HTTP_PAYLOAD, "response_text": "x"}
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/teachback", json=payload)
    assert resp.status_code == 200, f"Expected 200 for single-char response_text, got {resp.status_code}"


# ── AC 2 + AC 3: LLM failure handling (TQ-001 + INT-06) ──────────────────────

@pytest.mark.unit
async def test_score_teachback_exception_returns_502(mock_to_thread) -> None:
    """AC 2: score_teachback raises RuntimeError → grade_teachback raises HTTP 502."""
    from fastapi import HTTPException

    async def _raise_error(**kwargs):
        raise RuntimeError("OpenAI connection refused")

    import pytest as _pt
    from unittest.mock import patch as _patch

    with _patch("app.modules.assessment.service.score_teachback", _raise_error):
        supabase = _default_supabase_tb()
        with pytest.raises(HTTPException) as exc_info:
            await grade_teachback(
                session_id="sess-001",
                lesson_id="lesson-001",
                segment_id="seg-001",
                response_text="My explanation.",
                user_id="user-001",
                supabase=supabase,
            )
    assert exc_info.value.status_code == 502, (
        f"Expected 502 when score_teachback raises, got {exc_info.value.status_code}"
    )


@pytest.mark.unit
async def test_score_teachback_returns_none_gives_502(mock_to_thread) -> None:
    """AC 3: score_teachback returns None → grade_teachback raises HTTP 502."""
    from fastapi import HTTPException

    async def _return_none(**kwargs):
        return None

    from unittest.mock import patch as _patch

    with _patch("app.modules.assessment.service.score_teachback", _return_none):
        supabase = _default_supabase_tb()
        with pytest.raises(HTTPException) as exc_info:
            await grade_teachback(
                session_id="sess-001",
                lesson_id="lesson-001",
                segment_id="seg-001",
                response_text="My explanation.",
                user_id="user-001",
                supabase=supabase,
            )
    assert exc_info.value.status_code == 502, (
        f"Expected 502 when score_teachback returns None, got {exc_info.value.status_code}"
    )


# ── AC 6 / AC 11: Session wrong-owner now 404 (SEC-006) ─────────────────────

@pytest.mark.unit
async def test_session_wrong_user_returns_404(mock_to_thread, mock_score_teachback) -> None:
    """AC 6 + AC 11: session.user_id != JWT user_id → HTTP 404 'not found or access denied'."""
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
    assert exc_info.value.status_code == 404, (
        f"Expected 404 for wrong-owner session, got {exc_info.value.status_code}"
    )
    assert "not found or access denied" in exc_info.value.detail.lower(), (
        f"Expected 'not found or access denied' in detail, got: {exc_info.value.detail!r}"
    )


# ── AC 7: Feedback boundary score tests (TQ-004) ─────────────────────────────

@pytest.mark.unit
async def test_feedback_boundary_score_89_praise_and_correction(mock_to_thread, monkeypatch) -> None:
    """AC 7: score=89 with non-empty correction → feedback = praise + '\\n\\n' + correction."""
    result_89 = TeachbackScoreResult(
        score=89,
        accuracy_score=89,
        completeness_score=89,
        clarity_score=89,
        praise="Good effort explaining the topic.",
        correction="Fix this: you missed the ATP cycle.",
        concepts_hit=["chlorophyll"],
        concepts_missed=["ATP"],
    )

    async def _fake(**kwargs):
        return result_89

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _fake)
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    expected = f"{result_89.praise}\n\n{result_89.correction}"
    assert result.feedback == expected, (
        f"score=89: expected praise+correction, got: {result.feedback!r}"
    )


@pytest.mark.unit
async def test_feedback_boundary_score_90_praise_only(mock_to_thread, monkeypatch) -> None:
    """AC 7: score=90 with non-empty correction → model_validator clears correction → feedback = praise only."""
    # TeachbackScoreResult model_validator clears correction when score >= 90
    result_90 = TeachbackScoreResult(
        score=90,
        accuracy_score=90,
        completeness_score=90,
        clarity_score=90,
        praise="Excellent work on the core concepts.",
        correction="Some minor detail missed.",  # model_validator will clear this
        concepts_hit=["chlorophyll", "ATP"],
        concepts_missed=[],
    )
    # After model_validator: result_90.correction == ""
    assert result_90.correction == "", "model_validator must clear correction when score >= 90"

    async def _fake(**kwargs):
        return result_90

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _fake)
    supabase = _default_supabase_tb()
    result = await grade_teachback(
        session_id="sess-001",
        lesson_id="lesson-001",
        segment_id="seg-001",
        response_text="Excellent explanation.",
        user_id="user-001",
        supabase=supabase,
    )
    assert result.feedback == result_90.praise, (
        f"score=90: expected praise only, got: {result.feedback!r}"
    )
    assert "\n\n" not in result.feedback, "No separator when score >= 90"


# ── AC 8: Comprehensive DB write test (TQ-005) ───────────────────────────────

@pytest.mark.unit
async def test_comprehensive_db_write_all_fields(mock_to_thread, mock_score_teachback) -> None:
    """AC 8: All 9 required keys must be present in the teachback_attempts insert row."""
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
        response_text="My detailed explanation.",
        user_id="user-001",
        supabase=supabase,
    )

    assert len(captured_rows) == 1
    row = captured_rows[0]

    # Assert all 9 required keys are present
    required_keys = {
        "session_id", "segment_id", "response_text", "score",
        "feedback_praise", "feedback_correction", "concepts_hit",
        "concepts_missed", "attempt_number",
    }
    missing = required_keys - set(row.keys())
    assert not missing, f"Missing keys in DB insert: {missing}"

    # Assert values match the mock LLM result
    assert row["session_id"] == "sess-001"
    assert row["segment_id"] == "seg-001"
    assert row["response_text"] == "My detailed explanation."
    assert row["score"] == _MOCK_TB_RESULT.score
    assert row["feedback_praise"] == _MOCK_TB_RESULT.praise
    assert row["feedback_correction"] == _MOCK_TB_RESULT.correction
    assert row["concepts_hit"] == _MOCK_TB_RESULT.concepts_hit
    assert row["concepts_missed"] == _MOCK_TB_RESULT.concepts_missed
    assert row["attempt_number"] == 1  # first attempt (count=0)


# ── AC 9: attempt_number when count is None (TQ-005) ─────────────────────────

@pytest.mark.unit
async def test_attempt_number_count_none_defaults_to_1(mock_to_thread, mock_score_teachback) -> None:
    """AC 9: count_resp.count=None → attempt_number defaults to 1 (not 0+1 = 1 via None or 0)."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}
    count_mock = MagicMock()
    # Simulate supabase-py returning None for count (empty result set)
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = None

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
        response_text="First attempt explanation.",
        user_id="user-001",
        supabase=supabase,
    )

    assert len(captured_rows) == 1
    assert captured_rows[0]["attempt_number"] == 1, (
        f"When count=None, attempt_number must be 1, got {captured_rows[0]['attempt_number']}"
    )


# ── AC 10: Happy path value assertions (TQ-012) ──────────────────────────────

@pytest.mark.unit
async def test_happy_path_all_field_values(mock_to_thread, mock_score_teachback) -> None:
    """AC 10: Assert specific values for overall_score, ces_contribution, and feedback."""
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
    # Value assertions — not just field existence
    assert result.overall_score == pytest.approx(float(_MOCK_TB_RESULT.score)), (
        f"overall_score: expected {float(_MOCK_TB_RESULT.score)}, got {result.overall_score}"
    )
    expected_ces = round((_MOCK_TB_RESULT.score / 100.0) * 0.25 * 100, 4)
    assert result.ces_contribution == pytest.approx(expected_ces), (
        f"ces_contribution: expected {expected_ces}, got {result.ces_contribution}"
    )
    expected_feedback = f"{_MOCK_TB_RESULT.praise}\n\n{_MOCK_TB_RESULT.correction}"
    assert result.feedback == expected_feedback, (
        f"feedback mismatch: expected {expected_feedback!r}, got {result.feedback!r}"
    )
