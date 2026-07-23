"""
Unit tests for Story 2-11 (S2-11): package_builder_node real body.

Covers docs/stories/2-11-package-builder-node.md's ACs:
- AC-2: chapter_id resolved from the chunk_node checkpoint.
- AC-3/AC-4: LessonMetadata + per-segment assembly, correlating every
  upstream node's output by segment_id (slide_images by slide_id).
- AC-5/AC-6: per-segment degrade-and-skip; RuntimeError if every segment
  gets skipped.
- AC-7: top-level glossary is a deduplicated aggregate across segments.
- AC-8: teachback_prompt is a deterministic placeholder.
- AC-9: LessonPackage.model_validate() failures propagate uncaught.
- AC-10/AC-11: lessons/lesson_jobs writes on success; idempotency checkpoint.
- AC-12/AC-13: no WebSocket or Supabase Storage calls of any kind.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

FAKE_LESSON_ID = "70707070-7070-7070-7070-707070707070"
FAKE_BOOK_ID = "80808080-8080-8080-8080-808080808080"
FAKE_CHAPTER_ID = "90909090-9090-9090-9090-909090909090"

LESSON_PLAN: dict[str, Any] = {
    "title": "Intro to Thermodynamics",
    "subject": "Physics",
    "objectives": ["Understand entropy", "Understand heat transfer"],
    "complexity_level": "medium",
    "total_segments": 2,
    "total_duration_min": 12.5,
    "segments": [
        {
            "segment_id": "sec_0",
            "title": "Entropy Basics",
            "summary": "Intro to entropy.",
            "duration_min": 6.0,
        },
        {
            "segment_id": "sec_1",
            "title": "Heat Transfer",
            "summary": "Intro to heat transfer.",
            "duration_min": 6.5,
        },
    ],
}

COMPLEXITY_SCORES: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "level": "medium",
        "cognitive_load": "moderate",
        "abstraction_level": "concrete",
        "prerequisite_concepts": ["energy"],
        "narration_style": "conversational",
        "quiz_difficulty": "medium",
        "intervention_sensitivity": 0.4,
    },
    {
        "segment_id": "sec_1",
        "level": "medium",
        "cognitive_load": "moderate",
        "abstraction_level": "concrete",
        "prerequisite_concepts": ["temperature"],
        "narration_style": "conversational",
        "quiz_difficulty": "medium",
        "intervention_sensitivity": 0.5,
    },
]

SLIDES: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "slide_id": "slide_sec_0_0",
            "title": "What is Entropy?",
            "bullets": ["Point A"],
            "image_url": None,
            "fallback_image_url": None,
        },
    },
    {
        "segment_id": "sec_1",
        "data": {
            "slide_id": "slide_sec_1_0",
            "title": "Conduction",
            "bullets": ["Point B"],
            "image_url": None,
            "fallback_image_url": None,
        },
    },
]

SLIDE_IMAGES: list[dict[str, Any]] = [
    {"slide_id": "slide_sec_0_0", "image_url": f"{FAKE_LESSON_ID}/slide_sec_0_0.png"},
    {"slide_id": "slide_sec_1_0", "image_url": None},
]

AUDIO_ASSETS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "script": "Entropy measures disorder.",
            "audio_url": f"{FAKE_LESSON_ID}/sec_0.mp3",
            "audio_provider": "sarvam",
            "timestamps": [],
        },
    },
    {
        "segment_id": "sec_1",
        "data": {
            "script": "Heat flows from hot to cold.",
            "audio_url": f"{FAKE_LESSON_ID}/sec_1.mp3",
            "audio_provider": "azure",
            "timestamps": [],
        },
    },
]

QUIZ_QUESTIONS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "question_id": "quiz_sec_0",
            "type": "mcq",
            "question": "What is entropy?",
            "options": ["Disorder", "Order", "Mass", "Energy"],
            "correct_index": 0,
            "explanation": "Entropy measures disorder.",
            "difficulty": "medium",
        },
    },
    {
        "segment_id": "sec_1",
        "data": {
            "question_id": "quiz_sec_1",
            "type": "mcq",
            "question": "Heat flows from?",
            "options": ["Hot to cold", "Cold to hot", "Nowhere", "Everywhere"],
            "correct_index": 0,
            "explanation": "Second law of thermodynamics.",
            "difficulty": "medium",
        },
    },
]

GLOSSARY: list[dict[str, Any]] = [
    {"segment_id": "sec_0", "data": {"term": "Entropy", "definition": "A measure of disorder."}},
    {
        "segment_id": "sec_1",
        "data": {"term": "entropy ", "definition": "A duplicate, different casing."},
    },
    {
        "segment_id": "sec_1",
        "data": {"term": "Conduction", "definition": "Heat transfer through contact."},
    },
]

INTERVENTION_PROMPTS: list[dict[str, Any]] = [
    {
        "segment_id": "sec_0",
        "data": {
            "distraction": ["Stay focused!", "You've got this.", "Keep going."],
            "confusion": ["Let's slow down.", "Try re-reading.", "It's okay to pause."],
            "fatigue": ["Take a breath.", "Almost there.", "Stretch a bit."],
        },
    },
    {
        "segment_id": "sec_1",
        "data": {
            "distraction": ["Stay focused!", "You've got this.", "Keep going."],
            "confusion": ["Let's slow down.", "Try re-reading.", "It's okay to pause."],
            "fatigue": ["Take a breath.", "Almost there.", "Stretch a bit."],
        },
    },
]


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "lesson_plan": LESSON_PLAN,
        "complexity_scores": COMPLEXITY_SCORES,
        "slides": SLIDES,
        "slide_images": SLIDE_IMAGES,
        "audio_assets": AUDIO_ASSETS,
        "quiz_questions": QUIZ_QUESTIONS,
        "glossary": GLOSSARY,
        "intervention_prompts": INTERVENTION_PROMPTS,
        "progress_pct": 93.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_supabase(
    node_outputs: dict[str, Any] | None = None,
    chapter_id: str = FAKE_CHAPTER_ID,
) -> MagicMock:
    jobs_data = {
        "node_outputs": {**(node_outputs or {}), "chunk": {"chapter_id": chapter_id, "chunks": []}}
    }
    if node_outputs and "chunk" in node_outputs:
        jobs_data = {"node_outputs": node_outputs}

    jobs_table = MagicMock()
    jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        jobs_data
    )
    jobs_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    lessons_table = MagicMock()
    lessons_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    def _table_router(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs_table
        if name == "lessons":
            return lessons_table
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table_router
    sb.storage = MagicMock()
    return sb, jobs_table, lessons_table


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_assembles_valid_lesson_package_and_writes_both_tables() -> None:
    from app.modules.content.pipeline.graph import package_builder_node
    from app.schemas.lesson import LessonPackage

    sb, jobs_table, lessons_table = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    package = LessonPackage.model_validate(result["lesson_package"])
    assert package.metadata.title == "Intro to Thermodynamics"
    assert len(package.segments) == 2
    assert result["progress_pct"] == 100.0

    lessons_table.update.assert_called_once()
    lessons_update_kwargs = lessons_table.update.call_args[0][0]
    assert lessons_update_kwargs["status"] == "ready"
    assert lessons_update_kwargs["title"] == "Intro to Thermodynamics"

    jobs_update_kwargs = jobs_table.update.call_args[0][0]
    assert jobs_update_kwargs["status"] == "completed"
    assert "completed_at" in jobs_update_kwargs
    assert "package_builder" in jobs_update_kwargs["node_outputs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slide_image_correlated_by_slide_id_not_segment_id() -> None:
    """AC-4: slide_images is a FLAT list with no segment_id at all — must
    correlate purely by slide_id."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    package = result["lesson_package"]
    seg0_slide = package["segments"][0]["slides"][0]
    seg1_slide = package["segments"][1]["slides"][0]
    assert seg0_slide["image_url"] == f"{FAKE_LESSON_ID}/slide_sec_0_0.png"
    assert seg1_slide["image_url"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_top_level_glossary_deduplicates_across_segments() -> None:
    """AC-7: 'Entropy' (sec_0) and 'entropy ' (sec_1, different case/whitespace)
    must collapse to a single glossary entry, first occurrence's casing kept."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    glossary_terms = [g["term"] for g in result["lesson_package"]["glossary"]]
    assert glossary_terms.count("Entropy") == 1
    assert "entropy " not in glossary_terms
    assert "Conduction" in glossary_terms
    assert len(glossary_terms) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_missing_complexity_is_degraded_not_dropped() -> None:
    """Story 2-21: a segment with slides but missing complexity is KEPT with a
    neutral default complexity, not dropped — its succeeded parts survive."""
    from app.modules.content.pipeline.graph import package_builder_node

    incomplete_scores = [c for c in COMPLEXITY_SCORES if c["segment_id"] != "sec_0"]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(complexity_scores=incomplete_scores))

    package = result["lesson_package"]
    assert len(package["segments"]) == 2
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert seg0["complexity"]["level"] == "medium", "neutral default backfilled"
    assert seg0["slides"], "succeeded slides preserved"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_missing_narration_is_degraded_not_dropped() -> None:
    """Story 2-21: a segment missing narration is KEPT with a browser-fallback
    Narration (no server audio), not dropped; timestamps still come from slides."""
    from app.modules.content.pipeline.graph import package_builder_node

    incomplete_audio = [a for a in AUDIO_ASSETS if a["segment_id"] != "sec_1"]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(audio_assets=incomplete_audio))

    package = result["lesson_package"]
    assert len(package["segments"]) == 2
    seg1 = next(s for s in package["segments"] if s["segment_id"] == "sec_1")
    assert seg1["narration"]["audio_provider"] == "browser"
    assert seg1["narration"]["audio_url"] == ""
    assert len(seg1["narration"]["timestamps"]) == len(seg1["slides"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_missing_interventions_is_degraded_not_dropped() -> None:
    """Story 2-21: a segment missing interventions is KEPT with neutral default
    intervention messages (3 per type), not dropped."""
    from app.modules.content.pipeline.graph import package_builder_node

    incomplete_interventions = [i for i in INTERVENTION_PROMPTS if i["segment_id"] != "sec_0"]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(
            _base_state(intervention_prompts=incomplete_interventions)
        )

    package = result["lesson_package"]
    assert len(package["segments"]) == 2
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert len(seg0["interventions"]["distraction"]) == 3
    assert len(seg0["interventions"]["confusion"]) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_with_zero_slides_is_skipped() -> None:
    from app.modules.content.pipeline.graph import package_builder_node

    incomplete_slides = [s for s in SLIDES if s["segment_id"] != "sec_0"]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(slides=incomplete_slides))

    package = result["lesson_package"]
    assert len(package["segments"]) == 1
    assert package["segments"][0]["segment_id"] == "sec_1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_segments_without_slides_raises_runtime_error_and_writes_nothing() -> None:
    """Story 2-21/AC-4: 'zero usable segments' raises ONLY when every segment
    lacks slides (a genuine empty lesson) — no longer for a recoverable missing
    field like complexity (see test_missing_complexity_for_all_segments_...)."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, jobs_table, lessons_table = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        with pytest.raises(RuntimeError, match="zero usable segments"):
            await package_builder_node(_base_state(slides=[], slide_images=[]))

    # The 95%-progress marker call (status="running") is expected and fine —
    # only the completion write (status="completed") and the lessons-table
    # write must never happen once the RuntimeError fires.
    lessons_table.update.assert_not_called()
    for call in jobs_table.update.call_args_list:
        assert call[0][0].get("status") != "completed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_validate_failure_propagates_uncaught() -> None:
    """AC-9: a schema violation (here: no valid chapter_id available because
    the chunk checkpoint is missing) must raise, never be swallowed."""
    from app.modules.content.pipeline.graph import package_builder_node

    jobs_table = MagicMock()
    jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": {}  # no "chunk" key at all -> chapter_id resolves to ""
    }
    jobs_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
    lessons_table = MagicMock()

    def _table_router(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs_table
        if name == "lessons":
            return lessons_table
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table_router

    with patch("app.core.db.get_supabase", return_value=sb):
        with pytest.raises(ValidationError):  # not RuntimeError
            await package_builder_node(_base_state())

    lessons_table.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_cache_hit_returns_cached_without_any_writes() -> None:
    """AC-11: a cache hit must skip reassembly AND skip re-writing
    lessons/lesson_jobs entirely."""
    from app.modules.content.pipeline.graph import package_builder_node

    cached_package = {"lesson_id": FAKE_LESSON_ID, "cached": True}
    sb, jobs_table, lessons_table = _mock_supabase(
        node_outputs={"chunk": {"chapter_id": FAKE_CHAPTER_ID}, "package_builder": cached_package}
    )

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    assert result["lesson_package"] == cached_package
    assert result["progress_pct"] == 100.0
    jobs_table.update.assert_not_called()
    lessons_table.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_storage_or_websocket_calls_made() -> None:
    """AC-12/AC-13: this node must never touch Supabase Storage or any
    WebSocket-sending code — that's S2-12's job, not this story's."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(_base_state())

    sb.storage.from_.assert_not_called()


# ---------------------------------------------------------------------------
# 2026-07-16 code review patches (Edge Case Hunter coverage gaps)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_with_zero_quiz_and_jargon_still_included() -> None:
    """AC-5: quiz/jargon have no min_length on Segment — an empty match is
    NOT a reason to skip an otherwise-valid segment."""
    from app.modules.content.pipeline.graph import package_builder_node

    no_quiz_no_jargon_quiz = [q for q in QUIZ_QUESTIONS if q["segment_id"] != "sec_0"]
    no_quiz_no_jargon_glossary = [g for g in GLOSSARY if g["segment_id"] != "sec_0"]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(
            _base_state(quiz_questions=no_quiz_no_jargon_quiz, glossary=no_quiz_no_jargon_glossary)
        )

    package = result["lesson_package"]
    assert len(package["segments"]) == 2
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert seg0["quiz"] == []
    assert seg0["jargon"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chunk_present_but_missing_chapter_id_key_behaves_like_chunk_absent() -> None:
    """The .get("chapter_id", "") fallback must handle both 'chunk absent'
    and 'chunk present without chapter_id' identically — both should fail
    LessonPackage's UUID validation the same way."""
    from app.modules.content.pipeline.graph import package_builder_node

    jobs_table = MagicMock()
    jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": {"chunk": {"chunks": []}}  # chunk present, no chapter_id key
    }
    jobs_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
    lessons_table = MagicMock()

    def _table_router(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs_table
        if name == "lessons":
            return lessons_table
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table_router

    with patch("app.core.db.get_supabase", return_value=sb):
        with pytest.raises(ValidationError):
            await package_builder_node(_base_state())

    lessons_table.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_book_id_fails_model_validate() -> None:
    """book_id follows the same UUID-required path as chapter_id — a missing
    book_id must also fail validation, not silently produce an invalid
    'valid' package."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, lessons_table = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        with pytest.raises(ValidationError):
            await package_builder_node(_base_state(book_id=""))

    lessons_table.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slide_entirely_absent_from_slide_images_degrades_same_as_explicit_none() -> None:
    """A slide_id with NO entry at all in slide_images (image_generator_node
    never ran for it) must degrade to image_url=None identically to a slide
    with an explicit {slide_id, image_url: None} entry — not KeyError."""
    from app.modules.content.pipeline.graph import package_builder_node

    slide_images_missing_one = [img for img in SLIDE_IMAGES if img["slide_id"] != "slide_sec_1_0"]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(slide_images=slide_images_missing_one))

    seg1_slide = next(
        s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_1"
    )["slides"][0]
    assert seg1_slide["image_url"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_segment_id_in_complexity_scores_keeps_last_and_logs_warning(
    caplog: Any,
) -> None:
    """A retried/duplicate Send() dispatch could produce two complexity_scores
    entries for the same segment_id — must not crash, and must log a warning
    rather than silently picking one with no trace."""
    from app.modules.content.pipeline.graph import package_builder_node

    duplicated_scores = COMPLEXITY_SCORES + [
        {**COMPLEXITY_SCORES[0], "level": "high"}  # second entry for sec_0
    ]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(complexity_scores=duplicated_scores))

    package = result["lesson_package"]
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert seg0["complexity"]["level"] == "high"  # last one wins, as documented
    assert any("duplicate segment_id" in r.message for r in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orphaned_upstream_data_not_in_plan_is_logged_and_ignored(caplog: Any) -> None:
    """Segment data present in an upstream list but absent from
    lesson_plan["segments"] must be silently ignored in the assembled
    package (plan is authoritative) but logged, not invisible."""
    from app.modules.content.pipeline.graph import package_builder_node

    orphaned_scores = COMPLEXITY_SCORES + [{**COMPLEXITY_SCORES[0], "segment_id": "sec_orphan"}]
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(complexity_scores=orphaned_scores))

    package = result["lesson_package"]
    assert {s["segment_id"] for s in package["segments"]} == {"sec_0", "sec_1"}
    assert any("sec_orphan" in r.message for r in caplog.records)


# ── Story S2-LM3/LM7: tier written into LessonMetadata ──────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tier_from_state_written_into_metadata() -> None:
    """AC-7: LessonMetadata.tier reflects state["tier"] (set at run_pipeline
    entry from the lessons.tier column), not always the Pydantic default."""
    from app.modules.content.pipeline.graph import package_builder_node
    from app.schemas.lesson import LessonPackage

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(tier="T3"))

    package = LessonPackage.model_validate(result["lesson_package"])
    assert package.metadata.tier == "T3"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_tier_in_state_defaults_metadata_tier_to_t2() -> None:
    """No "tier" key in state at all (pre-S2-LM3 caller, or a test fixture
    that never set one) must still validate — defaults to T2."""
    from app.modules.content.pipeline.graph import package_builder_node
    from app.schemas.lesson import LessonPackage

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())  # no "tier" key

    package = LessonPackage.model_validate(result["lesson_package"])
    assert package.metadata.tier == "T2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_tier_string_in_state_falls_back_to_t2_not_passed_through() -> None:
    """Code review fix (Acceptance Auditor + Edge Case Hunter, independently):
    an invalid (non-empty, non-T1/T2/T3) tier string in state must be
    normalized to T2 here — the last line of defense before
    LessonPackage.model_validate() — not passed through unchecked, which
    would fail validation AFTER every upstream LLM/TTS/image cost is spent."""
    from app.modules.content.pipeline.graph import package_builder_node
    from app.schemas.lesson import LessonPackage

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(tier="not-a-real-tier"))

    package = LessonPackage.model_validate(result["lesson_package"])
    assert package.metadata.tier == "T2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_timestamps_populated_and_contiguous() -> None:
    """Story 2-19 (AC-1/AC-2): package_builder fills narration.timestamps
    (tts_node ships []), one per slide, contiguous from 0 — so the player's
    slide-sync (binary search) and segment-end quiz boundary work."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    for seg in result["lesson_package"]["segments"]:
        ts = seg["narration"]["timestamps"]
        assert len(ts) == len(seg["slides"]), "one timestamp per slide"
        assert ts[0]["start_ms"] == 0
        for a, b in zip(ts, ts[1:], strict=False):
            assert a["end_ms"] == b["start_ms"], "contiguous"
        for t in ts:
            assert set(t) == {"slide_id", "start_ms", "end_ms"}
            assert t["start_ms"] < t["end_ms"]
        assert [t["slide_id"] for t in ts] == [s["slide_id"] for s in seg["slides"]]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multi_slide_segment_track_and_settings_flow() -> None:
    """Story 2-19 (AC-1/AC-2/AC-3 through the REAL node): a segment with >=2
    slides gets a contiguous multi-entry track, and the estimated duration is
    driven by settings.narration_words_per_minute (proves the wiring uses the
    setting, not a hardcoded value)."""
    from app.config import get_settings
    from app.modules.content.pipeline.graph import package_builder_node

    slides_multi = [
        SLIDES[0],
        {
            "segment_id": "sec_0",
            "data": {
                "slide_id": "slide_sec_0_1",
                "title": "More Entropy",
                "bullets": ["Point A2"],
                "image_url": None,
                "fallback_image_url": None,
            },
        },
        SLIDES[1],
    ]
    slide_images_multi = [*SLIDE_IMAGES, {"slide_id": "slide_sec_0_1", "image_url": None}]

    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(
            _base_state(slides=slides_multi, slide_images=slide_images_multi)
        )

    seg0 = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    ts = seg0["narration"]["timestamps"]
    assert len(ts) == 2, "two slides -> two timestamps"
    assert [t["slide_id"] for t in ts] == ["slide_sec_0_0", "slide_sec_0_1"]
    assert ts[0]["start_ms"] == 0
    assert ts[0]["end_ms"] == ts[1]["start_ms"], "contiguous across entries"
    assert ts[0]["start_ms"] < ts[0]["end_ms"] and ts[1]["start_ms"] < ts[1]["end_ms"]
    # sec_0 script "Entropy measures disorder." = 3 words; duration must use the setting.
    wpm = get_settings().narration_words_per_minute
    assert ts[-1]["end_ms"] == round(3 / wpm * 60_000), "duration derived from the wpm setting"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_complexity_for_all_segments_completes_degraded() -> None:
    """Story 2-21: the OLD failure mode — complexity_scores=[] used to raise
    'zero usable segments'; now both slide-bearing segments are kept, degraded,
    and the lesson completes."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, lessons_table = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(complexity_scores=[]))

    package = result["lesson_package"]
    assert len(package["segments"]) == 2
    for seg in package["segments"]:
        assert seg["complexity"]["level"] == "medium"
    lessons_table.update.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_prompt_surfaces_jargon_terms() -> None:
    """Story 2-23: the teach-back prompt names the segment's jargon terms (the
    Dev3 scorer's key_concepts), aligning the shown prompt with the scoring."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    for seg in result["lesson_package"]["segments"]:
        terms = [j["term"] for j in seg["jargon"]]
        if terms:
            assert "Try to cover:" in seg["teachback_prompt"]
            for term in terms:
                assert " ".join(term.split()) in seg["teachback_prompt"]
        else:
            assert "Try to cover:" not in seg["teachback_prompt"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_prompt_generic_when_no_jargon() -> None:
    """Story 2-23 AC-2: no jargon -> the existing generic prompt (no 'cover' clause)."""
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(glossary=[]))

    for seg in result["lesson_package"]["segments"]:
        assert "Try to cover:" not in seg["teachback_prompt"]
        assert "explain what you learned about" in seg["teachback_prompt"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_prompt_dedups_jargon_terms_case_insensitively() -> None:
    """Story 2-23 AC-1: repeated jargon terms (incl. case/whitespace variants)
    are listed once in the teach-back prompt, consistent with glossary dedup."""
    from app.modules.content.pipeline.graph import package_builder_node

    glossary = [
        {"segment_id": "sec_0", "data": {"term": "Entropy", "definition": "d"}},
        {"segment_id": "sec_0", "data": {"term": "entropy ", "definition": "d2"}},  # dup
        {"segment_id": "sec_0", "data": {"term": "Order", "definition": "d3"}},
    ]
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(glossary=glossary))

    seg0 = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    tb = seg0["teachback_prompt"]
    cover = tb.split("Try to cover:")[1]  # only the concept list, not the title
    assert cover.lower().count("entropy") == 1, "duplicate term listed once in the cover clause"
    assert "Order" in cover


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_missing_all_three_economy_outputs_is_degraded_not_dropped() -> None:
    """Story 2-21: a slide-bearing segment missing complexity AND narration AND
    interventions simultaneously is still KEPT, with all three backfilled."""
    from app.modules.content.pipeline.graph import package_builder_node

    inc_c = [c for c in COMPLEXITY_SCORES if c["segment_id"] != "sec_0"]
    inc_a = [a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"]
    inc_i = [i for i in INTERVENTION_PROMPTS if i["segment_id"] != "sec_0"]
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(
            _base_state(complexity_scores=inc_c, audio_assets=inc_a, intervention_prompts=inc_i)
        )

    package = result["lesson_package"]
    assert len(package["segments"]) == 2
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert seg0["complexity"]["level"] == "medium"
    assert seg0["narration"]["audio_provider"] == "browser"
    assert len(seg0["interventions"]["distraction"]) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_degraded_segments_recorded_in_node_outputs_for_admin() -> None:
    """Story 2-21 (review finding): widespread degradation is surfaced — the
    degraded segment ids are recorded in lesson_jobs.node_outputs, not just a
    per-segment warning."""
    from app.modules.content.pipeline.graph import package_builder_node

    inc_c = [c for c in COMPLEXITY_SCORES if c["segment_id"] != "sec_0"]
    sb, jobs_table, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(_base_state(complexity_scores=inc_c))

    # find the completion write (the one carrying package_builder_degraded)
    rec = None
    for call in jobs_table.update.call_args_list:
        payload = call[0][0]
        if "package_builder_degraded" in payload.get("node_outputs", {}):
            rec = payload["node_outputs"]["package_builder_degraded"]
    assert rec is not None, "degradation must be recorded for admin visibility"
    assert rec["segment_ids"] == ["sec_0"]
    assert rec["total_segments"] == 2
