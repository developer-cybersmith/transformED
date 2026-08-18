"""End-to-end session flow validation with real UUID data (Demo T16).

Validates the full assessment session lifecycle with schema-accurate UUIDs:
  create_session → grade_quiz → grade_teachback → get_session_report

T15 validated grade_quiz and grade_teachback in isolation. T16 validates:
  - create_session correctly mints a DB UUID session_id (not a client value)
  - The UUID session_id chains correctly into grade_quiz and grade_teachback
  - get_session_report aggregates quiz + teachback data and discloses the correct
    CES formula (full_5_signal vs teachback_redistributed_4_signal)
  - IDOR guards on both create_session and get_session_report return 404, not 403

All tests are @pytest.mark.unit — no real Supabase, Redis, or OpenAI connections.
asyncio.to_thread is shimmed to run synchronously so MagicMock chains resolve.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.assessment.prompts import TeachbackScoreResult
from app.modules.assessment.schemas import QuizAnswer, QuizResult, TeachbackResult
from app.modules.assessment.service import (
    create_session,
    get_session_report,
    grade_quiz,
    grade_teachback,
)

# ── Real UUID IDs matching real pipeline output ───────────────────────────────

_LESSON_UUID = "550e8400-e29b-41d4-a716-446655440000"
_BOOK_UUID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
_CHAPTER_UUID = "6ba7b812-9dad-11d1-80b4-00c04fd430c8"
_USER_UUID_A = "a0000000-0000-0000-0000-000000000001"
_USER_UUID_B = "b0000000-0000-0000-0000-000000000002"
_SESSION_UUID = "c0000000-0000-0000-0000-000000000003"
_SEGMENT_ID = "seg-0-intro-thermodynamics"
_QUESTION_ID_0 = "seg-0-q-0"
_QUESTION_ID_1 = "seg-0-q-1"
_QUESTION_ID_2 = "seg-0-q-2"


# ── Real LessonPackage fixture (duplicated from T15 — T15 not yet on main) ───


def _build_real_lesson_package() -> dict:
    """Build a schema-valid LessonPackage with all required fields populated."""
    return {
        "lesson_id": _LESSON_UUID,
        "book_id": _BOOK_UUID,
        "chapter_id": _CHAPTER_UUID,
        "created_at": "2026-08-13T10:00:00Z",
        "metadata": {
            "title": "Introduction to Thermodynamics",
            "subject": "Physics",
            "total_segments": 1,
            "estimated_duration_mins": 15.0,
            "complexity_level": "medium",
            "tier": "T2",
        },
        "segments": [
            {
                "segment_id": _SEGMENT_ID,
                "segment_index": 0,
                "title": "What is Thermodynamics?",
                "summary": "An introduction to energy, heat, and work.",
                "complexity": {
                    "level": "low",
                    "cognitive_load": "low",
                    "abstraction_level": "concrete",
                    "prerequisite_concepts": ["energy", "force"],
                    "narration_style": "conversational",
                    "quiz_difficulty": "easy",
                    "intervention_sensitivity": 0.3,
                },
                "slides": [
                    {
                        "slide_id": "s0",
                        "title": "What is Thermodynamics?",
                        "bullets": [
                            "Study of energy, heat, and work",
                            "Applies to all natural systems",
                        ],
                        "image_url": None,
                        "fallback_image_url": None,
                    }
                ],
                "narration": {
                    "script": "Thermodynamics is the study of energy and heat transfer.",
                    "audio_url": "https://cdn.hieiq.ai/audio/seg-0.mp3",
                    "audio_provider": "sarvam",
                    "timestamps": [{"slide_id": "s0", "start_ms": 0, "end_ms": 8000}],
                },
                "quiz": [
                    {
                        "question_id": _QUESTION_ID_0,
                        "type": "mcq",
                        "question": "What does thermodynamics study?",
                        "options": [
                            "Sound waves",
                            "Energy and heat",
                            "Light refraction",
                            "Magnetism",
                        ],
                        "correct_index": 1,
                        "explanation": "Thermodynamics is the study of energy, heat, and work.",
                        "difficulty": "easy",
                    },
                    {
                        "question_id": _QUESTION_ID_1,
                        "type": "mcq",
                        "question": "Which law says energy cannot be created or destroyed?",
                        "options": ["Zeroth law", "First law", "Second law", "Third law"],
                        "correct_index": 1,
                        "explanation": (
                            "The First Law of Thermodynamics states conservation of energy."
                        ),
                        "difficulty": "medium",
                    },
                    {
                        "question_id": _QUESTION_ID_2,
                        "type": "concept_check",
                        "question": "What is entropy a measure of?",
                        "options": ["Order", "Disorder", "Pressure", "Volume"],
                        "correct_index": 1,
                        "explanation": (
                            "Entropy is a measure of disorder in a thermodynamic system."
                        ),
                        "difficulty": "hard",
                    },
                ],
                "teachback_prompt": "Explain what thermodynamics is and why it matters.",
                "jargon": [
                    {"term": "entropy", "definition": "Measure of disorder in a system."},
                    {"term": "enthalpy", "definition": "Total heat content of a system."},
                ],
                "interventions": {
                    "distraction": [
                        "Let's refocus on thermodynamics.",
                        "Stay with me!",
                        "Almost there.",
                    ],
                    "confusion": [
                        "Let me re-explain.",
                        "Take a breath.",
                        "Here is the key idea again.",
                    ],
                    "fatigue": ["Take a short break.", "Stretch!", "You are doing great."],
                },
            }
        ],
        "glossary": [
            {"term": "energy", "definition": "The capacity to do work."},
        ],
    }


_REAL_PACKAGE = _build_real_lesson_package()

_SESSION_ROW: dict = {
    "session_id": _SESSION_UUID,
    "user_id": _USER_UUID_A,
    "lesson_id": _LESSON_UUID,
}

_SESSION_ROW_FULL: dict = {
    "session_id": _SESSION_UUID,
    "user_id": _USER_UUID_A,
    "lesson_id": _LESSON_UUID,
    "ces_final": 72.5,
    "started_at": "2026-08-13T10:00:00+00:00",
    "ended_at": "2026-08-13T10:15:00+00:00",
}

_MOCK_TB_RESULT = TeachbackScoreResult(
    score=80,
    accuracy_score=85,
    completeness_score=75,
    clarity_score=80,
    praise="Good explanation of thermodynamics.",
    correction="Missed the relationship between entropy and disorder.",
    concepts_hit=["entropy"],
    concepts_missed=["enthalpy"],
)


# ── Supabase mock builders ────────────────────────────────────────────────────


def _build_supabase_create_session(
    lesson_row: dict | None = None,
    lesson_found: bool = True,
    insert_row: list | None = None,
) -> MagicMock:
    """2-call order: lessons(select ownership) → sessions(insert).

    lesson_found=False simulates lesson not found (returns None → 404).
    lesson_row overrides the default lesson record when lesson_found=True.
    """
    lesson_data: dict | None = (
        (lesson_row or {"lesson_id": _LESSON_UUID, "user_id": _USER_UUID_A})
        if lesson_found
        else None
    )
    insert_data: list = insert_row or [
        {
            "session_id": _SESSION_UUID,
            "lesson_id": _LESSON_UUID,
            "started_at": "2026-08-13T10:00:00+00:00",
        }
    ]

    mock = MagicMock()

    lessons_mock = MagicMock()
    lessons_chain = lessons_mock.select.return_value.eq.return_value.maybe_single.return_value
    lessons_chain.execute.return_value.data = lesson_data

    sessions_mock = MagicMock()
    sessions_mock.insert.return_value.execute.return_value.data = insert_data

    mock.table.side_effect = [lessons_mock, sessions_mock]
    return mock


def _build_supabase_quiz(
    session_data: dict | None = None,
    lesson_data: dict | None = None,
    count: int = 0,
) -> MagicMock:
    """4-call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)."""
    if session_data is None:
        session_data = _SESSION_ROW
    if lesson_data is None:
        lesson_data = {"content": _REAL_PACKAGE}

    mock = MagicMock()

    session_mock = MagicMock()
    session_chain = session_mock.select.return_value.eq.return_value.maybe_single.return_value
    session_chain.execute.return_value.data = session_data

    lesson_mock = MagicMock()
    lesson_chain = lesson_mock.select.return_value.eq.return_value.maybe_single.return_value
    lesson_chain.execute.return_value.data = lesson_data

    count_resp = MagicMock()
    count_resp.count = count
    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value = count_resp

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = []
    insert_mock.insert.return_value.execute.return_value.error = None

    mock.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]
    return mock


def _build_supabase_teachback(
    session_data: dict | None = None,
    lesson_data: dict | None = None,
    attempt_count: int = 0,
) -> MagicMock:
    """4-call order: sessions → lessons → teachback_attempts(COUNT) → teachback_attempts(INSERT)."""
    if session_data is None:
        session_data = _SESSION_ROW
    if lesson_data is None:
        lesson_data = {"content": _REAL_PACKAGE}

    mock = MagicMock()

    session_mock = MagicMock()
    session_chain = session_mock.select.return_value.eq.return_value.maybe_single.return_value
    session_chain.execute.return_value.data = session_data

    lesson_mock = MagicMock()
    lesson_chain = lesson_mock.select.return_value.eq.return_value.maybe_single.return_value
    lesson_chain.execute.return_value.data = lesson_data

    count_mock = MagicMock()
    count_chain = count_mock.select.return_value.eq.return_value.eq.return_value
    count_chain.execute.return_value.count = attempt_count

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = []
    insert_mock.insert.return_value.execute.return_value.error = None

    mock.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]
    return mock


def _build_supabase_session_report(
    session_row: dict | None = None,
    quiz_rows: list | None = None,
    teachback_rows: list | None = None,
    interventions_count: int = 1,
    dna_data: dict | None = None,
) -> MagicMock:
    """7-call order for get_session_report:

    sessions → lessons(tier) → quiz_attempts → teachback_attempts →
    session_events(interventions) → learner_dna → session_events(dna_update)
    """
    if session_row is None:
        session_row = _SESSION_ROW_FULL
    if quiz_rows is None:
        quiz_rows = [{"is_correct": True}, {"is_correct": False}, {"is_correct": True}]
    if teachback_rows is None:
        teachback_rows = [{"score": 80.0}]

    mock = MagicMock()

    # 1 — sessions (maybe_single)
    sessions_mock = MagicMock()
    sessions_chain = sessions_mock.select.return_value.eq.return_value.maybe_single.return_value
    sessions_chain.execute.return_value.data = session_row

    # 2 — lessons (tier, maybe_single)
    lessons_mock = MagicMock()
    lessons_chain = lessons_mock.select.return_value.eq.return_value.maybe_single.return_value
    lessons_chain.execute.return_value.data = {"tier": "T2"}

    # 3 — quiz_attempts (.select().eq().limit().execute())
    quiz_mock = MagicMock()
    quiz_chain = quiz_mock.select.return_value.eq.return_value.limit.return_value
    quiz_chain.execute.return_value.data = quiz_rows

    # 4 — teachback_attempts (.select().eq().order().limit().execute()) — Story 2-48
    tb_mock = MagicMock()
    _tb_lim = tb_mock.select.return_value.eq.return_value.order.return_value.limit.return_value
    _tb_lim.execute.return_value.data = teachback_rows

    # 5 — session_events (interventions, count="exact": .select().eq().eq().execute())
    interventions_resp = MagicMock()
    interventions_resp.count = interventions_count
    interventions_mock = MagicMock()
    interventions_chain = interventions_mock.select.return_value.eq.return_value.eq.return_value
    interventions_chain.execute.return_value = interventions_resp

    # 6 — session_events raw intervention rows (Story 2-46/S3-05, .order().limit() bounded)
    intervention_rows_mock = MagicMock()
    _ir_eq = intervention_rows_mock.select.return_value.eq.return_value.eq.return_value
    intervention_rows_chain = _ir_eq.order.return_value.limit.return_value
    intervention_rows_chain.execute.return_value.data = []

    # 7 — learner_dna (maybe_single)
    dna_mock = MagicMock()
    dna_chain = dna_mock.select.return_value.eq.return_value.maybe_single.return_value
    dna_chain.execute.return_value.data = dna_data

    # 8 — session_events (dna_update: .select().eq().eq().limit().execute())
    dna_events_mock = MagicMock()
    dna_events_chain = (
        dna_events_mock.select.return_value.eq.return_value.eq.return_value.limit.return_value
    )
    dna_events_chain.execute.return_value.data = []

    mock.table.side_effect = [
        sessions_mock,
        lessons_mock,
        quiz_mock,
        tb_mock,
        interventions_mock,
        intervention_rows_mock,
        dna_mock,
        dna_events_mock,
    ]
    return mock


# ── Shared autouse fixtures ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    """Mock all 5 CES weight settings so _build_ces_breakdown computes correctly."""
    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    mock_settings.ces_weight_behavioral = 0.20
    mock_settings.ces_weight_head_pose = 0.12
    mock_settings.ces_weight_blink = 0.08
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)


@pytest.fixture(autouse=True)
def _mock_analytics_consent(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.assessment.service.get_analytics_consent",
        AsyncMock(return_value=False),
    )


@pytest.fixture
def mock_to_thread(monkeypatch):
    """Shim asyncio.to_thread to run synchronously so MagicMock chains resolve."""

    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


@pytest.fixture
def mock_to_thread_with_llm(monkeypatch):
    """Shim + stub OpenAILLMProvider for teachback tests."""

    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)
    monkeypatch.setattr(
        "app.modules.assessment.service.OpenAILLMProvider",
        MagicMock(return_value=MagicMock()),
    )


# ── AC1: create_session returns DB-minted UUID session_id ─────────────────────


@pytest.mark.unit
async def test_create_session_returns_db_minted_uuid(mock_to_thread) -> None:
    """AC1: create_session mints the session_id from the DB, not from the client.

    The returned session_id must equal the UUID from sessions.insert, not the
    lesson_id or any caller-supplied value. The response also carries lesson_id
    and started_at.
    """
    supabase = _build_supabase_create_session()
    result = await create_session(
        lesson_id=_LESSON_UUID,
        user_id=_USER_UUID_A,
        supabase=supabase,
    )

    assert result["session_id"] == _SESSION_UUID
    assert result["lesson_id"] == _LESSON_UUID
    assert result["started_at"] is not None
    assert result["session_id"] != _LESSON_UUID


# ── AC2: create_session IDOR guard ────────────────────────────────────────────


@pytest.mark.unit
async def test_create_session_idor_guard_returns_404(mock_to_thread) -> None:
    """AC2: create_session returns 404 when lesson is owned by a different user.

    SEC-006: no 403 to prevent enumeration. Both "not found" and "wrong owner"
    return the same 404 with the same message.
    """
    from fastapi import HTTPException

    supabase = _build_supabase_create_session(
        lesson_row={"lesson_id": _LESSON_UUID, "user_id": _USER_UUID_A},
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_session(
            lesson_id=_LESSON_UUID,
            user_id=_USER_UUID_B,
            supabase=supabase,
        )

    assert exc_info.value.status_code == 404


# ── AC3: create_session 404 on non-existent lesson ───────────────────────────


@pytest.mark.unit
async def test_create_session_missing_lesson_returns_404(mock_to_thread) -> None:
    """AC3: create_session returns 404 when the lesson does not exist at all."""
    from fastapi import HTTPException

    supabase = _build_supabase_create_session(lesson_found=False)
    with pytest.raises(HTTPException) as exc_info:
        await create_session(
            lesson_id=_LESSON_UUID,
            user_id=_USER_UUID_A,
            supabase=supabase,
        )

    assert exc_info.value.status_code == 404


# ── AC4: grade_quiz with UUID session from create_session (full chain) ─────────


@pytest.mark.unit
async def test_grade_quiz_with_uuid_session_succeeds(mock_to_thread) -> None:
    """AC4: grade_quiz succeeds when session_id is the DB-minted UUID from create_session.

    Validates that the UUID session_id (_SESSION_UUID) that create_session would
    return is accepted by grade_quiz without 404 or 422, and that correct_count
    reflects the real quiz fixture's answers.
    """
    supabase = _build_supabase_quiz()
    answers = [
        QuizAnswer(question_id=_QUESTION_ID_0, response_index=1, response_time_ms=1500),
        QuizAnswer(question_id=_QUESTION_ID_1, response_index=1, response_time_ms=2000),
    ]
    result = await grade_quiz(
        session_id=_SESSION_UUID,
        lesson_id=_LESSON_UUID,
        segment_id=_SEGMENT_ID,
        answers=answers,
        user_id=_USER_UUID_A,
        supabase=supabase,
    )

    assert isinstance(result, QuizResult)
    assert result.correct_count >= 1
    assert result.total_count == 2
    assert result.score == pytest.approx(100.0)


# ── AC5: grade_teachback scorer receives real title + jargon via UUID session ──


@pytest.mark.unit
async def test_grade_teachback_scorer_receives_title_and_jargon(
    mock_to_thread_with_llm, monkeypatch
) -> None:
    """AC5: grade_teachback passes segment.title and jargon[].term when session_id is a UUID.

    The UUID session_id path must resolve the correct segment from the real package.
    score_teachback must receive the segment's title ("What is Thermodynamics?")
    and both jargon terms ("entropy", "enthalpy"), not empty strings.
    """
    captured: dict = {}

    async def _spy_score_teachback(*, topic, key_concepts, response_text, provider):
        captured["topic"] = topic
        captured["key_concepts"] = key_concepts
        return _MOCK_TB_RESULT

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _spy_score_teachback)

    supabase = _build_supabase_teachback()
    result = await grade_teachback(
        session_id=_SESSION_UUID,
        lesson_id=_LESSON_UUID,
        segment_id=_SEGMENT_ID,
        response_text="Thermodynamics studies energy, heat, and work in physical systems.",
        user_id=_USER_UUID_A,
        supabase=supabase,
    )

    assert isinstance(result, TeachbackResult)
    assert captured["topic"] == "What is Thermodynamics?"
    assert "entropy" in captured["key_concepts"]
    assert "enthalpy" in captured["key_concepts"]
    assert len(captured["key_concepts"]) == 2


# ── AC6: get_session_report aggregates quiz + teachback (full 5-signal formula) ─


@pytest.mark.unit
async def test_get_session_report_full_5_signal(mock_to_thread) -> None:
    """AC6: get_session_report returns full_5_signal when both quiz and teachback present.

    Verifies that quiz_score and teachback_score are both non-None, the formula
    disclosure is "full_5_signal", signal_coverage is 5, and ces_breakdown has
    the expected 5 keys.
    """
    from app.modules.assessment.router import SessionReport

    supabase = _build_supabase_session_report()
    result = await get_session_report(
        session_id=_SESSION_UUID,
        user_id=_USER_UUID_A,
        supabase=supabase,
        redis=None,
    )

    assert isinstance(result, SessionReport)
    assert result.quiz_score is not None
    assert result.teachback_score is not None
    assert result.formula_applied == "full_5_signal"
    assert result.signal_coverage == 5
    assert "quiz" in result.ces_breakdown
    assert "teachback" in result.ces_breakdown
    assert "behavioral" in result.ces_breakdown
    assert result.quiz_total_questions == 3
    assert result.quiz_correct_count == 2
    assert result.interventions_count == 1


# ── AC7: get_session_report with no teachback → teachback_redistributed formula ─


@pytest.mark.unit
async def test_get_session_report_no_teachback_uses_redistributed_formula(
    mock_to_thread,
) -> None:
    """AC7: teachback_score is None when no teachback_attempts exist.

    formula_applied must be "teachback_redistributed_4_signal" and signal_coverage
    must be 4, disclosing that the 5-signal formula could not be applied.
    """
    from app.modules.assessment.router import SessionReport

    supabase = _build_supabase_session_report(teachback_rows=[])
    result = await get_session_report(
        session_id=_SESSION_UUID,
        user_id=_USER_UUID_A,
        supabase=supabase,
        redis=None,
    )

    assert isinstance(result, SessionReport)
    assert result.teachback_score is None
    assert result.formula_applied == "teachback_redistributed_4_signal"
    assert result.signal_coverage == 4


# ── AC8: get_session_report with no quiz → quiz_score None ───────────────────


@pytest.mark.unit
async def test_get_session_report_no_quiz_returns_none_quiz_score(mock_to_thread) -> None:
    """AC8: quiz_score is None and quiz_total_questions is 0 when no quiz_attempts exist."""
    from app.modules.assessment.router import SessionReport

    supabase = _build_supabase_session_report(quiz_rows=[], teachback_rows=[])
    result = await get_session_report(
        session_id=_SESSION_UUID,
        user_id=_USER_UUID_A,
        supabase=supabase,
        redis=None,
    )

    assert isinstance(result, SessionReport)
    assert result.quiz_score is None
    assert result.quiz_total_questions == 0


# ── AC9: get_session_report IDOR guard ────────────────────────────────────────


@pytest.mark.unit
async def test_get_session_report_idor_guard_returns_404(mock_to_thread) -> None:
    """AC9: get_session_report returns 404 when session belongs to a different user.

    SEC-006: no 403 to prevent enumeration. User B accessing user A's session
    receives the same 404 as "session not found".
    """
    from fastapi import HTTPException

    session_row_owned_by_a = {**_SESSION_ROW_FULL, "user_id": _USER_UUID_A}
    supabase = _build_supabase_session_report(session_row=session_row_owned_by_a)
    with pytest.raises(HTTPException) as exc_info:
        await get_session_report(
            session_id=_SESSION_UUID,
            user_id=_USER_UUID_B,
            supabase=supabase,
            redis=None,
        )

    assert exc_info.value.status_code == 404
