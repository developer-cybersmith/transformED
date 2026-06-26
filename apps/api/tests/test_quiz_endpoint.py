"""Unit tests for quiz grading service (grade_quiz).

All tests are @pytest.mark.unit — no real Supabase connection required.
asyncio.to_thread is shimmed to run synchronously so MagicMock chain works correctly.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.modules.assessment.router import QuizAnswer
from app.modules.assessment.service import grade_quiz


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

    All happy-path tests reach ces_contribution = quiz_accuracy * settings.ces_weight_quiz,
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
) -> MagicMock:
    """Build a mock Supabase client with ordered call side effects.

    Call order matches grade_quiz internals: sessions → lessons → quiz_attempts insert.
    Pass session_data=None to simulate session not found.
    Pass lesson_data with content=None to simulate lesson without content.
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

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = insert_data or []

    mock.table.side_effect = [session_mock, lesson_mock, insert_mock]
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
    """2/2 correct → score == 100.0."""
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
    assert result.ces_contribution == pytest.approx(1.0 * 0.35)


@pytest.mark.unit
async def test_response_time_ms_written_to_db(mock_to_thread) -> None:
    """response_time_ms from each QuizAnswer is included in the DB insert row."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}

    def _capture(rows):
        captured_rows.extend(rows)
        m = MagicMock()
        m.execute.return_value.data = []
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    supabase.table.side_effect = [session_mock, lesson_mock, insert_mock]

    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=3750)]
    await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert len(captured_rows) == 1
    assert captured_rows[0]["response_time_ms"] == 3750


@pytest.mark.unit
async def test_attempt_number_written_to_db(mock_to_thread) -> None:
    """attempt_number parameter is written to each quiz_attempts row."""
    captured_rows: list = []

    session_mock = MagicMock()
    session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = _SESSION_ROW
    lesson_mock = MagicMock()
    lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"content": _LESSON_CONTENT}

    def _capture(rows):
        captured_rows.extend(rows)
        m = MagicMock()
        m.execute.return_value.data = []
        return m

    insert_mock = MagicMock()
    insert_mock.insert.side_effect = _capture
    supabase = MagicMock()
    supabase.table.side_effect = [session_mock, lesson_mock, insert_mock]

    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, attempt_number=2, user_id="user-001", supabase=supabase,
    )
    assert captured_rows[0]["attempt_number"] == 2


@pytest.mark.unit
async def test_feedback_contains_explanation(mock_to_thread) -> None:
    """Each feedback item includes the QuizQuestion explanation text."""
    supabase = _default_supabase()
    answers = [QuizAnswer(question_id="q1", response_index=0, response_time_ms=1000)]
    result = await grade_quiz(
        session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
        answers=answers, user_id="user-001", supabase=supabase,
    )
    assert result.feedback[0]["explanation"] == _QUESTION_1["explanation"]


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
async def test_raises_403_when_session_belongs_to_other_user(mock_to_thread) -> None:
    """session.user_id != request user_id → HTTP 403."""
    from fastapi import HTTPException
    other_session = {"session_id": "sess-001", "user_id": "other-user", "lesson_id": "lesson-001"}
    supabase = _build_supabase(session_data=other_session, lesson_data={"content": _LESSON_CONTENT})
    answers = [QuizAnswer(question_id="q1", response_index=1, response_time_ms=1000)]
    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id="sess-001", lesson_id="lesson-001", segment_id="seg-001",
            answers=answers, user_id="user-001", supabase=supabase,
        )
    assert exc_info.value.status_code == 403


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
