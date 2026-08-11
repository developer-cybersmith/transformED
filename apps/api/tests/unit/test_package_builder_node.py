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

# Story 2-31: the flat shape narration_generator_node emits. Derived from
# AUDIO_ASSETS so each segment's script is DISTINCT — an identical script for
# every segment would let an AC-1 assertion pass for the wrong reason.
NARRATION_SCRIPTS: list[dict[str, Any]] = [
    {"segment_id": a["segment_id"], "script": a["data"]["script"]} for a in AUDIO_ASSETS
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
        "narration_scripts": NARRATION_SCRIPTS,
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
async def test_malformed_slide_entry_that_is_not_a_dict_is_skipped_not_crashed() -> None:
    """D32: `_group_by_segment_id` must skip a non-dict entry (e.g. a bare string
    from a schema-drifted checkpoint), mirroring `_index_by_segment_id`'s existing
    check (Story 2-31). Pre-fix, `item.get("segment_id")` on a plain string raises
    AttributeError and crashes package_builder_node after 100% of the lesson's
    spend -- this must not happen; the other, well-formed slide for sec_0 survives."""
    from app.modules.content.pipeline.graph import package_builder_node

    malformed = "not-a-dict-slide-entry"
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(slides=[*SLIDES, malformed]))

    package = result["lesson_package"]
    assert len(package["segments"]) == 2, "both segments survive; the malformed entry is skipped"
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert len(seg0["slides"]) == 1, "only the real slide, the malformed entry did not get in"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_slide_entry_missing_data_key_is_skipped_not_crashed() -> None:
    """D32: a dict entry with a segment_id but no "data" key must be skipped, not
    a raw KeyError from `item["data"]`. Docstring says "same defensive-skip
    philosophy as _index_by_segment_id" -- before this fix, that claim was false."""
    from app.modules.content.pipeline.graph import package_builder_node

    malformed = {"segment_id": "sec_0"}  # no "data" key at all
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(slides=[*SLIDES, malformed]))

    package = result["lesson_package"]
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert len(seg0["slides"]) == 1, "only the real slide; the missing-data entry was skipped"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_slide_entry_with_non_dict_data_value_is_skipped_not_crashed() -> None:
    """D32: a "data" value that is present but not a dict (e.g. a string) must be
    skipped, mirroring `_index_by_segment_id`'s value-type check (graph.py:4015-27).
    Pre-fix this string reaches downstream code that does `{**value}`-shaped
    access on it and crashes."""
    from app.modules.content.pipeline.graph import package_builder_node

    malformed = {"segment_id": "sec_1", "data": "not-a-dict-value"}
    sb, _, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(slides=[*SLIDES, malformed]))

    package = result["lesson_package"]
    seg1 = next(s for s in package["segments"] if s["segment_id"] == "sec_1")
    assert len(seg1["slides"]) == 1, "only the real slide; the non-dict data entry was skipped"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_with_only_slide_malformed_drops_segment_and_total_segments_matches_shipped(
    caplog: Any,
) -> None:
    """D32 review round (Scale & Load Hunter — CONFIRMED, most severe finding).

    When a segment's ONLY slide entry is malformed (not one bad entry among
    several good ones — the whole segment's supply), the pre-existing
    zero-slides path drops the entire segment. Before this fix,
    `metadata.total_segments` still read the stale planning-time count
    (`lesson_plan["total_segments"]`), so the shipped package claimed 2
    segments while containing 1 — the same "reports success while being
    wrong" shape as the book-scale 4%-of-the-book defect, at segment
    granularity. `total_segments` must always equal the real, just-built
    `len(segments)`, and the drop must be recorded in
    `package_builder_degraded.dropped_segment_ids` (distinct from
    `segment_ids`, which is for segments that shipped degraded, not dropped).
    """
    from app.modules.content.pipeline.graph import package_builder_node

    only_bad_for_sec0 = [
        s if s["segment_id"] != "sec_0" else {"segment_id": "sec_0", "data": "not-a-dict"}
        for s in SLIDES
    ]
    sb, jobs_table, _ = _mock_supabase()

    with caplog.at_level("WARNING"):
        with patch("app.core.db.get_supabase", return_value=sb):
            result = await package_builder_node(_base_state(slides=only_bad_for_sec0))

    package = result["lesson_package"]
    assert len(package["segments"]) == 1
    assert package["segments"][0]["segment_id"] == "sec_1"
    assert package["metadata"]["total_segments"] == 1, (
        "total_segments must be the real shipped count, not the stale lesson_plan value (2)"
    )
    assert any("ALL were malformed" in r.message for r in caplog.records), (
        "the malformed-slides drop reason must actually be logged, not just asserted"
    )

    rec = None
    for call in jobs_table.update.call_args_list:
        payload = call[0][0]
        if "package_builder_degraded" in payload.get("node_outputs", {}):
            rec = payload["node_outputs"]["package_builder_degraded"]
    assert rec is not None
    assert rec["dropped_segment_ids"] == ["sec_0"], (
        "distinct from segment_ids (degraded, not dropped)"
    )
    assert rec["total_segments"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_quiz_entries_for_a_segment_malformed_is_degraded_not_silently_empty() -> None:
    """D32 review round (Edge Case Hunter + Scale & Load Hunter, independently
    confirmed): a segment whose quiz entries all fail the defensive checks
    must NOT be indistinguishable from a segment that legitimately has zero
    quiz questions (`Segment.quiz` has no `min_length`, per
    `test_segment_with_zero_quiz_and_jargon_still_included`). The segment
    survives (quiz is not mandatory like slides), but must appear in the
    admin degradation aggregate — the same visibility already given to a
    missing complexity/narration/interventions entry."""
    from app.modules.content.pipeline.graph import package_builder_node

    malformed_quiz = [{"segment_id": "sec_0", "data": "not-a-dict"}]
    sb, jobs_table, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(quiz_questions=malformed_quiz))

    package = result["lesson_package"]
    seg0 = next(s for s in package["segments"] if s["segment_id"] == "sec_0")
    assert seg0["quiz"] == [], "the malformed entry itself must not appear"

    rec = None
    for call in jobs_table.update.call_args_list:
        payload = call[0][0]
        if "package_builder_degraded" in payload.get("node_outputs", {}):
            rec = payload["node_outputs"]["package_builder_degraded"]
    assert rec is not None
    assert "sec_0" in rec["segment_ids"], (
        "a segment that had quiz entries but lost all of them must be flagged degraded"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_jargon_entries_for_a_segment_malformed_is_degraded_not_silently_empty() -> None:
    """D32 review round: same as the quiz case, for glossary/jargon."""
    from app.modules.content.pipeline.graph import package_builder_node

    malformed_glossary = [{"segment_id": "sec_1", "data": "not-a-dict"}]
    sb, jobs_table, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(glossary=malformed_glossary))

    package = result["lesson_package"]
    seg1 = next(s for s in package["segments"] if s["segment_id"] == "sec_1")
    assert seg1["jargon"] == []

    rec = None
    for call in jobs_table.update.call_args_list:
        payload = call[0][0]
        if "package_builder_degraded" in payload.get("node_outputs", {}):
            rec = payload["node_outputs"]["package_builder_degraded"]
    assert rec is not None
    assert "sec_1" in rec["segment_ids"], (
        "a segment that had jargon entries but lost all of them must be flagged degraded"
    )


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
async def test_missing_chapter_id_raises_diagnostic_not_model_validate_failure() -> None:
    """AC-9 kept, D33 (Story 1-13 AC7) inverted.

    The failure must still propagate uncaught — that half is unchanged. What
    changed is WHICH failure. Before Story 1-13 the `or ""` default let an
    absent chapter_id travel all the way into `LessonPackage.model_validate()`
    and surface as a bare pydantic ValidationError that named neither the
    lesson nor the missing upstream node — after every LLM/TTS/image call had
    already been billed. AC7 replaces it with a diagnostic raise that names the
    lesson and what is missing.
    """
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
        with pytest.raises(RuntimeError) as excinfo:
            await package_builder_node(_base_state())

    assert not isinstance(excinfo.value, ValidationError), (
        "D33: an absent chapter_id must no longer reach LessonPackage.model_validate()"
    )
    message = str(excinfo.value)
    assert "chapter_id" in message, "the diagnostic must name what is missing"
    assert FAKE_LESSON_ID in message, "the diagnostic must name the lesson"

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
    """The chunk-checkpoint fallback must handle both 'chunk absent' and
    'chunk present without chapter_id' identically.

    Story 1-13 AC7 changes what "identically" means: both now raise the same
    early diagnostic RuntimeError, where both previously fell through the `or ""`
    default into LessonPackage's UUID validation. The equivalence being asserted
    is the point of the test and is unchanged."""
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
        with pytest.raises(RuntimeError) as excinfo:
            await package_builder_node(_base_state())

    assert not isinstance(excinfo.value, ValidationError)
    assert "chapter_id" in str(excinfo.value)

    lessons_table.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_book_id_raises_diagnostic_not_model_validate_failure() -> None:
    """book_id follows the same required-UUID path as chapter_id — a missing
    book_id must also stop the node, not silently produce an invalid 'valid'
    package.

    Story 1-13 AC7 (D33) inverts only the mechanism: this used to assert the
    SYMPTOM — an empty string reaching `LessonPackage.model_validate()` and
    blowing up as a bare pydantic ValidationError at the FINAL node, after the
    whole pipeline had been paid for. It now asserts the diagnostic raise that
    replaced it, which names the lesson and the missing field.
    """
    from app.modules.content.pipeline.graph import package_builder_node

    sb, _, lessons_table = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        with pytest.raises(RuntimeError) as excinfo:
            await package_builder_node(_base_state(book_id=""))

    assert not isinstance(excinfo.value, ValidationError), (
        "D33: an absent book_id must no longer reach LessonPackage.model_validate()"
    )
    message = str(excinfo.value)
    assert "book_id" in message, "the diagnostic must name what is missing"
    assert FAKE_LESSON_ID in message, "the diagnostic must name the lesson"

    lessons_table.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chapter_id_on_state_is_used_without_any_chunk_checkpoint() -> None:
    """Story 1-13: chapter_id is a PipelineState field; the chunk checkpoint is
    only a fallback for jobs that started before Phase 5 landed. State alone
    must therefore be sufficient — with node_outputs empty, the package still
    names the state chapter."""
    from app.modules.content.pipeline.graph import package_builder_node

    jobs_table = MagicMock()
    jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": {}  # no chunk checkpoint at all
    }
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

    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state(chapter_id=FAKE_CHAPTER_ID))

    assert result["lesson_package"]["chapter_id"] == FAKE_CHAPTER_ID


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


# ── Story 2-31: narration-script recovery + malformed-entry hardening ─────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_audio_recovers_the_real_script_not_a_blank() -> None:
    """AC-1: only the AUDIO is missing in this degrade path — the script is not.

    Real production repro: tts_node cache-hits a persisted
    node_outputs["tts_node"] == [], so package_builder sees no audio_assets
    entry for a segment while narration_scripts still holds its text.
    """
    from app.modules.content.pipeline.graph import package_builder_node

    state = _base_state(audio_assets=[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"])
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"] == "Entropy measures disorder.", (
        "the segment's OWN script must be recovered from narration_scripts, not blanked"
    )
    assert seg["narration"]["audio_url"] == "", "audio genuinely is missing — that stays empty"
    assert seg["narration"]["audio_provider"] == "browser"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_audio_and_missing_script_degrades_to_empty() -> None:
    """AC-1: narration_generator returns [] on no-summary / LLM-failure /
    pacing-reject. There is genuinely nothing to recover — accept the gap."""
    from app.modules.content.pipeline.graph import package_builder_node

    state = _base_state(
        audio_assets=[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"],
        narration_scripts=[n for n in NARRATION_SCRIPTS if n["segment_id"] != "sec_0"],
    )
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"] == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_whitespace_only_recovered_script_is_treated_as_absent() -> None:
    """AC-1: a whitespace script is not a script."""
    from app.modules.content.pipeline.graph import package_builder_node

    state = _base_state(
        audio_assets=[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"],
        narration_scripts=[{"segment_id": "sec_0", "script": "   \n  "}],
    )
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"] == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recovered_narration_still_gets_estimated_timestamps() -> None:
    """AC-1: the fix must COMPOSE with the Story 2-19 timestamp-estimation block
    that immediately follows, not be overwritten by it."""
    from app.modules.content.pipeline.graph import package_builder_node

    state = _base_state(audio_assets=[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"])
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"], "script survived the timestamp block"
    assert seg["narration"]["timestamps"], "timestamps still estimated for a no-audio segment"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_audio_entry_missing_data_does_not_crash_the_node() -> None:
    """AC-2: _index_by_segment_id used item[value_key], so ONE malformed entry
    raised KeyError and took down the whole node — contradicting the "one bad
    item never crashes the node" guarantee its own docstring makes (AC-5)."""
    from app.modules.content.pipeline.graph import package_builder_node

    broken = [{"segment_id": "sec_0"}, *[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"]]
    state = _base_state(audio_assets=broken)
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    segs = {s["segment_id"]: s for s in result["lesson_package"]["segments"]}
    assert "sec_1" in segs, "the healthy segment must survive a malformed sibling"
    assert segs["sec_0"]["narration"]["script"] == "Entropy measures disorder.", (
        "the malformed segment degrades to no-audio but still recovers its script"
    )


# ── Story 2-31 review round: malformed-entry hardening (AC-2's real guarantee) ─


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_dict_entry_in_a_list_does_not_crash_the_node() -> None:
    """Review finding: AC-2's `.get(value_key)` fix only ever covered the
    dict-missing-key case. An entry that is not a dict AT ALL — a bare string
    from a schema-drifted or hand-edited checkpoint — made the very next
    `item.get("segment_id")` raise AttributeError, killing the node after all
    pipeline spend. The docstring's "one bad item never crashes the whole node"
    guarantee was still false."""
    from app.modules.content.pipeline.graph import package_builder_node

    state = _base_state(
        audio_assets=["not-a-dict", None, 42, *AUDIO_ASSETS],
        narration_scripts=["junk", *NARRATION_SCRIPTS],
        complexity_scores=[None, *COMPLEXITY_SCORES],
        intervention_prompts=[["nested", "list"], *INTERVENTION_PROMPTS],
    )
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    segs = result["lesson_package"]["segments"]
    assert len(segs) == 2, "healthy segments must still be built"
    seg = next(s for s in segs if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"] == "Entropy measures disorder."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_present_but_non_dict_value_degrades_that_segment_only() -> None:
    """Review finding: a `data` key that is PRESENT but not a dict slipped past
    every caller's `is None` degrade test, then blew up on `.get("script")` /
    `{**value}` — the same post-spend crash the KeyError fix was meant to
    eliminate, one branch further down."""
    from app.modules.content.pipeline.graph import package_builder_node

    broken = [
        {"segment_id": "sec_0", "data": "a bare string, not a dict"},
        *[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"],
    ]
    state = _base_state(audio_assets=broken)
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    segs = result["lesson_package"]["segments"]
    bad = next(s for s in segs if s["segment_id"] == "sec_0")
    good = next(s for s in segs if s["segment_id"] == "sec_1")
    # Degraded to the no-audio path — and AC-1 recovery still supplies the script.
    assert bad["narration"]["audio_url"] == ""
    assert bad["narration"]["script"] == "Entropy measures disorder."
    assert good["narration"]["audio_url"].endswith("sec_1.mp3"), "sibling unaffected"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_string_recovered_script_is_treated_as_absent() -> None:
    """Mutation survivor: the `isinstance(raw_script, str)` half of the AC-1
    guard had no test — every fixture supplied a str. Dropping it turns graceful
    degradation into an AttributeError inside package_builder_node."""
    from app.modules.content.pipeline.graph import package_builder_node

    for bad_script in (None, 123, {"text": "nope"}, ["a", "b"]):
        state = _base_state(
            audio_assets=[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"],
            narration_scripts=[
                {"segment_id": "sec_0", "script": bad_script},
                *[n for n in NARRATION_SCRIPTS if n["segment_id"] != "sec_0"],
            ],
        )
        sb, _, _ = _mock_supabase()
        with patch("app.core.db.get_supabase", return_value=sb):
            result = await package_builder_node(state)  # type: ignore[arg-type]

        seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
        assert seg["narration"]["script"] == "", f"{bad_script!r} must degrade, not propagate"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_segment_id_in_narration_scripts_keeps_last() -> None:
    """AC-1 names this case explicitly ("duplicate segment_id — last wins") but
    it shipped with zero coverage. narration_scripts is the ONLY caller passing
    no value_key, so the pre-existing duplicate test on complexity_scores does
    not exercise this branch."""
    from app.modules.content.pipeline.graph import package_builder_node

    state = _base_state(
        audio_assets=[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"],
        narration_scripts=[
            {"segment_id": "sec_0", "script": "FIRST — should be overwritten"},
            {"segment_id": "sec_0", "script": "LAST — this one wins"},
            *[n for n in NARRATION_SCRIPTS if n["segment_id"] != "sec_0"],
        ],
    )
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"] == "LAST — this one wins"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audio_entry_present_but_script_blank_still_recovers() -> None:
    """Review finding: recovery fired only under `if narration is None`. A
    tts_node checkpoint persisted under an older shape can carry an audio entry
    whose script is blank — the `is None` branch never fires, so the segment
    shipped empty narration even though the text was sitting in
    narration_script_by_id."""
    from app.modules.content.pipeline.graph import package_builder_node

    scriptless = [
        {
            "segment_id": "sec_0",
            "data": {
                "script": "",
                "audio_url": f"{FAKE_LESSON_ID}/sec_0.mp3",
                "audio_provider": "sarvam",
                "timestamps": [],
            },
        },
        *[a for a in AUDIO_ASSETS if a["segment_id"] != "sec_0"],
    ]
    state = _base_state(audio_assets=scriptless)
    sb, _, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(state)  # type: ignore[arg-type]

    seg = next(s for s in result["lesson_package"]["segments"] if s["segment_id"] == "sec_0")
    assert seg["narration"]["script"] == "Entropy measures disorder.", (
        "the script must be recovered even though the audio entry itself exists"
    )
    assert seg["narration"]["audio_url"].endswith("sec_0.mp3"), "real audio must be preserved"
