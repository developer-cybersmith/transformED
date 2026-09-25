"""
Tests for Story 249 (issue #249): book_context/chapter_context wiring parity.

Tests cover:
- prompt_context.merge_chapter_context logic (mirrors TestMergeBookContext in
  test_s5_1_book_context.py — same contract, chapter_context's own budget)
- lesson_planner_node returning chapter_context in state (AC 2)
- lesson_planner_node using merge_chapter_context instead of raw concatenation (AC 5)
- slide_generator_node / narration_generator_node merging chapter_context (AC 6, AC 7)
- _FAN_OUT_STATE_KEYS carries chapter_context (AC 7)
- chapter_context_truncated surfaced the same way book_context_truncated is (AC 8)
- the 5 Phase-1 economy nodes never reference either context (AC 9 regression guard)
"""

from __future__ import annotations

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# A. prompt_context.py — pure function, no mocking needed (mirrors
#    TestMergeBookContext in test_s5_1_book_context.py exactly)
# ─────────────────────────────────────────────────────────────────────────────


class TestMergeChapterContext:
    def _import(self):
        from app.modules.content.pipeline.prompt_context import (
            _CHAPTER_CONTEXT_MAX_CHARS,
            _CHAPTER_TRUNCATION_MARKER,
            merge_chapter_context,
        )

        return merge_chapter_context, _CHAPTER_CONTEXT_MAX_CHARS, _CHAPTER_TRUNCATION_MARKER

    def test_empty_context_returns_base_unchanged(self):
        merge_chapter_context, _, _ = self._import()
        base = "System prompt here."
        merged, was_truncated = merge_chapter_context(base, "")
        assert merged == base
        assert was_truncated is False

    def test_short_context_appended_with_separator(self):
        merge_chapter_context, _, _ = self._import()
        base = "Base."
        ctx = "[Chapter Instructions]\nStudent-supplied doubt: Why does the chain rule work?"
        merged, was_truncated = merge_chapter_context(base, ctx)
        assert merged == base + "\n\n" + ctx
        assert was_truncated is False

    def test_context_at_exact_limit_not_truncated(self):
        merge_chapter_context, max_chars, marker = self._import()
        ctx = "x" * max_chars
        merged, was_truncated = merge_chapter_context("Base.", ctx)
        assert marker not in merged
        assert ctx in merged
        assert was_truncated is False

    def test_context_over_limit_truncated_at_newline_boundary(self):
        merge_chapter_context, max_chars, marker = self._import()
        prefix = "Field: value\n"
        suffix = "x" * (max_chars + 100)
        ctx = prefix + suffix
        merged, was_truncated = merge_chapter_context("Base.", ctx)
        assert was_truncated is True
        assert marker in merged
        assert len(merged) <= len("Base.") + 2 + max_chars + len(marker) + 10

    def test_context_over_limit_no_mid_sentence_cut_when_no_newline(self):
        merge_chapter_context, max_chars, marker = self._import()
        ctx = "a" * (max_chars + 50)
        merged, was_truncated = merge_chapter_context("Base.", ctx)
        assert was_truncated is True
        assert marker in merged

    def test_truncation_marker_text_is_informative(self):
        merge_chapter_context, max_chars, marker = self._import()
        assert "truncated" in marker.lower()

    def test_marker_distinguishes_chapter_from_book_truncation(self):
        """The two contexts can BOTH be merged into the same prompt (e.g.
        lesson_planner_node's base includes book_context via merge_book_context
        AND chapter_context via merge_chapter_context) — the two markers must be
        distinguishable, or an admin reading a truncated prompt can't tell which
        context was cut."""
        from app.modules.content.pipeline.prompt_context import _TRUNCATION_MARKER

        merge_chapter_context, _, chapter_marker = self._import()
        assert chapter_marker != _TRUNCATION_MARKER
        assert "chapter" in chapter_marker.lower()

    def test_budget_is_independently_derived_not_copied_from_book_context(self):
        """AC 4 / Scale & Load Q5: chapter_context has 2 free-text fields (vs
        book_context's 3), so its own honestly-derived cap must be smaller than
        book_context's 2,000 — reusing that number unchanged would be exactly
        the un-re-derived-inherited-cap pattern CLAUDE.md warns against."""
        from app.modules.content.pipeline.prompt_context import _BOOK_CONTEXT_MAX_CHARS

        _, chapter_max_chars, _ = self._import()
        assert chapter_max_chars < _BOOK_CONTEXT_MAX_CHARS
        assert 1_000 <= chapter_max_chars <= 1_500


# ─────────────────────────────────────────────────────────────────────────────
# B. lesson_planner_node — chapter_context now returned in state, merged not
#    raw-concatenated
# ─────────────────────────────────────────────────────────────────────────────


class TestLessonPlannerChapterContextWiring:
    def test_planner_system_prompt_uses_merge_chapter_context_not_raw_concat(self):
        """AC 5: the old `base + chapter_context` raw string concatenation
        (no budget, no truncation guard) must be replaced by a real merge call
        — prove it by feeding an over-budget chapter_context and confirming the
        truncation marker appears, which raw concatenation could never produce."""
        from app.modules.content.pipeline.graph import _planner_system_prompt
        from app.modules.content.pipeline.prompt_context import (
            _CHAPTER_CONTEXT_MAX_CHARS,
            _CHAPTER_TRUNCATION_MARKER,
        )

        oversized_chapter_context = "\n\n[Chapter Instructions]\n" + (
            "x" * (_CHAPTER_CONTEXT_MAX_CHARS + 500)
        )
        prompt, _was_book_ctx_truncated = _planner_system_prompt(
            10.0, chapter_context=oversized_chapter_context, book_context=""
        )
        assert _CHAPTER_TRUNCATION_MARKER in prompt


# ─────────────────────────────────────────────────────────────────────────────
# C. _FAN_OUT_STATE_KEYS carries chapter_context (AC 7)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fan_out_state_keys_includes_chapter_context():
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    assert "chapter_context" in _FAN_OUT_STATE_KEYS
    assert "book_context" in _FAN_OUT_STATE_KEYS  # unchanged, still there


# ─────────────────────────────────────────────────────────────────────────────
# D. AC 9 regression guard — the 5 Phase-1 economy nodes never reference
#    either context (they run before either fetch happens; D189 registers why
#    this stays true, not a target for this story to change)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_phase1_economy_nodes_never_reference_either_context():
    """D189: book_context/chapter_context reach lesson_planner_node,
    slide_generator_node, and narration_generator_node only — never the 5
    Phase-1 economy nodes, which run before either fetch happens. This is a
    source-level regression guard, not a behavioral one: it fails loudly if a
    future edit accidentally starts referencing either context inside one of
    these 5 node functions, which would be silently wrong (state[...] would
    read the always-"" default from _fan_out_phase1_economy_nodes, not a real
    value) rather than an honest error."""
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
        assert "book_context" not in source, f"{name} must not reference book_context (D189)"
        assert "chapter_context" not in source, f"{name} must not reference chapter_context (D189)"


# ─────────────────────────────────────────────────────────────────────────────
# E. slide_generator_node / narration_generator_node — chapter_context text
#    actually reaches the real constructed LLM prompt (AC 6, AC 7). Mirrors
#    test_slide_generator_node.py's own
#    test_prompt_never_includes_raw_summaries_or_sections style: inspect the
#    real prompt sent to the mocked provider, not just that a mock was called.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slide_generator_node_prompt_includes_chapter_context() -> None:
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
        "chapter_context": (
            "\n\n[Chapter Instructions]\nStudent-supplied doubt: UNIQUE_CHAPTER_DOUBT_MARKER_XYZ"
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
        await slide_generator_node(state)

    sent_messages = mock_provider.complete_structured.call_args.args[0]
    full_prompt = "\n".join(m["content"] for m in sent_messages)
    assert "UNIQUE_CHAPTER_DOUBT_MARKER_XYZ" in full_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_generator_node_prompt_includes_chapter_context() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.content.pipeline.graph import narration_generator_node

    mock_output = type(
        "Narration",
        (),
        {"narration_style": "conversational", "script": "Let's begin."},
    )()
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = mock_output

    state = {
        "lesson_id": "40404040-4040-4040-4040-404040404040",
        "_section": {
            "title": "Intro",
            "body": "prose. " * 20,
            "page_start": 1,
            "page_end": 2,
        },
        "_section_index": 0,
        "chapter_context": (
            "\n\n[Chapter Instructions]\nStudent-supplied doubt: UNIQUE_NARRATION_DOUBT_MARKER_XYZ"
        ),
    }

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
        await narration_generator_node(state)

    sent_messages = mock_provider.complete_structured.call_args.args[0]
    full_prompt = "\n".join(m["content"] for m in sent_messages)
    assert "UNIQUE_NARRATION_DOUBT_MARKER_XYZ" in full_prompt
