"""Unit tests for quiz grading service (grade_quiz) and POST /quiz router endpoint.

All tests are @pytest.mark.unit — no real Supabase connection required.
asyncio.to_thread is shimmed to run synchronously so MagicMock chain works correctly.

Includes both direct service-layer tests (grade_quiz called directly) and an
HTTP-layer test via TestClient to verify the router wires to the service correctly.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from unittest.mock import MagicMock, call, patch

from app.dependencies import get_current_user
from app.modules.assessment.router import QuizAnswer, router
from app.modules.assessment.service import grade_quiz

# ── HTTP-layer client (router integration) ────────────────────────────────────

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
    "answers": [{"question_id": "q1", "response_index": 1, "response_time_ms": 1500}],
}


# ── Test data constants ──────────────────────────────────────────────────────

_QUESTION_1: dict = {
    "question_id": "q1",
    "type": "mcq",
    "question": "What is the powerhouse of the cell?",
    "options": ["Nucleus", "Mitochondria", "Ribosome", "Golgi apparatus"],
    "correct_index": 1,
    "explanation": "The mitochondria produces ATP via cellular respiration.",
    "difficulty": "easy",
}

_QUESTION_2: dict = {
    "question_id": "q2",
    "type": "mcq",
    "question": "What molecule carries energy in cells?",
    "options": ["DNA", "RNA", "ATP", "ADP"],
    "correct_index": 2,
    "explanation": "ATP (adenosine triphosphate) is the main energy currency of the cell.",
    "difficulty": "medium",
}

_SEGMENT: dict = {"segment_id": "seg-001", "quiz": [_QUESTION_1, _QUESTION_2]}
_SESSION_ROW: dict = {"session_id": "sess-001", "user_id": "user-001", "lesson_id": "lesson-001"}
_LESSON_CONTENT: dict = {"lesson_id": "lesson-001", "segments": [_SEGMENT]}


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    """Patch get_settings so unit tests don't require real environment variables.

    All happy-path tests reach ces_contribution = quiz_accuracy * settings.ces_weight_quiz * 100,
    so settings must always be mocked. Tests that need a different weight override this
    fixture with their own monkeypatch.setattr on the same target.
    """
    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)


@pytest.fixture
def mock_to_thread(monkeypatch):
    """Replace asyncio.to_thread with a synchronous shim for unit tests.

    The shim runs the lambda immediately rather than dispatching to a thread
    pool, so MagicMock return values resolve correctly without a real event loop
    or thread pool overhead.
    """
    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


def _build_supabase(
    session_data=None,
    lesson_data=None,
    insert_data=None,
    count=0,
) -> MagicMock:
    """Build a mock Supabase client with ordered call side effects.

    Call order matches grade_quiz internals (post-fix):
      sessions → lessons → quiz_attempts (COUNT) → quiz_attempts (INSERT).
    Pass session_data=None to simulate session not found.
    Pass lesson_data with content=None to simulate lesson without content.
    Pass count=N to simulate N existing quiz_attempts rows for attempt_number computation.
    Defaults to count=0 (first attempt, no prior rows).
    """
    if session_data is None and lesson_data is None and insert_data is None:
        # Default: valid session + valid lesson
        session_data = _SESSION_ROW
        lesson_data = {"content": _LESSON_CONTENT}
        insert_data = []

    mock = MagicMock()

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = session_data

    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = lesson_data

    count_resp_obj = MagicMock()
    count_resp_obj.count = count

    count_table_mock = MagicMock()
    count_table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = count_resp_obj

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = insert_data or []
    insert_mock.insert.return_value.execute.return_value.error = None  # explicit success

    # 4-call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)
    mock.table.side_effect = [session_mock, lesson_mock, count_table_mock, insert_mock]
    return mock


def _default_supabase() -> MagicMock:
    """Valid session + valid lesson (happy path)."""
    return _build_supabase(
        session_data=_SESSION_ROW,
        lesson_data={"content": _LESSON_CONTENT},
        insert_data=[],
    )


# ── Grading logic tests ──────────────────────────────────────────────────────


@pytest.mark.unit
async def test_correct_answer_is_marked_correct(mock_to_thread) -> None:
    """response_index == correct_index (1) → is_correct True."""
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1500)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["is_correct"] is True
    assert result.correct_count == 1


@pytest.mark.unit
async def test_wrong_answer_is_marked_incorrect(mock_to_thread) -> None:
    """response_index != correct_index → is_correct False."""
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=0, response_time_ms=1000)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["is_correct"] is False
    assert result.correct_count == 0


@pytest.mark.unit
async def test_all_correct_gives_score_100(mock_to_thread) -> None:
    """2/2 correct → score == 100.0, ces_contribution == 35.0."""
    supabase = _default_supabase()
    answers = [
        QuizAnswer(question_id="q1", response_index=1, response_time_ms=1200),
        QuizAnswer(question_id="q2", response_index=2, response_time_ms=2000),
    ]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.correct_count == 2
    assert result.total_count == 2
    assert result.score == pytest.approx(100.0)
    # AC 7: CES SCALE CONTRACT — all correct at ces_weight_quiz=0.35 must yield exactly 35.0 pts
    assert result.ces_contribution == pytest.approx(35.0)


@pytest.mark.unit
async def test_all_wrong_gives_score_0(mock_to_thread) -> None:
    """0/2 correct → score == 0.0."""
    supabase = _default_supabase()
    answers = [
        QuizAnswer(question_id="q1", response_index=0, response_time_ms=1000),
        QuizAnswer(question_id="q2", response_index=0, response_time_ms=1000),
    ]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.correct_count == 0
    assert result.score == pytest.approx(0.0)
    assert result.ces_contribution == pytest.approx(0.0)


@pytest.mark.unit
async def test_mixed_answers_give_50_percent(mock_to_thread) -> None:
    """1 correct + 1 wrong → score == 50.0."""
    supabase = _default_supabase()
    answers = [
        QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000),  # correct
        QuizAnswer(question_id="q2", response_index=0, response_time_ms=1500),  # wrong
    ]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.score == pytest.approx(50.0)


@pytest.mark.unit
async def test_ces_contribution_uses_quiz_weight(mock_to_thread, monkeypatch) -> None:
    """ces_contribution = accuracy * settings.ces_weight_quiz."""
    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)

    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.ces_contribution == pytest.approx(1.0 * 0.35 * 100)


@pytest.mark.unit
async def test_response_time_ms_written_to_db(mock_to_thread) -> None:
    """response_time_ms from each QuizAnswer is included in the DB insert row."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}

    # count query: count=0 → attempt_number=1 (first attempt)
    count_resp_obj = MagicMock()
    count_resp_obj.count = 0
    count_table_mock = MagicMock()
    count_table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = count_resp_obj

    def _capture(rows):
        captured_rows.extend(rows)
        m = MagicMock()
        m.execute.return_value.data = []
        m.execute.return_value.error = None
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    # 4-call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)
    supabase.table.side_effect = [session_mock, lesson_mock, count_table_mock, insert_mock]

    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=3750)]
    await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert len(captured_rows) == 1
    assert captured_rows[0]["response_time_ms"] == 3750


@pytest.mark.unit
async def test_attempt_number_written_to_db(mock_to_thread) -> None:
    """attempt_number is computed from DB count and written to each quiz_attempts row.

    count=1 (1 prior attempt exists) → service computes attempt_number=2 and inserts it.
    """
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}

    # count=1 → service computes attempt_number = 1 + 1 = 2
    count_resp_obj = MagicMock()
    count_resp_obj.count = 1
    count_table_mock = MagicMock()
    count_table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = count_resp_obj

    def _capture(rows):
        captured_rows.extend(rows)
        m = MagicMock()
        m.execute.return_value.data = []
        m.execute.return_value.error = None
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    # 4-call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)
    supabase.table.side_effect = [session_mock, lesson_mock, count_table_mock, insert_mock]

    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert captured_rows[0]["attempt_number"] == 2


@pytest.mark.unit
async def test_feedback_contains_explanation(mock_to_thread) -> None:
    """Each feedback item includes the QuizQuestion explanation text and question text (AC 12)."""
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=0, response_time_ms=1000)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["explanation"] == _QUESTION_1["explanation"]
    assert result.feedback[0]["question"] == _QUESTION_1["question"]


@pytest.mark.unit
async def test_feedback_contains_correct_option_text(mock_to_thread) -> None:
    """Feedback includes the text of the correct option, not just the index."""
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=0, response_time_ms=1000)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["correct_option"] == "Mitochondria"


# ── Error-handling tests ─────────────────────────────────────────────────────


@pytest.mark.unit
async def test_raises_404_when_session_not_found(mock_to_thread) -> None:
    """DB returns None for session → HTTP 404."""
    from fastapi import HTTPException
    supabase = _build_supabase(session_data=None, lesson_data={"content": _LESSON_CONTENT})
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="missing", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
async def test_session_wrong_user_returns_404(mock_to_thread) -> None:
    """session.user_id != request user_id → HTTP 404 (SEC-006: session enumeration fix).

    AC 4 and AC 8: wrong-owner path must return 404 (not 403) so attackers cannot
    distinguish 'session belongs to someone else' from 'session does not exist'.
    Detail must contain 'not found or access denied'.
    """
    from fastapi import HTTPException
    other_session = {"session_id": "sess-001", "user_id": "other-user", "lesson_id": "lesson-001"}
    supabase = _build_supabase(session_data=other_session, lesson_data={"content": _LESSON_CONTENT})
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 404
    assert "not found or access denied" in exc_info.value.detail


@pytest.mark.unit
async def test_raises_404_when_lesson_content_is_none(mock_to_thread) -> None:
    """lesson.content == None → HTTP 404."""
    from fastapi import HTTPException
    supabase = _build_supabase(session_data=_SESSION_ROW, lesson_data={"content": None})
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
async def test_raises_404_when_segment_not_in_lesson(mock_to_thread) -> None:
    """segment_id not in lesson.segments → HTTP 404."""
    from fastapi import HTTPException
    supabase = _build_supabase(session_data=_SESSION_ROW, lesson_data={"content": _LESSON_CONTENT})
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="DOES-NOT-EXIST",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.unit
async def test_raises_422_when_question_id_not_in_segment(mock_to_thread) -> None:
    """question_id from answer not in segment quiz → HTTP 422."""
    from fastapi import HTTPException
    supabase = _build_supabase(session_data=_SESSION_ROW, lesson_data={"content": _LESSON_CONTENT})
    answers = [QuizAnswer(question_id="BOGUS-Q", response_index=0, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 422


# ── New tests added by post-review audit (BLOCKER fixes) ─────────────────────


@pytest.mark.unit
async def test_raises_422_when_answers_list_is_empty(mock_to_thread) -> None:
    """Empty answers list must be rejected with 422 before any DB write."""
    from fastapi import HTTPException
    supabase = _build_supabase(session_data=_SESSION_ROW, lesson_data={"content": _LESSON_CONTENT})
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=[], user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 422
    # Confirm no insert was attempted for empty submission
    supabase.table.assert_any_call("sessions")
    insert_calls = [c for c in supabase.table.call_args_list if c == call("quiz_attempts")]
    assert not insert_calls, "quiz_attempts must not be touched on empty-answers submission"


@pytest.mark.unit
async def test_table_routing_is_verified(mock_to_thread) -> None:
    """supabase.table() must be called with the correct table names in order.

    Verifies that grade_quiz calls sessions → lessons → quiz_attempts(COUNT) →
    quiz_attempts(INSERT) in that order (4 calls total after S3-12 fix).
    If service.py reorders queries, this test catches it before mocks silently
    return wrong data to wrong queries.
    """
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    calls = [c.args[0] for c in supabase.table.call_args_list]
    assert calls == ["sessions", "lessons", "quiz_attempts", "quiz_attempts"], (
        f"Expected table call order [sessions, lessons, quiz_attempts, quiz_attempts], got {calls}"
    )


@pytest.mark.unit
async def test_correct_index_zero_marks_correct_answer(mock_to_thread) -> None:
    """response_index=0 with correct_index=0 must produce is_correct=True.

    Guards against a falsy-zero bug: `if ans.response_index` instead of
    `== correct_index` would incorrectly treat index 0 as False.
    """
    question_zero = {
        "question_id": "q_zero",
        "type": "mcq",
        "question": "Which option is first?",
        "options": ["First", "Second", "Third", "Fourth"],
        "correct_index": 0,
        "explanation": "The first option is correct.",
        "difficulty": "easy",
    }
    segment = {"segment_id": "seg-001", "quiz": [question_zero]}
    lesson_content = {"lesson_id": "lesson-001", "segments": [segment]}
    supabase = _build_supabase(
        session_data=_SESSION_ROW,
        lesson_data={"content": lesson_content},
        insert_data=[],
    )
    answers = [QuizAnswer(question_id="q_zero", response_index=0, response_time_ms=500)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["is_correct"] is True


@pytest.mark.unit
def test_http_layer_post_quiz_returns_200(monkeypatch) -> None:
    """HTTP-layer: POST /api/assessment/quiz wires correctly to grade_quiz.

    Patches grade_quiz in the service module (the lazy-import source) and
    get_supabase in core.db (where the router's lazy import resolves it).
    Verifies: user_id extracted from JWT sub, all body fields forwarded.
    """
    from app.modules.assessment.schemas import QuizResult as _QuizResult

    captured_kwargs: dict = {}

    async def _fake_grade_quiz(**kwargs):
        captured_kwargs.update(kwargs)
        return _QuizResult(
            session_id=kwargs["session_id"],
            score=100.0,
            correct_count=1,
            total_count=1,
            ces_contribution=35.0,
            feedback=[],
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_quiz", _fake_grade_quiz)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=_VALID_HTTP_PAYLOAD)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert captured_kwargs["user_id"] == "user-001", "user_id must be JWT sub"
    assert captured_kwargs["session_id"] == "sess-001"
    assert captured_kwargs["segment_id"] == "seg-001"
    assert captured_kwargs["lesson_id"] == "lesson-001"
    assert len(captured_kwargs["answers"]) == 1
    assert captured_kwargs["supabase"] is not None


@pytest.mark.unit
def test_http_layer_post_quiz_returns_404_on_missing_session(monkeypatch) -> None:
    """HTTP-layer: HTTPException from service propagates with correct status code."""
    from fastapi import HTTPException

    async def _raise_404(**kwargs):
        raise HTTPException(status_code=404, detail="Session not found")

    monkeypatch.setattr("app.modules.assessment.service.grade_quiz", _raise_404)
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=_VALID_HTTP_PAYLOAD)
    assert resp.status_code == 404


# ── S3-13: Unique attempt constraint 409 tests ────────────────────────────────


def _build_supabase_with_insert_error(error_message: str) -> MagicMock:
    """Build a mock Supabase client where the quiz_attempts insert returns an error.

    Call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT with error).
    4-call side_effect required after S3-12 added the SELECT COUNT query.
    """
    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW

    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}

    count_resp_obj = MagicMock()
    count_resp_obj.count = 0
    count_table_mock = MagicMock()
    count_table_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = count_resp_obj

    error_obj = MagicMock()
    error_obj.__str__ = MagicMock(return_value=error_message)

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = []
    insert_mock.insert.return_value.execute.return_value.error = error_obj

    supabase = MagicMock()
    # 4-call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)
    supabase.table.side_effect = [session_mock, lesson_mock, count_table_mock, insert_mock]
    return supabase


@pytest.mark.unit
async def test_quiz_duplicate_attempt_returns_409(mock_to_thread) -> None:
    """Insert error containing 'duplicate key' → HTTP 409 Conflict.

    When the DB returns a unique-constraint violation, grade_quiz must raise
    HTTPException(409) instead of the generic 500.
    """
    from fastapi import HTTPException
    supabase = _build_supabase_with_insert_error(
        "duplicate key value violates unique constraint \"uq_quiz_attempt\""
    )
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 409
    assert "duplicate" in exc_info.value.detail.lower()


@pytest.mark.unit
async def test_quiz_generic_insert_error_still_returns_500(mock_to_thread) -> None:
    """Insert error NOT containing 'duplicate'/'unique' → HTTP 500 (not 409).

    Non-constraint errors (e.g. connection timeout) must still produce a 500.
    """
    from fastapi import HTTPException
    supabase = _build_supabase_with_insert_error("connection timeout")
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 500


# ── S3-10: Quiz Security Hardening — additional tests ────────────────────────


@pytest.mark.unit
def test_too_many_answers_rejected() -> None:
    """AC 9.1: 51 answers → HTTP 422 (QuizSubmission.answers max_length=50 violated).

    Field(min_length=1, max_length=50) on QuizSubmission.answers is enforced by FastAPI
    before grade_quiz is ever called. 51 items must be rejected at the HTTP layer.
    """
    payload = {
        "session_id": "sess-001",
        "lesson_id": "lesson-001",
        "segment_id": "seg-001",
        "answers": [{"question_id": f"q{i}", "response_index": 0, "response_time_ms": 0} for i in range(51)],
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 422, f"Expected 422 for 51 answers, got {resp.status_code}"


@pytest.mark.unit
def test_answers_at_max_length_accepted(monkeypatch) -> None:
    """AC 9.2: Exactly 50 answers → HTTP 200 (upper boundary is accepted)."""
    from app.modules.assessment.schemas import QuizResult as _QR

    async def _fake_grade_quiz(**kwargs):
        return _QR(
            session_id=kwargs["session_id"],
            score=0.0,
            correct_count=0,
            total_count=50,
            ces_contribution=0.0,
            feedback=[],
        )

    monkeypatch.setattr("app.modules.assessment.service.grade_quiz", _fake_grade_quiz)
    payload = {
        "session_id": "sess-001",
        "lesson_id": "lesson-001",
        "segment_id": "seg-001",
        "answers": [{"question_id": f"q{i}", "response_index": 0, "response_time_ms": 0} for i in range(50)],
    }
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/quiz", json=payload)
    assert resp.status_code == 200, f"Expected 200 for 50 answers, got {resp.status_code}"


@pytest.mark.unit
async def test_response_index_upper_bound_rejected(mock_to_thread) -> None:
    """AC 9.3: response_index=99 for a 4-option question → HTTP 422 (SEC-008).

    _QUESTION_1 has 4 options (indices 0–3). response_index=99 is out of range.
    """
    from fastapi import HTTPException
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=99, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 422
    assert "out of range" in exc_info.value.detail.lower()


@pytest.mark.unit
async def test_response_index_at_max_valid(mock_to_thread) -> None:
    """AC 9.4: response_index=3 for a 4-option question → accepted (last valid index).

    Last valid index for _QUESTION_1 (4 options) is 3. Must not raise 422.
    Correct index is 1, so is_correct=False but the call completes without error.
    """
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=3, response_time_ms=500)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["is_correct"] is False
    assert result.feedback[0]["selected_option"] == "Golgi apparatus"


@pytest.mark.unit
async def test_duplicate_question_id_rejected(mock_to_thread) -> None:
    """AC 9.5: Two QuizAnswer items with the same question_id → HTTP 422 (TQ-007).

    Duplicate submission would double-count the question in total_count and
    incorrectly inflate or deflate the score.
    """
    from fastapi import HTTPException
    supabase = _default_supabase()
    answers = [
        QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000),
        QuizAnswer(question_id="q1", response_index=0, response_time_ms=500),  # duplicate
    ]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 422
    assert "duplicate" in exc_info.value.detail.lower()


@pytest.mark.unit
async def test_insert_error_log_sanitized(mock_to_thread) -> None:
    """AC 9.6: Insert error with embedded newline → logger.error receives sanitized string.

    SEC-009: Log injection prevention. The raw error object may contain newlines from
    stack traces or injected SQL. safe_err must strip them before logging.
    """
    from fastapi import HTTPException
    from unittest.mock import patch as _patch

    malicious_error = "connection failed\nSELECT * FROM secrets\rANOTHER LINE"
    supabase = _build_supabase_with_insert_error(malicious_error)

    with _patch("app.modules.assessment.service.logger") as mock_log:
        with pytest.raises(HTTPException) as exc_info:
            await grade_quiz(
                session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
                answers=[QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)],
                user_id="user-001", supabase=supabase,
            )

    assert exc_info.value.status_code == 500
    assert mock_log.error.called, "logger.error must be called for non-duplicate insert errors"
    # Extract the logged error arg (4th positional arg in format-style log call)
    logged_call = mock_log.error.call_args
    logged_args = logged_call.args if logged_call.args else ()
    # The safe_err is the last positional argument (session_id then safe_err)
    logged_str = " ".join(str(a) for a in logged_args)
    assert "\n" not in logged_str, f"logger.error must not contain newlines; got: {logged_str!r}"
    assert "\r" not in logged_str, f"logger.error must not contain carriage returns; got: {logged_str!r}"
