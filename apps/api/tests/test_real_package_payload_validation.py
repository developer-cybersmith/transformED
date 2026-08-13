"""Validate grade_quiz and grade_teachback against a complete, schema-accurate LessonPackage.

All existing quiz/teachback tests use simplified, non-schema-compliant fixtures:
  lesson_id="lesson-001" (not UUID), segment_id="seg-001" (arbitrary),
  question_id="q1" (arbitrary). Segments also lack title, jargon, and other
  required fields, so score_teachback silently received topic="" and key_concepts=[].

This suite uses a fixture built from lesson_package.schema.json — UUID IDs for
lesson/book/chapter, string IDs for segment/question in the real pipeline format,
and all required fields present.

All tests are @pytest.mark.unit — no real Supabase or OpenAI connections required.
asyncio.to_thread is shimmed to run synchronously so MagicMock chains resolve.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.assessment.prompts import TeachbackScoreResult
from app.modules.assessment.schemas import QuizAnswer, QuizResult, TeachbackResult
from app.modules.assessment.service import grade_quiz, grade_teachback

# ── Schema path ───────────────────────────────────────────────────────────────

def _schema_path() -> pathlib.Path:
    # Resolve to absolute at call time — __file__ may be relative at import time.
    return (
        pathlib.Path(__file__).resolve().parents[3]
        / "packages"
        / "shared"
        / "lesson_package.schema.json"
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


# ── Real LessonPackage fixture ────────────────────────────────────────────────


def _build_real_lesson_package() -> dict:
    """Build a schema-valid LessonPackage with all required fields populated.

    This is the fixture shape that Dev 1's pipeline will produce. Every field
    required by lesson_package.schema.json is present.
    """
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
                        "options": ["Sound waves", "Energy and heat", "Light refraction", "Magnetism"],
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
                        "explanation": "The First Law of Thermodynamics states conservation of energy.",
                        "difficulty": "medium",
                    },
                    {
                        "question_id": _QUESTION_ID_2,
                        "type": "concept_check",
                        "question": "What is entropy a measure of?",
                        "options": ["Order", "Disorder", "Pressure", "Volume"],
                        "correct_index": 1,
                        "explanation": "Entropy is a measure of disorder in a thermodynamic system.",
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


def _build_supabase_quiz(
    session_data=None,
    lesson_data=None,
    count: int = 0,
) -> MagicMock:
    """4-call order: sessions → lessons → quiz_attempts(COUNT) → quiz_attempts(INSERT)."""
    if session_data is None and lesson_data is None:
        session_data = _SESSION_ROW
        lesson_data = {"content": _REAL_PACKAGE}

    mock = MagicMock()

    session_mock = MagicMock()
    sess_exec = session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute
    sess_exec.return_value.data = session_data

    lesson_mock = MagicMock()
    les_exec = lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute
    les_exec.return_value.data = lesson_data

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
    session_data=None,
    lesson_data=None,
    attempt_count: int = 0,
) -> MagicMock:
    """4-call order: sessions → lessons → teachback_attempts(COUNT) → teachback_attempts(INSERT)."""
    if session_data is None and lesson_data is None:
        session_data = _SESSION_ROW
        lesson_data = {"content": _REAL_PACKAGE}

    mock = MagicMock()

    session_mock = MagicMock()
    session_ex = session_mock.select.return_value.eq.return_value.maybe_single.return_value.execute
    session_ex.return_value.data = session_data

    lesson_mock = MagicMock()
    lesson_ex = lesson_mock.select.return_value.eq.return_value.maybe_single.return_value.execute
    lesson_ex.return_value.data = lesson_data

    count_mock = MagicMock()
    count_mock.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = attempt_count

    insert_mock = MagicMock()
    insert_mock.insert.return_value.execute.return_value.data = []
    insert_mock.insert.return_value.execute.return_value.error = None

    mock.table.side_effect = [session_mock, lesson_mock, count_mock, insert_mock]
    return mock


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch) -> None:
    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)


@pytest.fixture(autouse=True)
def _mock_analytics_consent(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.assessment.service.get_analytics_consent",
        AsyncMock(return_value=False),
    )


@pytest.fixture
def mock_to_thread(monkeypatch):
    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


@pytest.fixture
def mock_to_thread_with_llm(monkeypatch):
    """Shim for teachback tests — also stubs OpenAILLMProvider construction."""

    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)
    monkeypatch.setattr(
        "app.modules.assessment.service.OpenAILLMProvider",
        MagicMock(return_value=MagicMock()),
    )


# ── AC4: Schema validation of the fixture itself ──────────────────────────────


@pytest.mark.unit
def test_real_schema_quiz_fixture_validates_against_schema() -> None:
    """AC4: The real-package fixture validates against lesson_package.schema.json.

    If this test fails, the fixture is wrong — not the service code. Fix the
    fixture and re-run before investigating any other test failures.
    """
    import jsonschema

    path = _schema_path()
    assert path.exists(), f"Schema not found at {path}"
    with open(path, encoding="utf-8-sig") as f:
        schema = json.load(f)

    jsonschema.validate(instance=_REAL_PACKAGE, schema=schema)


# ── AC1: Quiz submission with real-schema package succeeds ────────────────────


@pytest.mark.unit
async def test_quiz_with_real_package_succeeds(mock_to_thread) -> None:
    """AC1: grade_quiz processes a schema-valid LessonPackage without error.

    Validates that UUID lesson_id, namespaced question_ids (seg-0-q-0 format),
    and a full-schema segment structure do not cause KeyError or 422/404/500.
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
    assert result.correct_count == 2
    assert result.total_count == 2
    assert result.score == pytest.approx(100.0)
    assert len(result.feedback) == 2
    feedback_ids = {f["question_id"] for f in result.feedback}
    assert _QUESTION_ID_0 in feedback_ids
    assert _QUESTION_ID_1 in feedback_ids


# ── AC2: Teachback scorer receives title + jargon from real segment ───────────


@pytest.mark.unit
async def test_teachback_receives_title_and_jargon_from_real_segment(
    mock_to_thread_with_llm, monkeypatch
) -> None:
    """AC2: grade_teachback passes segment.title and jargon[].term to score_teachback.

    Simplified fixtures had no title or jargon, so the scorer was silently
    called with topic='' and key_concepts=[]. With the real-schema fixture,
    the scorer must receive the actual segment title and jargon terms.
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
        response_text="Thermodynamics studies energy and heat transfer between systems.",
        user_id=_USER_UUID_A,
        supabase=supabase,
    )

    assert isinstance(result, TeachbackResult)
    assert captured["topic"] == "What is Thermodynamics?"
    assert "entropy" in captured["key_concepts"]
    assert "enthalpy" in captured["key_concepts"]
    assert len(captured["key_concepts"]) == 2


# ── AC3: Session chain resolves correctly with UUID lesson_id ─────────────────


@pytest.mark.unit
async def test_session_chain_uuid_ids_quiz_and_teachback(mock_to_thread) -> None:
    """AC3: grade_quiz resolves a session whose lesson_id is a UUID without 404.

    # MOCK-CONTRACT: Tests service-layer session lookup. Router-level session
    # creation (create_session) is tested in test_session_endpoint.py.
    """
    supabase = _build_supabase_quiz(
        session_data={
            "session_id": _SESSION_UUID,
            "user_id": _USER_UUID_A,
            "lesson_id": _LESSON_UUID,
        },
        lesson_data={"content": _REAL_PACKAGE},
    )
    answers = [QuizAnswer(question_id=_QUESTION_ID_0, response_index=0, response_time_ms=1000)]
    result = await grade_quiz(
        session_id=_SESSION_UUID,
        lesson_id=_LESSON_UUID,
        segment_id=_SEGMENT_ID,
        answers=answers,
        user_id=_USER_UUID_A,
        supabase=supabase,
    )
    # If session lookup fails, HTTPException 404 propagates and we never reach here.
    assert result.total_count == 1


# ── AC5: Segment not found includes UUID lesson_id in error detail ────────────


@pytest.mark.unit
async def test_segment_not_found_uuid_lesson_id_in_error(mock_to_thread) -> None:
    """AC5: When segment_id is absent from the real package, 404 detail contains the UUID lesson_id."""
    from fastapi import HTTPException

    supabase = _build_supabase_quiz(
        session_data=_SESSION_ROW,
        lesson_data={"content": _REAL_PACKAGE},
    )
    answers = [QuizAnswer(question_id=_QUESTION_ID_0, response_index=1, response_time_ms=500)]

    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id=_SESSION_UUID,
            lesson_id=_LESSON_UUID,
            segment_id="seg-99-does-not-exist",
            answers=answers,
            user_id=_USER_UUID_A,
            supabase=supabase,
        )

    assert exc_info.value.status_code == 404
    assert _LESSON_UUID in str(exc_info.value.detail)


# ── AC6: IDOR guard works with UUID user IDs ──────────────────────────────────


@pytest.mark.unit
async def test_idor_guard_uuid_user_ids(mock_to_thread) -> None:
    """AC6: A different UUID user cannot access a session owned by user_A (SEC-006 — 404)."""
    from fastapi import HTTPException

    supabase = _build_supabase_quiz(
        session_data={
            "session_id": _SESSION_UUID,
            "user_id": _USER_UUID_A,
            "lesson_id": _LESSON_UUID,
        },
        lesson_data={"content": _REAL_PACKAGE},
    )
    answers = [QuizAnswer(question_id=_QUESTION_ID_0, response_index=1, response_time_ms=500)]

    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id=_SESSION_UUID,
            lesson_id=_LESSON_UUID,
            segment_id=_SEGMENT_ID,
            answers=answers,
            user_id=_USER_UUID_B,  # Different UUID user — IDOR attempt
            supabase=supabase,
        )

    assert exc_info.value.status_code == 404


# ── AC7: Wrong question_id (not in real segment) returns 422 ──────────────────


@pytest.mark.unit
async def test_wrong_question_id_returns_422(mock_to_thread) -> None:
    """AC7: A question_id not in the real segment's quiz array returns HTTP 422."""
    from fastapi import HTTPException

    supabase = _build_supabase_quiz()
    answers = [
        QuizAnswer(question_id="seg-99-q-99", response_index=0, response_time_ms=500),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id=_SESSION_UUID,
            lesson_id=_LESSON_UUID,
            segment_id=_SEGMENT_ID,
            answers=answers,
            user_id=_USER_UUID_A,
            supabase=supabase,
        )

    assert exc_info.value.status_code == 422


# ── AC8: Empty jargon — teachback scorer receives key_concepts=[] without error ─


@pytest.mark.unit
async def test_empty_jargon_teachback_graceful(mock_to_thread_with_llm, monkeypatch) -> None:
    """AC8: Segment with empty jargon passes key_concepts=[] to scorer — no error or KeyError."""
    captured: dict = {}

    async def _spy(*args, **kwargs):
        captured["key_concepts"] = kwargs.get("key_concepts", "MISSING")
        return _MOCK_TB_RESULT

    monkeypatch.setattr("app.modules.assessment.service.score_teachback", _spy)

    pkg_no_jargon = _build_real_lesson_package()
    pkg_no_jargon["segments"][0]["jargon"] = []

    supabase = _build_supabase_teachback(
        session_data=_SESSION_ROW,
        lesson_data={"content": pkg_no_jargon},
    )
    result = await grade_teachback(
        session_id=_SESSION_UUID,
        lesson_id=_LESSON_UUID,
        segment_id=_SEGMENT_ID,
        response_text="Thermodynamics is about heat and energy.",
        user_id=_USER_UUID_A,
        supabase=supabase,
    )

    assert isinstance(result, TeachbackResult)
    assert captured["key_concepts"] == []


# ── AC9: response_index >= 4 (real schema: exactly 4 options) returns 422 ─────


@pytest.mark.unit
async def test_response_index_out_of_range_422(mock_to_thread) -> None:
    """AC9: response_index=4 against a 4-option question (valid range 0-3) returns HTTP 422."""
    from fastapi import HTTPException

    supabase = _build_supabase_quiz()
    answers = [
        QuizAnswer(question_id=_QUESTION_ID_0, response_index=4, response_time_ms=500),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await grade_quiz(
            session_id=_SESSION_UUID,
            lesson_id=_LESSON_UUID,
            segment_id=_SEGMENT_ID,
            answers=answers,
            user_id=_USER_UUID_A,
            supabase=supabase,
        )

    assert exc_info.value.status_code == 422
    assert "out of range" in str(exc_info.value.detail).lower()
