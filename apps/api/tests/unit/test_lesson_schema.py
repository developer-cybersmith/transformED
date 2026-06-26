"""
Unit tests: Pydantic LessonPackage models ↔ JSON schema round-trip.

Validates that the Python models in app.schemas.lesson stay in sync with
the authoritative JSON schema at packages/shared/lesson_package.schema.json.
"""

import json
from pathlib import Path
from uuid import UUID

import jsonschema
import pytest
from pydantic import ValidationError

from app.schemas import (
    GlossaryEntry,
    JargonEntry,
    LessonMetadata,
    LessonPackage,
    LessonRecord,
    Narration,
    NarrationTimestamp,
    QuizQuestion,
    Segment,
    SegmentComplexity,
    SegmentInterventions,
    Slide,
)

SCHEMA_PATH = Path(__file__).parents[4] / "packages/shared/lesson_package.schema.json"

# ---------------------------------------------------------------------------
# Minimal valid fixture — reused across tests
# ---------------------------------------------------------------------------

MINIMAL_PACKAGE_DICT = {
    "lesson_id": "00000000-0000-0000-0000-000000000001",
    "book_id": "00000000-0000-0000-0000-000000000002",
    "chapter_id": "00000000-0000-0000-0000-000000000003",
    "created_at": "2026-06-25T00:00:00Z",
    "metadata": {
        "title": "Test Lesson",
        "subject": "Testing",
        "total_segments": 1,
        "estimated_duration_mins": 5.0,
        "complexity_level": "medium",
    },
    "segments": [
        {
            "segment_id": "seg_1",
            "segment_index": 0,
            "title": "Segment 1",
            "summary": "Summary text",
            "complexity": {
                "level": "medium",
                "cognitive_load": "moderate",
                "abstraction_level": "concrete",
                "prerequisite_concepts": [],
                "narration_style": "conversational",
                "quiz_difficulty": "medium",
                "intervention_sensitivity": 0.5,
            },
            "slides": [
                {
                    "slide_id": "sl_1",
                    "title": "Slide 1",
                    "bullets": ["Point 1"],
                    "image_url": None,
                    "fallback_image_url": None,
                }
            ],
            "narration": {
                "script": "Hello world.",
                "audio_url": "https://example.com/audio.mp3",
                "audio_provider": "azure",
                "timestamps": [{"slide_id": "sl_1", "start_ms": 0, "end_ms": 3000}],
            },
            "quiz": [],
            "teachback_prompt": "Explain in your own words.",
            "jargon": [],
            "interventions": {
                "distraction": ["A", "B", "C"],
                "confusion": ["D", "E", "F"],
                "fatigue": ["G", "H", "I"],
            },
        }
    ],
    "glossary": [],
}


# ---------------------------------------------------------------------------
# JSON schema round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lesson_package_validates_against_json_schema() -> None:
    """model_dump_json → JSON schema validation must pass."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    package = LessonPackage.model_validate(MINIMAL_PACKAGE_DICT)
    jsonschema.validate(
        instance=json.loads(package.model_dump_json()),
        schema=schema,
    )


@pytest.mark.unit
def test_lesson_package_round_trip() -> None:
    """model_dump → model_validate must be identity."""
    package = LessonPackage.model_validate(MINIMAL_PACKAGE_DICT)
    dumped = package.model_dump(mode="json")
    restored = LessonPackage.model_validate(dumped)
    assert package == restored


# ---------------------------------------------------------------------------
# LessonMetadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lesson_metadata_total_segments_min() -> None:
    with pytest.raises(ValidationError):
        LessonMetadata(
            title="T", subject="S", total_segments=0,
            estimated_duration_mins=1.0, complexity_level="low",
        )


@pytest.mark.unit
def test_lesson_metadata_duration_min() -> None:
    with pytest.raises(ValidationError):
        LessonMetadata(
            title="T", subject="S", total_segments=1,
            estimated_duration_mins=-1.0, complexity_level="low",
        )


@pytest.mark.unit
def test_lesson_metadata_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        LessonMetadata(
            title="T", subject="S", total_segments=1,
            estimated_duration_mins=1.0, complexity_level="low",
            unexpected_field="x",
        )


# ---------------------------------------------------------------------------
# SegmentComplexity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_segment_complexity_intervention_sensitivity_bounds() -> None:
    base = {
        "level": "low",
        "cognitive_load": "low",
        "abstraction_level": "concrete",
        "prerequisite_concepts": [],
        "narration_style": "plain",
        "quiz_difficulty": "easy",
    }
    with pytest.raises(ValidationError):
        SegmentComplexity(**base, intervention_sensitivity=1.1)
    with pytest.raises(ValidationError):
        SegmentComplexity(**base, intervention_sensitivity=-0.1)


@pytest.mark.unit
def test_segment_complexity_level_enum() -> None:
    with pytest.raises(ValidationError):
        SegmentComplexity(
            level="extreme",
            cognitive_load="x", abstraction_level="x",
            prerequisite_concepts=[], narration_style="x",
            quiz_difficulty="x", intervention_sensitivity=0.5,
        )


# ---------------------------------------------------------------------------
# QuizQuestion
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_quiz_question_requires_four_options() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            question_id="q1", type="mcq", question="Q?",
            options=["A", "B", "C"],  # only 3
            correct_index=0, explanation="E", difficulty="easy",
        )


@pytest.mark.unit
def test_quiz_question_valid() -> None:
    q = QuizQuestion(
        question_id="q1", type="mcq", question="Q?",
        options=["A", "B", "C", "D"],
        correct_index=0, explanation="E", difficulty="easy",
    )
    assert q.type == "mcq"


# ---------------------------------------------------------------------------
# SegmentInterventions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_segment_interventions_require_exactly_three() -> None:
    with pytest.raises(ValidationError):
        SegmentInterventions(
            distraction=["A", "B"],  # only 2
            confusion=["D", "E", "F"],
            fatigue=["G", "H", "I"],
        )
    with pytest.raises(ValidationError):
        SegmentInterventions(
            distraction=["A", "B", "C", "D"],  # 4 — exceeds max
            confusion=["D", "E", "F"],
            fatigue=["G", "H", "I"],
        )


# ---------------------------------------------------------------------------
# Slide
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slide_null_image_urls_allowed() -> None:
    s = Slide(slide_id="s1", title="T", bullets=[], image_url=None, fallback_image_url=None)
    assert s.image_url is None


@pytest.mark.unit
def test_slide_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Slide(
            slide_id="s1", title="T", bullets=[],
            image_url=None, fallback_image_url=None,
            unknown="x",
        )


# ---------------------------------------------------------------------------
# JargonEntry / GlossaryEntry alias
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_jargon_and_glossary_are_same_type() -> None:
    j = JargonEntry(term="T", definition="D")
    g = GlossaryEntry(term="T", definition="D")
    assert type(j) is type(g)
    assert j == g


# ---------------------------------------------------------------------------
# NarrationTimestamp
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_narration_timestamp_negative_ms_rejected() -> None:
    with pytest.raises(ValidationError):
        NarrationTimestamp(slide_id="s1", start_ms=-1, end_ms=1000)


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_narration_audio_provider_enum() -> None:
    with pytest.raises(ValidationError):
        Narration(
            script="x", audio_url="https://x.com/a.mp3",
            audio_provider="sarvam",  # not in frozen schema enum yet
            timestamps=[],
        )


# ---------------------------------------------------------------------------
# LessonRecord
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lesson_record_content_nullable() -> None:
    r = LessonRecord(
        lesson_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        title=None,
        status="generating",
        content=None,
        source_file_path=None,
        created_at="2026-06-25T00:00:00Z",
        updated_at="2026-06-25T00:00:00Z",
    )
    assert r.content is None


@pytest.mark.unit
def test_lesson_status_values() -> None:
    for valid in ("generating", "ready", "failed"):
        r = LessonRecord(
            lesson_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            title=None, status=valid, content=None,
            source_file_path=None,
            created_at="2026-06-25T00:00:00Z",
            updated_at="2026-06-25T00:00:00Z",
        )
        assert r.status == valid


@pytest.mark.unit
def test_lesson_status_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        LessonRecord(
            lesson_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            title=None, status="published", content=None,
            source_file_path=None,
            created_at="2026-06-25T00:00:00Z",
            updated_at="2026-06-25T00:00:00Z",
        )


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_segment_requires_at_least_one_slide() -> None:
    seg_dict = MINIMAL_PACKAGE_DICT["segments"][0].copy()
    seg_dict["slides"] = []
    with pytest.raises(ValidationError):
        Segment.model_validate(seg_dict)


# ---------------------------------------------------------------------------
# LessonPackage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lesson_package_requires_at_least_one_segment() -> None:
    d = {**MINIMAL_PACKAGE_DICT, "segments": []}
    with pytest.raises(ValidationError):
        LessonPackage.model_validate(d)


@pytest.mark.unit
def test_lesson_package_extra_fields_forbidden() -> None:
    d = {**MINIMAL_PACKAGE_DICT, "unexpected": "value"}
    with pytest.raises(ValidationError):
        LessonPackage.model_validate(d)
