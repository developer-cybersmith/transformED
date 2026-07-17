"""
Unit tests for Story 2-7 (S2-8): slide_generator_node real generation.

Covers docs/stories/2-7-slide-generator-node.md's ACs:
- AC-1: input is lesson_plan["segments"] only, never raw summaries/sections/text.
- AC-2/AC-7: 1:1 segment count, echoed segment_ids, degrade-not-fabricate guards.
- AC-3/AC-5: each slide validates against the frozen Slide model, nested
  {segment_id, data} output shape.
- AC-4: 1-8 slides per segment.
- AC-6: settings.llm_slide_generator is the model passed to complete_structured.
- AC-8: idempotency checkpoint (Phase-A style).

Patches "app.providers.llm.openai.OpenAILLMProvider" (the SOURCE module) and
"app.core.db.get_supabase" — graph.py uses lazy in-function imports, so these
are the correct patch targets (established convention).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force the submodule into sys.modules so patch("app.providers.llm.openai.OpenAILLMProvider", ...)
# can resolve it — graph.py's lazy in-function imports mean nothing else
# guarantees this import has already happened.
import app.providers.llm.openai as openai_provider_module  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _default_under_cost_ceiling():
    """Story 2-13/S2-13: every node call now checks the cost ceiling before
    dispatching an LLM call. Default every test in this file to "not over
    ceiling" so pre-existing tests need no changes; downshift-specific tests
    override this explicitly."""
    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        yield


FAKE_LESSON_ID = "40404040-4040-4040-4040-404040404040"

PLAN_SEGMENTS: list[dict[str, Any]] = [
    {"segment_id": "sec_0", "title": "Getting Started", "summary": "Intro summary.", "duration_min": 4.0},
    {"segment_id": "sec_1", "title": "How It Works", "summary": "Mechanics summary.", "duration_min": 6.0},
    {"segment_id": "sec_2", "title": "Examples", "summary": "Examples summary.", "duration_min": 5.0},
]


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "lesson_plan": {
            "title": "Understanding the Topic",
            "subject": "General Studies",
            "objectives": ["Understand X"],
            "complexity_level": "medium",
            "total_segments": 3,
            "total_duration_min": 15.0,
            "segments": PLAN_SEGMENTS,
        },
        "progress_pct": 38.0,
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_supabase(node_outputs: dict[str, Any] | None = None) -> MagicMock:
    sb = MagicMock()
    jobs_mock = MagicMock()
    jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs or {}
    }
    jobs_mock.update.return_value.eq.return_value.execute.return_value = MagicMock()
    sb.table.return_value = jobs_mock
    return sb


def _deck_response(segments: list[dict[str, Any]] | None = None) -> MagicMock:
    """Build a mock parsed `_SlideDeckLLM`-shaped response."""
    if segments is None:
        segments = [
            {
                "segment_id": "sec_0",
                "slides": [{"title": "Welcome", "bullets": ["Point A", "Point B"]}],
            },
            {
                "segment_id": "sec_1",
                "slides": [
                    {"title": "Mechanics 1", "bullets": ["Step 1"]},
                    {"title": "Mechanics 2", "bullets": ["Step 2"]},
                ],
            },
            {
                "segment_id": "sec_2",
                "slides": [{"title": "Example 1", "bullets": ["Case A"]}],
            },
        ]
    response = MagicMock()
    seg_mocks = []
    for seg in segments:
        slide_mocks = [MagicMock(**s) for s in seg["slides"]]
        seg_mock = MagicMock(segment_id=seg["segment_id"], slides=slide_mocks)
        seg_mocks.append(seg_mock)
    response.segments = seg_mocks
    return response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_produces_nested_slide_entries_matching_segments() -> None:
    """AC-3/AC-5: N plan segments in -> nested {segment_id, data} entries out,
    each data validates against Slide, slide_id deterministic."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await slide_generator_node(_base_state())

    slides = result["slides"]
    # Flat per-slide list: 1 (sec_0) + 2 (sec_1) + 1 (sec_2) = 4 total.
    assert len(slides) == 4
    assert slides[0]["segment_id"] == "sec_0"
    assert slides[0]["data"]["slide_id"] == "slide_sec_0_0"
    assert slides[0]["data"]["title"] == "Welcome"
    assert slides[0]["data"]["bullets"] == ["Point A", "Point B"]
    assert slides[0]["data"]["image_url"] is None
    assert slides[0]["data"]["fallback_image_url"] is None
    # sec_1 has 2 slides in this fixture
    assert slides[1]["segment_id"] == "sec_1"
    assert slides[1]["data"]["slide_id"] == "slide_sec_1_0"
    assert slides[2]["segment_id"] == "sec_1"
    assert slides[2]["data"]["slide_id"] == "slide_sec_1_1"
    assert slides[3]["segment_id"] == "sec_2"
    assert slides[3]["data"]["slide_id"] == "slide_sec_2_0"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prompt_never_includes_raw_summaries_or_sections() -> None:
    """AC-1: even when segment_summaries/sections/chapter_content are present
    in state alongside lesson_plan, the prompt must never include them."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response()
    sb = _mock_supabase()

    state = _base_state(
        segment_summaries=[{"segment_id": "sec_0", "summary": "RAW SEGMENT SUMMARY MUST NEVER APPEAR"}],
        chapter_content="RAW CHAPTER TEXT MUST NEVER APPEAR" * 50,
        sections=[{"title": "sec_0", "body": "RAW SECTION BODY MUST NEVER APPEAR"}],
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        await slide_generator_node(state)

    sent_messages = mock_provider.complete_structured.call_args.args[0]
    full_prompt = "\n".join(m["content"] for m in sent_messages)
    assert "RAW SEGMENT SUMMARY" not in full_prompt
    assert "RAW CHAPTER TEXT" not in full_prompt
    assert "RAW SECTION BODY" not in full_prompt
    for seg in PLAN_SEGMENTS:
        assert seg["title"] in full_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_used_is_settings_llm_slide_generator() -> None:
    """AC-6: the model passed to complete_structured is settings.llm_slide_generator."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm_slide_generator = "gpt-4o-custom-eval-candidate"
        await slide_generator_node(_base_state())

    call_args = mock_provider.complete_structured.call_args
    assert call_args.args[1] == "gpt-4o-custom-eval-candidate"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_over_ceiling_downshifts_to_llm_mini_and_completes() -> None:
    """Story 2-13/S2-13 AC-2: when check_ceiling() returns True, the node
    uses settings.llm_mini (not llm_slide_generator) for both provider
    selection and the complete_structured model arg, records a downshift,
    and still completes successfully (never raises solely for a ceiling
    breach)."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)
        ) as mock_check_ceiling,
    ):
        mock_settings.return_value.llm_slide_generator = "gpt-4o"
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await slide_generator_node(_base_state())

    call_args = mock_provider.complete_structured.call_args
    assert call_args.args[1] == "gpt-4o-mini"
    assert len(result["slides"]) > 0  # completed normally, not raised
    mock_check_ceiling.assert_awaited_once_with(FAKE_LESSON_ID)

    # Story 2-13/S2-13 review fix: the downshift record must survive into the
    # node's OWN final checkpoint write, not be clobbered by it.
    checkpoint_calls = [
        c.args[0] for c in sb.table.return_value.update.call_args_list if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    written_node_outputs = checkpoint_calls[0]["node_outputs"]
    assert "slide_generator" in written_node_outputs
    downshifts = written_node_outputs["_cost_downshifts"]
    assert len(downshifts) == 1
    assert downshifts[0]["node"] == "slide_generator"
    assert downshifts[0]["from_model_or_provider"] == "gpt-4o"
    assert downshifts[0]["to_model_or_provider"] == "gpt-4o-mini"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_ceiling_failure_fails_open_and_uses_premium_model() -> None:
    """Story 2-13/S2-13 review fix: check_ceiling() raising must not crash
    the node — fail open, matching _fan_out_phase1_economy_nodes' pattern."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.core.cost_tracker.check_ceiling",
            new=AsyncMock(side_effect=RuntimeError("Redis pool is not initialised")),
        ),
    ):
        mock_settings.return_value.llm_slide_generator = "gpt-4o"
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await slide_generator_node(_base_state())

    call_args = mock_provider.complete_structured.call_args
    assert call_args.args[1] == "gpt-4o"  # premium model, not downshifted
    assert len(result["slides"]) > 0  # completed normally, not raised


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_lesson_plan_segments_rejected_before_llm_call() -> None:
    """Empty lesson_plan['segments'] must reject before calling the LLM."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="zero"):
            await slide_generator_node(_base_state(lesson_plan={"segments": []}))

    mock_provider.complete_structured.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mismatched_segment_count_is_rejected_not_checkpointed() -> None:
    """AC-2/AC-7: LLM returns fewer segment-slide-sets than plan segments -> reject."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": [{"title": "Welcome", "bullets": ["Point A"]}]},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
        ]  # only 2, plan has 3
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="segment count"):
            await slide_generator_node(_base_state())

    sb.table.return_value.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_segment_id_is_rejected() -> None:
    """AC-2/AC-7: LLM invents a segment_id not present in the plan -> reject."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": [{"title": "Welcome", "bullets": ["Point A"]}]},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
            {"segment_id": "sec_invented", "slides": [{"title": "Made Up", "bullets": ["X"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="segment_id"):
            await slide_generator_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_segment_id_is_rejected() -> None:
    """Duplicate segment_id in response is rejected, mirroring lesson_planner_node."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": [{"title": "Welcome", "bullets": ["Point A"]}]},
            {"segment_id": "sec_0", "slides": [{"title": "Duplicate", "bullets": ["Point B"]}]},
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="duplicate"):
            await slide_generator_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_zero_slides_for_a_segment_is_rejected() -> None:
    """AC-4/AC-7: a segment with 0 slides is rejected."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": []},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="slides"):
            await slide_generator_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_too_many_slides_for_a_segment_is_rejected() -> None:
    """AC-4/AC-7: a segment with more than 8 slides is rejected."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {
                "segment_id": "sec_0",
                "slides": [{"title": f"Slide {i}", "bullets": ["X"]} for i in range(9)],
            },
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="slides"):
            await slide_generator_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_slide_title_is_rejected() -> None:
    """AC-7: a blank slide title is rejected, not silently shipped."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": [{"title": "   ", "bullets": ["Point A"]}]},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="blank"):
            await slide_generator_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_bullets_is_rejected() -> None:
    """AC-7: a slide with empty bullets is rejected, not silently shipped."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": [{"title": "Welcome", "bullets": []}]},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="bullet"):
            await slide_generator_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refusal_raises_and_does_not_checkpoint() -> None:
    """A None response (refusal/parse failure) raises rather than shipping a
    placeholder — no per-segment redundancy exists for this premium node."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = None
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError):
            await slide_generator_node(_base_state())

    sb.table.return_value.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_cache_hit_skips_llm_call() -> None:
    """AC-8: a pre-existing node_outputs['slide_generator'] checkpoint is
    returned as-is with zero calls to complete_structured."""
    from app.modules.content.pipeline.graph import slide_generator_node

    cached_slides = [
        {
            "segment_id": "sec_0",
            "data": {
                "slide_id": "slide_sec_0_0", "title": "Cached", "bullets": ["x"],
                "image_url": None, "fallback_image_url": None,
            },
        }
    ]
    mock_provider = AsyncMock()
    sb = _mock_supabase(node_outputs={"slide_generator": cached_slides})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await slide_generator_node(_base_state())

    assert result["slides"] == cached_slides
    mock_provider.complete_structured.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_run_writes_checkpoint() -> None:
    """AC-8: a successful generation writes last_node + node_outputs."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        await slide_generator_node(_base_state())

    checkpoint_calls = [
        call.args[0]
        for call in sb.table.return_value.update.call_args_list
        if "node_outputs" in call.args[0]
    ]
    assert len(checkpoint_calls) == 1, f"expected exactly one checkpoint write, got {checkpoint_calls}"
    update_call = checkpoint_calls[0]
    assert update_call["last_node"] == "slide_generator"
    assert "slide_generator" in update_call["node_outputs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_order_follows_input_not_llm_response_order() -> None:
    """The assembled slides list must follow lesson_plan['segments']' original
    order, even if the LLM returns the same set of segment_ids shuffled."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
            {"segment_id": "sec_0", "slides": [{"title": "Welcome", "bullets": ["Point A"]}]},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await slide_generator_node(_base_state())

    ordered_ids = [entry["segment_id"] for entry in result["slides"]]
    assert ordered_ids == ["sec_0", "sec_1", "sec_2"], (
        f"segment order must follow lesson_plan input order, got {ordered_ids}"
    )


# ---------------------------------------------------------------------------
# 2026-07-15 code review patches
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_whitespace_only_bullet_is_rejected() -> None:
    """Review finding (Blind Hunter + Edge Case Hunter): a blank/whitespace-only
    bullet string must be rejected even when the bullets list itself is
    non-empty."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _deck_response(
        segments=[
            {"segment_id": "sec_0", "slides": [{"title": "Welcome", "bullets": ["   ", "Real point"]}]},
            {"segment_id": "sec_1", "slides": [{"title": "Mechanics", "bullets": ["Step 1"]}]},
            {"segment_id": "sec_2", "slides": [{"title": "Example", "bullets": ["Case A"]}]},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="bullet"):
            await slide_generator_node(_base_state())

    sb.table.return_value.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_lesson_plan_segment_raises_contextual_error() -> None:
    """Review finding (Blind Hunter + Edge Case Hunter + Acceptance Auditor):
    a lesson_plan segment missing segment_id/title/summary raises a
    contextual RuntimeError, not a raw KeyError."""
    from app.modules.content.pipeline.graph import slide_generator_node

    mock_provider = AsyncMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="malformed lesson_plan segment"):
            await slide_generator_node(
                _base_state(lesson_plan={"segments": [{"segment_id": "sec_0", "title": "X"}]})
            )

    mock_provider.complete_structured.assert_not_called()
