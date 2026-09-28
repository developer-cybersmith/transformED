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
    SplitScreenSide,
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
            title="T",
            subject="S",
            total_segments=0,
            estimated_duration_mins=1.0,
            complexity_level="low",
        )


@pytest.mark.unit
def test_lesson_metadata_duration_min() -> None:
    with pytest.raises(ValidationError):
        LessonMetadata(
            title="T",
            subject="S",
            total_segments=1,
            estimated_duration_mins=-1.0,
            complexity_level="low",
        )


@pytest.mark.unit
def test_lesson_metadata_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        LessonMetadata(
            title="T",
            subject="S",
            total_segments=1,
            estimated_duration_mins=1.0,
            complexity_level="low",
            unexpected_field="x",
        )


@pytest.mark.unit
def test_lesson_metadata_tier_defaults_to_t2() -> None:
    """Story 2-2 AC-1: tier defaults to T2 so existing callers/fixtures are unaffected."""
    metadata = LessonMetadata(
        title="T",
        subject="S",
        total_segments=1,
        estimated_duration_mins=1.0,
        complexity_level="low",
    )
    assert metadata.tier == "T2"


@pytest.mark.unit
@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
def test_lesson_metadata_tier_accepts_valid_values(tier: str) -> None:
    metadata = LessonMetadata(
        title="T",
        subject="S",
        total_segments=1,
        estimated_duration_mins=1.0,
        complexity_level="low",
        tier=tier,
    )
    assert metadata.tier == tier


@pytest.mark.unit
def test_lesson_metadata_tier_rejects_invalid_value() -> None:
    with pytest.raises(ValidationError):
        LessonMetadata(
            title="T",
            subject="S",
            total_segments=1,
            estimated_duration_mins=1.0,
            complexity_level="low",
            tier="T4",
        )


@pytest.mark.unit
@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
def test_lesson_package_tier_round_trips_through_json_schema(tier: str) -> None:
    """Story 2-2 AC-1/AC-5: every tier value round-trips through Pydantic + the
    frozen JSON schema (Story 2-25: `tier` is optional in the schema, matching
    Pydantic's "T2" default — see additionalProperties: false)."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    package_dict = {
        **MINIMAL_PACKAGE_DICT,
        "metadata": {**MINIMAL_PACKAGE_DICT["metadata"], "tier": tier},
    }
    package = LessonPackage.model_validate(package_dict)
    assert package.metadata.tier == tier
    jsonschema.validate(instance=json.loads(package.model_dump_json()), schema=schema)


@pytest.mark.unit
def test_lesson_metadata_omitting_tier_validates_against_raw_json_schema() -> None:
    """Story 2-25 regression: a metadata dict that omits `tier` entirely must
    validate against the raw JSON schema (bypassing Pydantic's default-filling
    by validating the input dict directly, not a Pydantic model_dump). Before
    this story, `tier` was in LessonMetadata's `required` array — a payload
    omitting it failed schema validation here while silently defaulting to
    "T2" in Pydantic (a real 3-way contract drift, not just a hypothetical)."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    package_dict = {
        **MINIMAL_PACKAGE_DICT,
        "metadata": {k: v for k, v in MINIMAL_PACKAGE_DICT["metadata"].items() if k != "tier"},
    }
    assert "tier" not in package_dict["metadata"]
    jsonschema.validate(instance=package_dict, schema=schema)


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
            cognitive_load="x",
            abstraction_level="x",
            prerequisite_concepts=[],
            narration_style="x",
            quiz_difficulty="x",
            intervention_sensitivity=0.5,
        )


# ---------------------------------------------------------------------------
# QuizQuestion
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_quiz_question_requires_four_options() -> None:
    with pytest.raises(ValidationError):
        QuizQuestion(
            question_id="q1",
            type="mcq",
            question="Q?",
            options=["A", "B", "C"],  # only 3
            correct_index=0,
            explanation="E",
            difficulty="easy",
        )


@pytest.mark.unit
def test_quiz_question_valid() -> None:
    q = QuizQuestion(
        question_id="q1",
        type="mcq",
        question="Q?",
        options=["A", "B", "C", "D"],
        correct_index=0,
        explanation="E",
        difficulty="easy",
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
            slide_id="s1",
            title="T",
            bullets=[],
            image_url=None,
            fallback_image_url=None,
            unknown="x",
        )


# ---------------------------------------------------------------------------
# Slide — Story 233 Piece 1: slide_type / topic_index / target_duration_sec /
# left_content / right_content. Mirrors the exact test pattern the
# LessonPackage avatar-fields story (below) already established for a
# frozen-contract additive/nullable field set: default-to-None,
# accepts-real-values, omitting-still-validates-against-raw-schema, and
# round-trips-through-JSON-schema.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_slide_new_fields_default_to_none() -> None:
    s = Slide(slide_id="s1", title="T", bullets=[], image_url=None, fallback_image_url=None)
    assert s.slide_type is None
    assert s.topic_index is None
    assert s.target_duration_sec is None
    assert s.left_content is None
    assert s.right_content is None


@pytest.mark.unit
def test_slide_new_fields_accept_real_values() -> None:
    s = Slide(
        slide_id="s1",
        title="T",
        bullets=[],
        image_url=None,
        fallback_image_url=None,
        slide_type="split_screen",
        topic_index=1,
        target_duration_sec=300,
        left_content=SplitScreenSide(heading="Technical", bullets=["Definition", "Formula"]),
        right_content=SplitScreenSide(heading="Relatable", bullets=["Movie reference"]),
    )
    assert s.slide_type == "split_screen"
    assert s.topic_index == 1
    assert s.target_duration_sec == 300
    assert s.left_content is not None
    assert s.left_content.heading == "Technical"
    assert s.left_content.bullets == ["Definition", "Formula"]
    assert s.right_content is not None
    assert s.right_content.heading == "Relatable"


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "overview",
        "contents",
        "topic_teaching",
        "split_screen",
        "qa",
        "broader_picture",
        "mind_map",
    ],
)
def test_slide_type_accepts_all_seven_values(value: str) -> None:
    s = Slide(
        slide_id="s1",
        title="T",
        bullets=[],
        image_url=None,
        fallback_image_url=None,
        slide_type=value,
    )
    assert s.slide_type == value


@pytest.mark.unit
def test_slide_type_rejects_invalid_value() -> None:
    with pytest.raises(ValidationError):
        Slide(
            slide_id="s1",
            title="T",
            bullets=[],
            image_url=None,
            fallback_image_url=None,
            slide_type="not_a_real_type",
        )


@pytest.mark.unit
def test_split_screen_side_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        SplitScreenSide(heading="H", bullets=[], unknown="x")


@pytest.mark.unit
def test_split_screen_side_requires_heading_and_bullets() -> None:
    """Round 1 review finding (Test Coverage, HIGH, reproduced by mutating
    SplitScreenSide to make both fields optional and confirming the full
    suite stayed green): SplitScreenSide's `required` shape (both `heading`
    and `bullets`, per lesson_package.schema.json) was never independently
    asserted at the Pydantic layer. A future edit accidentally adding a
    `= None` default to either field would silently violate the frozen JSON
    schema's `"required": ["heading", "bullets"]` with no test catching it."""
    with pytest.raises(ValidationError):
        SplitScreenSide(bullets=["x"])  # type: ignore[call-arg]  # missing heading
    with pytest.raises(ValidationError):
        SplitScreenSide(heading="H")  # type: ignore[call-arg]  # missing bullets


@pytest.mark.unit
def test_slide_left_content_rejects_malformed_object_via_json_schema() -> None:
    """Round 1 review finding (Test Coverage, HIGH, reproduced by weakening
    left_content's schema `$ref` to a permissive `{"type": "object"}` and
    confirming the full suite stayed green): every existing JSON-schema-facing
    test only exercises the ACCEPT path for left_content/right_content.
    Proves the reject path too -- a left_content object missing `bullets`
    (violating SplitScreenSide's own `required`) must fail jsonschema
    validation, confirming the `$ref` to #/definitions/SplitScreenSide is
    real and enforced, not silently weakened to an unconstrained object."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    d = json.loads(json.dumps(MINIMAL_PACKAGE_DICT))
    d["segments"][0]["slides"][0]["left_content"] = {"heading": "Technical"}  # missing bullets
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=d, schema=schema)


@pytest.mark.unit
def test_slide_left_and_right_content_independently_settable() -> None:
    """Round 1 review finding (Test Coverage, MEDIUM): every existing test
    sets left_content/right_content together or both-None -- never the
    realistic partial-population shape. Proves each side is genuinely
    independent, not silently coupled."""
    s = Slide(
        slide_id="s1",
        title="T",
        bullets=[],
        image_url=None,
        fallback_image_url=None,
        left_content=SplitScreenSide(heading="Technical", bullets=["Only side set"]),
    )
    assert s.left_content is not None
    assert s.right_content is None

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    d = json.loads(json.dumps(MINIMAL_PACKAGE_DICT))
    d["segments"][0]["slides"][0]["right_content"] = {"heading": "Relatable", "bullets": ["x"]}
    jsonschema.validate(instance=d, schema=schema)


@pytest.mark.unit
def test_slide_topic_index_and_duration_reject_out_of_range_values() -> None:
    """Round 1 review finding (Blind Hunter, LOW): unlike every other
    numeric field in this file (NarrationTimestamp.start_ms/end_ms,
    LessonMetadata.total_segments, SegmentComplexity.intervention_sensitivity),
    topic_index/target_duration_sec originally had no lower bound. Fixed via
    Field(ge=1)/Field(ge=0)."""
    with pytest.raises(ValidationError):
        Slide(
            slide_id="s1",
            title="T",
            bullets=[],
            image_url=None,
            fallback_image_url=None,
            topic_index=0,  # topics are 1 or 2 per the slide-strategy spec, never 0
        )
    with pytest.raises(ValidationError):
        Slide(
            slide_id="s1",
            title="T",
            bullets=[],
            image_url=None,
            fallback_image_url=None,
            target_duration_sec=-1,
        )


@pytest.mark.unit
def test_split_screen_side_in_schemas_dunder_all() -> None:
    """Round 1 review finding (Story Quality, MEDIUM): AC9 originally named
    test_node_return_shape.py/test_unbounded_queries.py as this story's
    guard tests, but neither actually covers a schemas/__init__.py __all__
    addition -- test_node_return_shape.py AST-scans only pipeline/tutor node
    returns, and test_unbounded_queries.py explicitly scopes to router.py/
    service.py. The real, already-precedented guard for this exact situation
    is test_f2_1_learner_context.py's own __all__ membership assertion --
    mirrored here."""
    from app import schemas

    assert "SplitScreenSide" in schemas.__all__, (
        "SplitScreenSide missing from schemas.__all__ — add it so imports work across modules"
    )


@pytest.mark.unit
def test_slide_omitting_new_fields_validates_against_raw_json_schema() -> None:
    """AC 5: a slide dict with none of the 5 new fields present -- exactly
    every existing lesson record and every existing test fixture, including
    MINIMAL_PACKAGE_DICT itself, unchanged -- must still validate against the
    updated JSON schema. These 5 fields must never be added to Slide's
    `required` array in the schema for this reason."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    slide_dict = MINIMAL_PACKAGE_DICT["segments"][0]["slides"][0]
    for new_field in (
        "slide_type",
        "topic_index",
        "target_duration_sec",
        "left_content",
        "right_content",
    ):
        assert new_field not in slide_dict
    jsonschema.validate(instance=MINIMAL_PACKAGE_DICT, schema=schema)


@pytest.mark.unit
def test_slide_new_fields_round_trip_through_json_schema() -> None:
    """AC 6: a slide with all 5 new fields populated, including a fully
    populated SplitScreenSide on both sides, round-trips through
    Slide.model_validate() -> model_dump(mode="json") -> the raw JSON schema
    validator."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    d = json.loads(json.dumps(MINIMAL_PACKAGE_DICT))
    d["segments"][0]["slides"][0].update(
        {
            "slide_type": "split_screen",
            "topic_index": 2,
            "target_duration_sec": 210,
            "left_content": {"heading": "Technical", "bullets": ["Step 1", "Step 2"]},
            "right_content": {"heading": "Relatable", "bullets": ["Cricket analogy"]},
        }
    )
    package = LessonPackage.model_validate(d)
    dumped = json.loads(package.model_dump_json())
    jsonschema.validate(instance=dumped, schema=schema)
    round_tripped_slide = dumped["segments"][0]["slides"][0]
    assert round_tripped_slide["slide_type"] == "split_screen"
    assert round_tripped_slide["left_content"]["heading"] == "Technical"
    assert round_tripped_slide["right_content"]["bullets"] == ["Cricket analogy"]


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
            script="x",
            audio_url="https://x.com/a.mp3",
            audio_provider="elevenlabs",  # removed — replaced by sarvam (CLAUDE.md 2026-06-25)
            timestamps=[],
        )


def test_narration_audio_provider_accepts_sixtydb() -> None:
    """Story 232 (review finding, AC 8): "sixtydb" was added to the frozen
    AudioProvider enum across 3 files (schemas/lesson.py, lesson.ts,
    lesson_package.schema.json) with no test asserting it — this closes that
    gap, checking both the Pydantic model and the raw JSON schema (the same
    round-trip convention every other AC in this file already uses)."""
    narration = Narration(
        script="x",
        audio_url="https://x.com/a.mp3",
        audio_provider="sixtydb",
        timestamps=[],
    )
    assert narration.audio_provider == "sixtydb"

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    package_dict = {
        **MINIMAL_PACKAGE_DICT,
        "segments": [
            {
                **MINIMAL_PACKAGE_DICT["segments"][0],
                "narration": {
                    **MINIMAL_PACKAGE_DICT["segments"][0]["narration"],
                    "audio_provider": "sixtydb",
                },
            }
        ],
    }
    jsonschema.validate(instance=package_dict, schema=schema)


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
            title=None,
            status=valid,
            content=None,
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
            title=None,
            status="published",
            content=None,
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


# ---------------------------------------------------------------------------
# Avatar fields (Story 1-5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_lesson_package_avatar_fields_default_to_none() -> None:
    package = LessonPackage.model_validate(MINIMAL_PACKAGE_DICT)
    assert package.avatar_intro_url is None
    assert package.avatar_static_url is None
    assert package.avatar_outro_url is None


@pytest.mark.unit
def test_lesson_package_avatar_fields_accept_real_urls() -> None:
    d = {
        **MINIMAL_PACKAGE_DICT,
        "avatar_intro_url": "https://example.com/intro.mp4",
        "avatar_static_url": "https://example.com/static.png",
        "avatar_outro_url": "https://example.com/outro.mp4",
    }
    package = LessonPackage.model_validate(d)
    assert package.avatar_intro_url == "https://example.com/intro.mp4"
    assert package.avatar_static_url == "https://example.com/static.png"
    assert package.avatar_outro_url == "https://example.com/outro.mp4"


@pytest.mark.unit
def test_lesson_package_omitting_avatar_fields_validates_against_raw_json_schema() -> None:
    """Story 1-5 regression guard, mirrors the Story 2-25 tier fix: a
    LessonPackage dict that omits avatar_intro_url/avatar_static_url/
    avatar_outro_url entirely -- exactly what every pre-Story-1-5 lesson and
    every existing test fixture looks like -- must still validate against the
    raw JSON schema. These fields must never be added to the schema's
    `required` array for this reason."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    assert "avatar_intro_url" not in MINIMAL_PACKAGE_DICT
    assert "avatar_static_url" not in MINIMAL_PACKAGE_DICT
    assert "avatar_outro_url" not in MINIMAL_PACKAGE_DICT
    jsonschema.validate(instance=MINIMAL_PACKAGE_DICT, schema=schema)


@pytest.mark.unit
def test_lesson_package_avatar_fields_round_trip_through_json_schema() -> None:
    """Review finding (Blind Hunter + Edge Case Hunter, corroborated): the
    schema's "format: uri" on these 3 properties is currently NOT enforced --
    jsonschema requires an explicit FormatChecker, and even with one supplied,
    this environment has no "uri" checker registered (needs the optional
    `rfc3987` package, not installed -- confirmed via
    `jsonschema.FormatChecker().checkers` not containing "uri"). Passing
    `format_checker=jsonschema.FormatChecker()` here is honest about that
    limitation rather than pretending it enforces something it doesn't: it
    exercises the same code path the constraint would use if the dependency
    were ever added, without a false "this proves URLs are validated" claim."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
    d = {
        **MINIMAL_PACKAGE_DICT,
        "avatar_intro_url": "https://example.com/intro.mp4",
        "avatar_static_url": None,
        "avatar_outro_url": "https://example.com/outro.mp4",
    }
    package = LessonPackage.model_validate(d)
    jsonschema.validate(
        instance=json.loads(package.model_dump_json()),
        schema=schema,
        format_checker=jsonschema.FormatChecker(),
    )
