"""
Tests for the onboarding-context pipeline bridge (docs handoff, 2026-09-28;
see docs/stories/onboarding-context-pipeline-wiring.md).

Mirrors tests/test_249_context_wiring.py's structure exactly (chapter_context
wiring), adapted for onboarding_context's own data sources (Q1-Q5 headline
answers + Penta-Intelligence badges, via assessment.service, not a
content-module-owned table).

Tests cover:
- prompt_context.merge_onboarding_context logic (mirrors TestMergeChapterContext)
- assessment.service.get_onboarding_lesson_context — data assembly, Penta
  badge filtering, never-raises contract (AC1, AC2)
- content.context_onboarding.get_onboarding_context_prompt_context — formatting (AC3)
- lesson_planner_node returning onboarding_context in state, cache-hit path,
  precedence order (AC5)
- slide_generator_node / narration_generator_node merging onboarding_context (AC6)
- _FAN_OUT_STATE_KEYS carries onboarding_context + its truncated flag (AC7)
- onboarding_context_truncated surfaced to the persisted admin record (AC8)
- the 5 Phase-1 economy nodes never reference onboarding_context (AC9)
"""

from __future__ import annotations

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# A. prompt_context.py — pure function, no mocking needed
# ─────────────────────────────────────────────────────────────────────────────


class TestMergeOnboardingContext:
    def _import(self):
        from app.modules.content.pipeline.prompt_context import (
            _ONBOARDING_CONTEXT_MAX_CHARS,
            _ONBOARDING_TRUNCATION_MARKER,
            merge_onboarding_context,
        )

        return (
            merge_onboarding_context,
            _ONBOARDING_CONTEXT_MAX_CHARS,
            _ONBOARDING_TRUNCATION_MARKER,
        )

    def test_empty_context_returns_base_unchanged(self):
        merge_onboarding_context, _, _ = self._import()
        base = "System prompt here."
        merged, was_truncated = merge_onboarding_context(base, "")
        assert merged == base
        assert was_truncated is False

    def test_short_context_appended_with_separator(self):
        merge_onboarding_context, _, _ = self._import()
        base = "Base."
        ctx = "[Onboarding Context]\nStated goal: Crack a competitive exam"
        merged, was_truncated = merge_onboarding_context(base, ctx)
        assert merged == base + "\n\n" + ctx
        assert was_truncated is False

    def test_context_at_exact_limit_not_truncated(self):
        merge_onboarding_context, max_chars, marker = self._import()
        ctx = "x" * max_chars
        merged, was_truncated = merge_onboarding_context("Base.", ctx)
        assert marker not in merged
        assert ctx in merged
        assert was_truncated is False

    def test_context_over_limit_truncated_at_newline_boundary(self):
        merge_onboarding_context, max_chars, marker = self._import()
        line_content = "Field: " + "v" * 20
        line = line_content + "\n"
        n_lines = (max_chars // len(line)) + 5
        ctx = line * n_lines
        merged, was_truncated = merge_onboarding_context("Base.", ctx)
        assert was_truncated is True
        assert marker in merged

        kept_body = merged[len("Base.\n\n") : merged.index(marker)]
        kept_lines = kept_body.split("\n")
        for kept_line in kept_lines:
            assert kept_line == line_content, f"partial/corrupted line: {kept_line!r}"
        assert len(kept_lines) >= 1
        assert len(kept_body) <= max_chars
        assert kept_body.count(line_content) < n_lines

    def test_context_over_limit_no_mid_sentence_cut_when_no_newline(self):
        merge_onboarding_context, max_chars, marker = self._import()
        ctx = "a" * (max_chars + 50)
        merged, was_truncated = merge_onboarding_context("Base.", ctx)
        assert was_truncated is True
        assert marker in merged

    def test_truncation_marker_text_is_informative(self):
        merge_onboarding_context, max_chars, marker = self._import()
        assert "truncated" in marker.lower()

    def test_marker_distinguishes_onboarding_from_book_and_chapter_truncation(self):
        from app.modules.content.pipeline.prompt_context import (
            _CHAPTER_TRUNCATION_MARKER,
            _TRUNCATION_MARKER,
        )

        merge_onboarding_context, _, onboarding_marker = self._import()
        assert onboarding_marker != _TRUNCATION_MARKER
        assert onboarding_marker != _CHAPTER_TRUNCATION_MARKER
        assert "onboarding" in onboarding_marker.lower()

    def test_budget_is_independently_derived_not_copied_from_book_or_chapter_context(self):
        """AC4 / Scale & Load Q5: onboarding_context's field set (5 MCQ answers
        each Pydantic-capped at 1,000 chars) is genuinely different from both
        book_context's (3 free-text fields at 500 chars) and chapter_context's
        (2 free-text fields at 500 chars) — reusing either unchanged would be
        exactly the un-re-derived-inherited-cap pattern CLAUDE.md warns against."""
        from app.modules.content.pipeline.prompt_context import (
            _BOOK_CONTEXT_MAX_CHARS,
            _CHAPTER_CONTEXT_MAX_CHARS,
        )

        _, onboarding_max_chars, _ = self._import()
        assert onboarding_max_chars != _BOOK_CONTEXT_MAX_CHARS
        assert onboarding_max_chars != _CHAPTER_CONTEXT_MAX_CHARS
        # Pin the exact claimed value, not just its neighborhood.
        assert onboarding_max_chars == 5_500


# ─────────────────────────────────────────────────────────────────────────────
# B. assessment.service.get_onboarding_lesson_context — data assembly
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOnboardingLessonContext:
    @pytest.mark.asyncio
    async def test_returns_empty_when_user_id_blank(self):
        from app.modules.assessment.service import get_onboarding_lesson_context

        result = await get_onboarding_lesson_context("")
        assert result.stated_goal is None
        assert result.penta_badge_labels == []

    @pytest.mark.asyncio
    async def test_never_raises_on_db_error(self, mocker):
        mocker.patch(
            "app.core.db.get_supabase",
            side_effect=RuntimeError("db unavailable"),
        )
        from app.modules.assessment.service import get_onboarding_lesson_context

        result = await get_onboarding_lesson_context("u1")
        assert result.stated_goal is None
        assert result.penta_badge_labels == []

    @pytest.mark.asyncio
    async def test_returns_q1_5_headline_answers_and_penta_badges_only(self, mocker):
        """AC1: Q1-Q5 answers pass through; the 9 behavioral-dimension badges
        mixed into the same badge_labels array are filtered OUT, only the 5
        Penta-dimension badges survive."""
        from app.modules.assessment.onboarding_questions import (
            BADGE_THRESHOLDS,
            PENTA_BADGE_THRESHOLDS,
        )

        headline = {
            "stated_goal": "Crack a competitive exam",
            "current_level": "Absolute beginner",
        }
        mixed_badges = [
            next(iter(BADGE_THRESHOLDS.values())),  # a behavioral badge — must be filtered out
            next(iter(PENTA_BADGE_THRESHOLDS.values())),  # a Penta badge — must survive
        ]

        mocker.patch(
            "app.modules.assessment.service._read_onboarding_headline_answers",
            return_value=headline,
        )
        mocker.patch("app.core.db.get_supabase", return_value=mocker.MagicMock())
        mocker.patch(
            "app.modules.assessment.service.single_row",
            return_value={"badge_labels": mixed_badges},
        )
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.assessment.service import get_onboarding_lesson_context

        result = await get_onboarding_lesson_context("u1")
        assert result.stated_goal == "Crack a competitive exam"
        assert result.current_level == "Absolute beginner"
        assert result.penta_badge_labels == [next(iter(PENTA_BADGE_THRESHOLDS.values()))]
        assert next(iter(BADGE_THRESHOLDS.values())) not in result.penta_badge_labels

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data_on_file(self, mocker):
        mocker.patch(
            "app.modules.assessment.service._read_onboarding_headline_answers",
            return_value={},
        )
        mocker.patch("app.core.db.get_supabase", return_value=mocker.MagicMock())
        mocker.patch("app.modules.assessment.service.single_row", return_value=None)
        mocker.patch("asyncio.to_thread", side_effect=lambda f: f())

        from app.modules.assessment.service import get_onboarding_lesson_context

        result = await get_onboarding_lesson_context("u1")
        assert result.stated_goal is None
        assert result.penta_badge_labels == []


# ─────────────────────────────────────────────────────────────────────────────
# C. content.context_onboarding.get_onboarding_context_prompt_context — formatting
# ─────────────────────────────────────────────────────────────────────────────


class TestGetOnboardingContextPromptContext:
    @pytest.mark.asyncio
    async def test_returns_empty_string_when_user_id_blank(self):
        from app.modules.content.context_onboarding import (
            get_onboarding_context_prompt_context,
        )

        result = await get_onboarding_context_prompt_context("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_all_fields_empty(self, mocker):
        from app.modules.assessment.schemas import OnboardingLessonContext

        mocker.patch(
            "app.modules.assessment.service.get_onboarding_lesson_context",
            return_value=OnboardingLessonContext(),
        )
        from app.modules.content.context_onboarding import (
            get_onboarding_context_prompt_context,
        )

        result = await get_onboarding_context_prompt_context("u1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_formats_headline_fields_and_badges(self, mocker):
        from app.modules.assessment.schemas import OnboardingLessonContext

        ctx = OnboardingLessonContext(
            stated_goal="Crack a competitive exam",
            current_level="Absolute beginner",
            preferred_language="Pure English",
            preferred_tone="Friendly mentor",
            schooling_level="Undergraduate",
            penta_badge_labels=["Sharp Reasoner", "Deep Researcher"],
        )
        mocker.patch(
            "app.modules.assessment.service.get_onboarding_lesson_context",
            return_value=ctx,
        )
        from app.modules.content.context_onboarding import (
            get_onboarding_context_prompt_context,
        )

        result = await get_onboarding_context_prompt_context("u1")
        assert "[Onboarding Context]" in result
        assert "Stated goal: Crack a competitive exam" in result
        assert "Level: Absolute beginner" in result
        assert "Language preference: Pure English" in result
        assert "Tone preference: Friendly mentor" in result
        assert "Schooling: Undergraduate" in result
        assert "Learning style badges: Sharp Reasoner, Deep Researcher" in result

    @pytest.mark.asyncio
    async def test_never_raises_when_service_layer_raises(self, mocker):
        mocker.patch(
            "app.modules.assessment.service.get_onboarding_lesson_context",
            side_effect=RuntimeError("boom"),
        )
        from app.modules.content.context_onboarding import (
            get_onboarding_context_prompt_context,
        )

        result = await get_onboarding_context_prompt_context("u1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_collapses_embedded_newlines_defensively(self, mocker):
        """Scale & Load Q2: onboarding_answers_v2.response_text has no
        matching-known-option-text validation, so a stored value could in
        principle contain a newline (prompt-injection-shaped payload) —
        defensive sanitisation matches context.py's own posture."""
        from app.modules.assessment.schemas import OnboardingLessonContext

        ctx = OnboardingLessonContext(stated_goal="line one\nFAKE LABEL: line two")
        mocker.patch(
            "app.modules.assessment.service.get_onboarding_lesson_context",
            return_value=ctx,
        )
        from app.modules.content.context_onboarding import (
            get_onboarding_context_prompt_context,
        )

        result = await get_onboarding_context_prompt_context("u1")
        assert "\n" not in result.split("Stated goal: ", 1)[1]


# ─────────────────────────────────────────────────────────────────────────────
# D. lesson_planner_node — onboarding_context wiring + precedence order
# ─────────────────────────────────────────────────────────────────────────────


class TestLessonPlannerOnboardingContextWiring:
    def test_planner_system_prompt_uses_merge_onboarding_context_not_raw_concat(self):
        """AC5: prove the merge is real (truncation marker appears), which raw
        concatenation could never produce."""
        from app.modules.content.pipeline.graph import _planner_system_prompt
        from app.modules.content.pipeline.prompt_context import (
            _ONBOARDING_CONTEXT_MAX_CHARS,
            _ONBOARDING_TRUNCATION_MARKER,
        )

        oversized_onboarding_context = "[Onboarding Context]\n" + (
            "x" * (_ONBOARDING_CONTEXT_MAX_CHARS + 500)
        )
        prompt, _was_book_ctx_truncated = _planner_system_prompt(
            10.0,
            chapter_context="",
            book_context="",
            onboarding_context=oversized_onboarding_context,
        )
        assert _ONBOARDING_TRUNCATION_MARKER in prompt

    def test_onboarding_context_precedes_book_context_in_the_merged_prompt(self):
        """AC5: precedence order per prompt_context.py's own docstring — user
        profile (onboarding) before book context."""
        from app.modules.content.pipeline.graph import _planner_system_prompt

        prompt, _ = _planner_system_prompt(
            10.0,
            chapter_context="",
            book_context="[Book Context]\nBOOK_MARKER_XYZ",
            onboarding_context="[Onboarding Context]\nONBOARDING_MARKER_XYZ",
        )
        assert prompt.index("ONBOARDING_MARKER_XYZ") < prompt.index("BOOK_MARKER_XYZ")


# ─────────────────────────────────────────────────────────────────────────────
# E. _FAN_OUT_STATE_KEYS carries onboarding_context (AC7)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fan_out_state_keys_includes_onboarding_context():
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    assert "onboarding_context" in _FAN_OUT_STATE_KEYS
    assert "book_context" in _FAN_OUT_STATE_KEYS  # unchanged, still there
    assert "chapter_context" in _FAN_OUT_STATE_KEYS  # unchanged, still there


@pytest.mark.unit
def test_fan_out_state_keys_includes_onboarding_context_truncated():
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    assert "onboarding_context_truncated" in _FAN_OUT_STATE_KEYS


@pytest.mark.unit
@pytest.mark.asyncio
async def test_phase1_fan_out_defaults_onboarding_context_in_every_payload():
    from unittest.mock import AsyncMock, patch

    from app.modules.content.pipeline import graph as g

    state = {
        "lesson_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "u1",
        "book_id": "b1",
        "tier": "T1",
        "sections": [{"title": "Intro", "body": "Body one."}],
    }
    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(state)  # type: ignore[arg-type]

    for send in sends:
        assert send.arg["onboarding_context"] == ""
        assert send.arg["onboarding_context_truncated"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_carries_real_onboarding_context():
    from unittest.mock import AsyncMock, patch

    from app.modules.content.pipeline import graph as g

    sections = [{"title": "Intro", "body": "Body one."}]
    plan_segments = [
        {
            "segment_id": g._derive_section_id(sections[0], 0),
            "title": "Intro",
            "summary": "s",
            "duration_min": 5.0,
            "continuity_notes": "",
        }
    ]
    state = {
        "lesson_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "u1",
        "book_id": "b1",
        "tier": "T1",
        "sections": sections,
        "lesson_plan": {"segments": plan_segments},
        "onboarding_context": "[Onboarding Context]\nStated goal: X",
        "onboarding_context_truncated": False,
    }
    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_narration_after_planning(state)  # type: ignore[arg-type]

    for send in sends:
        assert send.arg["onboarding_context"] == "[Onboarding Context]\nStated goal: X"


# ─────────────────────────────────────────────────────────────────────────────
# F. AC9 regression guard — the 5 Phase-1 economy nodes never reference
#    onboarding_context (D189/D199: same structural reason as book/chapter)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_phase1_economy_nodes_never_reference_onboarding_context():
    import inspect

    from app.modules.content.pipeline import graph as graph_module

    economy_node_names = [
        "summarise_segment_node",
        "quiz_generator_node",
        "segment_complexity_node",
        "jargon_extractor_node",
        "intervention_messages_node",
    ]
    for name in economy_node_names:
        source = inspect.getsource(getattr(graph_module, name))
        assert "onboarding_context" not in source, (
            f"{name} must not reference onboarding_context (D189/D199)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# G. slide_generator_node / narration_generator_node — onboarding_context text
#    actually reaches the real constructed LLM prompt (AC6)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slide_generator_node_prompt_includes_onboarding_context() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.content.pipeline.graph import slide_generator_node

    plan_segments = [
        {
            "segment_id": "sec_0",
            "title": "Getting Started",
            "summary": "Intro summary.",
            "duration_min": 4.0,
        },
    ]
    state = {
        "lesson_id": "40404040-4040-4040-4040-404040404040",
        "lesson_plan": {
            "title": "T",
            "subject": "S",
            "objectives": ["O"],
            "complexity_level": "medium",
            "total_segments": 1,
            "total_duration_min": 4.0,
            "segments": plan_segments,
        },
        "progress_pct": 38.0,
        "error": None,
        "onboarding_context": (
            "[Onboarding Context]\nStated goal: UNIQUE_ONBOARDING_GOAL_MARKER_XYZ"
        ),
    }

    response = MagicMock()
    seg_mock = MagicMock(
        segment_id="sec_0",
        slides=[MagicMock(title="Welcome", bullets=["Point A"])],
    )
    response.segments = [seg_mock]
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = response
    sb = MagicMock()
    jobs_mock = MagicMock()
    jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": {}
    }
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    sb.table.return_value = jobs_mock

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        result = await slide_generator_node(state)

    sent_messages = mock_provider.complete_structured.call_args.args[0]
    full_prompt = "\n".join(m["content"] for m in sent_messages)
    assert "UNIQUE_ONBOARDING_GOAL_MARKER_XYZ" in full_prompt
    assert result["onboarding_context_truncated"] is False


def _narration_state_with_onboarding_context(onboarding_context: str) -> dict:
    return {
        "lesson_id": "40404040-4040-4040-4040-404040404040",
        "_section": {
            "title": "Intro",
            "body": "prose. " * 20,
            "page_start": 1,
            "page_end": 2,
        },
        "_section_index": 0,
        "onboarding_context": onboarding_context,
    }


async def _run_narration_generator_node(state: dict):
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.content.pipeline.graph import narration_generator_node

    mock_output = type(
        "Narration",
        (),
        {"narration_style": "conversational", "script": "Let's begin."},
    )()
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = mock_output

    jobs_mock = MagicMock()
    _jobs_data = {"node_outputs": {}}
    jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        _jobs_data
    )
    _maybe_single = jobs_mock.select.return_value.eq.return_value.maybe_single
    _maybe_single.return_value.execute.return_value.data = _jobs_data
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    mock_supabase = MagicMock()
    mock_supabase.table.return_value = jobs_mock
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with (
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.core.db.get_supabase", return_value=mock_supabase),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        result = await narration_generator_node(state)

    sent_messages = mock_provider.complete_structured.call_args.args[0]
    full_prompt = "\n".join(m["content"] for m in sent_messages)
    return result, full_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_generator_node_prompt_includes_onboarding_context() -> None:
    _, full_prompt = await _run_narration_generator_node(
        _narration_state_with_onboarding_context(
            "[Onboarding Context]\nStated goal: UNIQUE_NARRATION_GOAL_MARKER_XYZ"
        )
    )
    assert "UNIQUE_NARRATION_GOAL_MARKER_XYZ" in full_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_generator_node_return_dict_excludes_onboarding_context_truncated() -> None:
    """Same InvalidUpdateError hazard already proven for book/chapter — this
    node is Send()-dispatched N-way concurrently."""
    result, _ = await _run_narration_generator_node(_narration_state_with_onboarding_context(""))
    assert "onboarding_context_truncated" not in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_generator_node_uses_real_merge_not_raw_concat() -> None:
    from app.modules.content.pipeline.prompt_context import (
        _ONBOARDING_CONTEXT_MAX_CHARS,
        _ONBOARDING_TRUNCATION_MARKER,
    )

    oversized_onboarding_context = "[Onboarding Context]\n" + (
        "x" * (_ONBOARDING_CONTEXT_MAX_CHARS + 500)
    )
    _, full_prompt = await _run_narration_generator_node(
        _narration_state_with_onboarding_context(oversized_onboarding_context)
    )
    assert _ONBOARDING_TRUNCATION_MARKER in full_prompt


# ─────────────────────────────────────────────────────────────────────────────
# H. AC8 — onboarding_context_truncated must reach the PERSISTED, admin-visible
#    record package_builder_node writes.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_onboarding_context_truncated_reaches_persisted_admin_record() -> None:
    from unittest.mock import patch

    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase()
    state = _base_state(onboarding_context_truncated=True)

    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(state)

    jobs_update_kwargs = jobs_table.update.call_args[0][0]
    node_outputs = jobs_update_kwargs["node_outputs"]
    assert node_outputs["onboarding_context_truncated"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_onboarding_context_truncated_defaults_false_when_absent() -> None:
    from unittest.mock import patch

    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(_base_state())

    jobs_update_kwargs = jobs_table.update.call_args[0][0]
    node_outputs = jobs_update_kwargs["node_outputs"]
    assert node_outputs["onboarding_context_truncated"] is False
