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


# ─────────────────────────────────────────────────────────────────────────────
# F. AC 8 — chapter_context_truncated must reach the PERSISTED, admin-visible
#    record package_builder_node writes, not just transient PipelineState.
#    Review finding: this was computed but never persisted — package_builder_node
#    only wrote book_context_truncated into node_outputs. Mirrors
#    test_package_builder_node.py's own conventions.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chapter_context_truncated_reaches_persisted_admin_record() -> None:
    from unittest.mock import patch

    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase()
    state = _base_state(chapter_context_truncated=True)

    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(state)

    jobs_update_kwargs = jobs_table.update.call_args[0][0]
    node_outputs = jobs_update_kwargs["node_outputs"]
    assert node_outputs["chapter_context_truncated"] is True, (
        "AC 8: chapter_context_truncated must reach the same persisted, "
        "admin-visible record book_context_truncated already does — a value "
        "that only ever lives in transient PipelineState is not surfaced, "
        "it is silent (CLAUDE.md)"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chapter_context_truncated_defaults_false_when_absent() -> None:
    """Symmetry with book_context_truncated's own `state.get(..., False)`
    default — most lessons have no chapter context at all."""
    from unittest.mock import patch

    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase()

    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(_base_state())

    jobs_update_kwargs = jobs_table.update.call_args[0][0]
    node_outputs = jobs_update_kwargs["node_outputs"]
    assert node_outputs["chapter_context_truncated"] is False


# ─────────────────────────────────────────────────────────────────────────────
# G. lesson_planner_node — the REAL node's returned dict, both idempotency
#    paths (review finding: only the private _planner_system_prompt helper
#    and the pure merge function were exercised; a regression dropping
#    chapter_context/chapter_context_truncated from either return-dict
#    literal in the real node would pass the whole suite undetected).
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lesson_planner_node_returns_chapter_context_fresh_computation_path() -> None:
    from unittest.mock import AsyncMock, patch

    from app.modules.content.pipeline.graph import lesson_planner_node
    from tests.unit.test_lesson_planner_node import _mock_supabase, _plan_llm_response

    state = {
        "lesson_id": "30303030-3030-3030-3030-303030303030",
        "segment_summaries": [
            {"segment_id": "sec_0", "summary": "Introduction to the topic."},
        ],
        "progress_pct": 30.0,
        "error": None,
        "chapter_id": "chapter-fixture-id",
        "user_id": "user-fixture-id",
    }

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[
            {
                "segment_id": "sec_0",
                "title": "Getting Started",
                "duration_min": 4.0,
                "continuity_notes": "",
            }
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch(
            "app.modules.content.context.get_book_context_prompt_context",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "app.modules.content.context_chapter.get_chapter_context_prompt_block",
            new=AsyncMock(return_value="UNIQUE_FRESH_PATH_CHAPTER_CTX_MARKER"),
        ),
    ):
        result = await lesson_planner_node(state)

    assert result["chapter_context"] == "UNIQUE_FRESH_PATH_CHAPTER_CTX_MARKER"
    assert result["chapter_context_truncated"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lesson_planner_node_returns_chapter_context_on_cache_hit_path() -> None:
    """The cache-hit branch skips the LLM call entirely but must still return
    chapter_context/chapter_context_truncated — slide_generator_node and
    narration_generator_node (dispatched after this node via
    _FAN_OUT_STATE_KEYS) read them from state regardless of which branch ran."""
    from unittest.mock import AsyncMock, patch

    from app.modules.content.pipeline.graph import lesson_planner_node
    from tests.unit.test_lesson_planner_node import _mock_supabase

    cached_plan = {
        "title": "Cached",
        "subject": "S",
        "objectives": ["O"],
        "complexity_level": "medium",
        "total_segments": 1,
        "total_duration_min": 4.0,
        "segments": [],
    }
    state = {
        "lesson_id": "30303030-3030-3030-3030-303030303030",
        "segment_summaries": [{"segment_id": "sec_0", "summary": "Intro."}],
        "progress_pct": 30.0,
        "error": None,
        "chapter_id": "chapter-fixture-id",
        "user_id": "user-fixture-id",
    }
    sb = _mock_supabase(node_outputs={"lesson_planner": cached_plan})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch(
            "app.modules.content.context.get_book_context_prompt_context",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "app.modules.content.context_chapter.get_chapter_context_prompt_block",
            new=AsyncMock(return_value="UNIQUE_CACHE_HIT_CHAPTER_CTX_MARKER"),
        ),
    ):
        result = await lesson_planner_node(state)

    assert result["lesson_plan"] == cached_plan
    assert result["chapter_context"] == "UNIQUE_CACHE_HIT_CHAPTER_CTX_MARKER"


# ─────────────────────────────────────────────────────────────────────────────
# H. slide_generator_node — the REAL node's returned dict must carry
#    chapter_context_truncated (not just narration/lesson_planner's), and
#    book_context + chapter_context must compose correctly in the same
#    prompt when BOTH are present (review finding: each was only ever
#    tested in isolation; accidentally re-passing the pre-book-merge base
#    prompt into merge_chapter_context would silently drop book_context).
# ─────────────────────────────────────────────────────────────────────────────


def _slide_state_with_contexts(book_context: str = "", chapter_context: str = "") -> dict:
    return {
        "lesson_id": "40404040-4040-4040-4040-404040404040",
        "lesson_plan": {
            "title": "T",
            "subject": "S",
            "objectives": ["O"],
            "complexity_level": "medium",
            "total_segments": 1,
            "total_duration_min": 4.0,
            "segments": [
                {
                    "segment_id": "sec_0",
                    "title": "Getting Started",
                    "summary": "Intro summary.",
                    "duration_min": 4.0,
                },
            ],
        },
        "progress_pct": 38.0,
        "error": None,
        "book_context": book_context,
        "chapter_context": chapter_context,
    }


async def _run_slide_generator_node(state: dict):
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.modules.content.pipeline.graph import slide_generator_node

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
    return result, full_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_slide_generator_node_returns_chapter_context_truncated_in_dict() -> None:
    from app.modules.content.pipeline.prompt_context import _CHAPTER_CONTEXT_MAX_CHARS

    oversized_chapter_context = "\n\n[Chapter Instructions]\n" + (
        "x" * (_CHAPTER_CONTEXT_MAX_CHARS + 500)
    )
    result, _ = await _run_slide_generator_node(
        _slide_state_with_contexts(chapter_context=oversized_chapter_context)
    )
    assert result["chapter_context_truncated"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_book_and_chapter_context_both_reach_slide_prompt_uncorrupted() -> None:
    """AC 6/AC 7 composition guard: when both book_context and chapter_context
    are non-empty, neither merge call may clobber the other. A regression
    where merge_chapter_context() is fed the pre-book-merge base prompt
    (instead of book_context's own merged output) would silently drop
    book_context from the final prompt whenever chapter_context is also
    present — this test would catch that, the isolated single-context tests
    above cannot."""
    result, full_prompt = await _run_slide_generator_node(
        _slide_state_with_contexts(
            book_context="\n\n[Book Instructions]\nUNIQUE_BOOK_MARKER_COMPOSE_TEST",
            chapter_context="\n\n[Chapter Instructions]\nUNIQUE_CHAPTER_MARKER_COMPOSE_TEST",
        )
    )
    assert "UNIQUE_BOOK_MARKER_COMPOSE_TEST" in full_prompt
    assert "UNIQUE_CHAPTER_MARKER_COMPOSE_TEST" in full_prompt
    book_pos = full_prompt.index("UNIQUE_BOOK_MARKER_COMPOSE_TEST")
    chapter_pos = full_prompt.index("UNIQUE_CHAPTER_MARKER_COMPOSE_TEST")
    assert book_pos < chapter_pos, "book_context must be merged before chapter_context"
    assert result["book_context_truncated"] is False
    assert result["chapter_context_truncated"] is False


# ─────────────────────────────────────────────────────────────────────────────
# I. AC 1 — PipelineState TypedDict carries both new fields. TypedDict has no
#    runtime enforcement, so this only guards the annotation itself, but a
#    field silently dropped from the class body would otherwise go unnoticed
#    by every other test in this file (they all use plain dict literals).
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_pipeline_state_declares_chapter_context_fields():
    # graph.py has `from __future__ import annotations`, so
    # PipelineState.__annotations__ holds unresolved ForwardRef objects, not
    # real types — get_type_hints() resolves them against the module's own
    # globals, the same way a type checker or IDE would.
    from typing import get_type_hints

    from app.modules.content.pipeline.graph import PipelineState

    hints = get_type_hints(PipelineState)
    assert hints.get("chapter_context") is str
    assert hints.get("chapter_context_truncated") is bool
    # unchanged sibling fields, confirming this isn't a fresh/replaced class
    assert hints.get("book_context") is str
    assert hints.get("book_context_truncated") is bool
