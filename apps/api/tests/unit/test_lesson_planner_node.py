"""
Unit tests for Story 2-6 (S2-7): lesson_planner_node real generation.

Covers docs/stories/2-6-lesson-planner-node.md's ACs:
- AC-1: input is segment_summaries only, never raw chapter text/sections.
- AC-2/AC-6: 1:1 segment count, echoed segment_ids, degrade-not-fabricate guards.
- AC-3: output dict shape.
- AC-4: settings.llm_lesson_planner is the model passed to complete_structured.
- AC-5: idempotency checkpoint (Phase-A style, not Story 2-1b's atomic RPC).
- AC-7: total_duration_min is summed, never asked for directly.

Patches "app.providers.llm.openai.OpenAILLMProvider" (the SOURCE module) and
"app.core.db.get_supabase" — graph.py uses lazy in-function imports, so these
are the correct patch targets (established convention, see
test_phase1_economy_nodes.py's module docstring).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force the submodule into sys.modules so patch("app.providers.llm.openai.OpenAILLMProvider", ...)
# can resolve it — graph.py's lazy in-function imports mean nothing else
# guarantees this import has already happened (same convention as
# test_phase1_economy_nodes.py).
import app.providers.llm.openai as openai_provider_module  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _default_under_cost_ceiling():
    """Story 2-13/S2-13: every node call now checks the cost ceiling before
    dispatching an LLM call. Default every test in this file to "not over
    ceiling" so pre-existing tests need no changes; downshift-specific tests
    override this explicitly."""
    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        yield


FAKE_LESSON_ID = "30303030-3030-3030-3030-303030303030"

SUMMARIES: list[dict[str, Any]] = [
    {"segment_id": "sec_0", "summary": "Introduction to the topic."},
    {"segment_id": "sec_1", "summary": "Core mechanics explained."},
    {"segment_id": "sec_2", "summary": "Worked examples and pitfalls."},
]


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "segment_summaries": SUMMARIES,
        "progress_pct": 30.0,
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


def _plan_llm_response(
    segments: list[dict[str, Any]] | None = None,
    title: str = "Understanding the Topic",
    subject: str = "General Studies",
    complexity_level: str = "medium",
    objectives: list[str] | None = None,
) -> MagicMock:
    """Build a mock parsed `_LessonPlanLLM`-shaped response."""
    if segments is None:
        segments = [
            {"segment_id": "sec_0", "title": "Getting Started", "duration_min": 4.0},
            {"segment_id": "sec_1", "title": "How It Works", "duration_min": 6.0},
            {"segment_id": "sec_2", "title": "Examples", "duration_min": 5.0},
        ]
    if objectives is None:
        objectives = ["Understand the core concept", "Apply it to a worked example"]
    response = MagicMock()
    response.title = title
    response.subject = subject
    response.complexity_level = complexity_level
    response.objectives = objectives
    response.segments = [MagicMock(**seg) for seg in segments]
    return response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_produces_lesson_plan_matching_input_count() -> None:
    """AC-3/AC-7: N summaries in -> N-segment plan out, total_duration_min summed."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state())

    plan = result["lesson_plan"]
    assert plan["title"] == "Understanding the Topic"
    assert plan["subject"] == "General Studies"
    assert plan["complexity_level"] == "medium"
    assert plan["total_segments"] == 3
    assert plan["total_duration_min"] == pytest.approx(15.0), "must be summed, not LLM-supplied directly"
    assert len(plan["segments"]) == 3
    assert plan["segments"][0]["segment_id"] == "sec_0"
    assert plan["segments"][0]["title"] == "Getting Started"
    assert plan["segments"][0]["duration_min"] == 4.0
    # Original summary text is preserved verbatim, not re-derived from the LLM.
    assert plan["segments"][0]["summary"] == "Introduction to the topic."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prompt_never_includes_raw_chapter_text_or_sections() -> None:
    """AC-1: even when chapter_content/sections are present in state alongside
    segment_summaries, the prompt sent to the LLM must never include them —
    this is the exact 5x-cost-overrun bug the constraint exists to prevent."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    state = _base_state(
        chapter_content="RAW CHAPTER TEXT THAT MUST NEVER APPEAR IN THE PROMPT" * 50,
        sections=[{"title": "sec_0", "body": "RAW SECTION BODY MUST NEVER APPEAR EITHER"}],
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        await lesson_planner_node(state)

    sent_messages = mock_provider.complete_structured.call_args.args[0]
    full_prompt = "\n".join(m["content"] for m in sent_messages)
    assert "RAW CHAPTER TEXT" not in full_prompt
    assert "RAW SECTION BODY" not in full_prompt
    for s in SUMMARIES:
        assert s["summary"] in full_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_used_is_settings_llm_lesson_planner() -> None:
    """AC-4: the model passed to complete_structured is settings.llm_lesson_planner,
    never llm_mini or a hardcoded string."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.llm_lesson_planner = "gpt-4o-custom-eval-candidate"
        await lesson_planner_node(_base_state())

    call_args = mock_provider.complete_structured.call_args
    assert call_args.args[1] == "gpt-4o-custom-eval-candidate"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_over_ceiling_downshifts_to_llm_mini_and_completes() -> None:
    """Story 2-13/S2-13 AC-1: when check_ceiling() returns True, the node
    uses settings.llm_mini (not llm_lesson_planner) for both provider
    selection and the complete_structured model arg, records a downshift,
    and still completes successfully (never raises solely for a ceiling
    breach)."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)
        ) as mock_check_ceiling,
    ):
        mock_settings.return_value.llm_lesson_planner = "gpt-4o"
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await lesson_planner_node(_base_state())

    call_args = mock_provider.complete_structured.call_args
    assert call_args.args[1] == "gpt-4o-mini"
    assert result["lesson_plan"]["title"]  # completed normally, not raised
    mock_check_ceiling.assert_awaited_once_with(FAKE_LESSON_ID)

    # Story 2-13/S2-13 review fix: the downshift record must survive into the
    # node's OWN final checkpoint write, not be clobbered by it (the original
    # bug this replaces) — _record_cost_downshift is no longer mocked so this
    # exercises the real merge-then-write path end to end.
    # _update_job_progress() also calls .update() afterward (a separate,
    # smaller payload) — find the checkpoint write specifically by its
    # distinctive "node_outputs" key rather than assuming call order.
    checkpoint_calls = [
        c.args[0] for c in sb.table.return_value.update.call_args_list if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    written_node_outputs = checkpoint_calls[0]["node_outputs"]
    assert "lesson_planner" in written_node_outputs
    downshifts = written_node_outputs["_cost_downshifts"]
    assert len(downshifts) == 1
    assert downshifts[0]["node"] == "lesson_planner"
    assert downshifts[0]["from_model_or_provider"] == "gpt-4o"
    assert downshifts[0]["to_model_or_provider"] == "gpt-4o-mini"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_ceiling_failure_downshifts_by_default() -> None:
    """2026-07-20 review fix: check_ceiling() raising (e.g. Redis unavailable)
    must not crash the node AND must not fail open. For this PREMIUM node,
    failing open would run the expensive model uncapped during a Redis
    outage — a fleet-wide cost-exhaustion vector. Instead it DOWNSHIFTS BY
    DEFAULT: assume over-ceiling, use llm_mini, record the downshift, and
    still complete."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
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
        mock_settings.return_value.llm_lesson_planner = "gpt-4o"
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await lesson_planner_node(_base_state())

    call_args = mock_provider.complete_structured.call_args
    assert call_args.args[1] == "gpt-4o-mini"  # downshifted, NOT the premium model
    assert result["lesson_plan"]["title"]  # completed normally, not raised

    # The downshift must be recorded just as it is on a real ceiling breach.
    checkpoint_calls = [
        c.args[0]
        for c in sb.table.return_value.update.call_args_list
        if "node_outputs" in c.args[0]
    ]
    assert len(checkpoint_calls) == 1
    downshifts = checkpoint_calls[0]["node_outputs"]["_cost_downshifts"]
    assert len(downshifts) == 1
    assert downshifts[0]["node"] == "lesson_planner"
    assert downshifts[0]["to_model_or_provider"] == "gpt-4o-mini"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mismatched_segment_count_is_rejected_not_checkpointed() -> None:
    """AC-2/AC-6: LLM returns fewer segments than input summaries -> reject,
    raise, and never write a checkpoint (no re-billing-safe partial plan)."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[
            {"segment_id": "sec_0", "title": "Getting Started", "duration_min": 4.0},
            {"segment_id": "sec_1", "title": "How It Works", "duration_min": 6.0},
        ]  # only 2, input has 3
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="segment count"):
            await lesson_planner_node(_base_state())

    sb.table.return_value.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_segment_id_is_rejected() -> None:
    """AC-2/AC-6: LLM invents a segment_id not present in the input -> reject."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[
            {"segment_id": "sec_0", "title": "Getting Started", "duration_min": 4.0},
            {"segment_id": "sec_1", "title": "How It Works", "duration_min": 6.0},
            {"segment_id": "sec_99_invented", "title": "Made Up", "duration_min": 5.0},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="segment_id"):
            await lesson_planner_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_title_is_rejected() -> None:
    """AC-6: a blank top-level title is rejected, not silently shipped."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(title="   ")
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="blank"):
            await lesson_planner_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_segment_title_is_rejected() -> None:
    """AC-6: a blank per-segment title is rejected, not silently shipped."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[
            {"segment_id": "sec_0", "title": "", "duration_min": 4.0},
            {"segment_id": "sec_1", "title": "How It Works", "duration_min": 6.0},
            {"segment_id": "sec_2", "title": "Examples", "duration_min": 5.0},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="blank"):
            await lesson_planner_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refusal_raises_and_does_not_checkpoint() -> None:
    """A None response (refusal/parse failure) raises rather than shipping a
    placeholder — no per-section redundancy exists for this premium node."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = None
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError):
            await lesson_planner_node(_base_state())

    sb.table.return_value.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_cache_hit_skips_llm_call() -> None:
    """AC-5: a pre-existing node_outputs['lesson_planner'] checkpoint is
    returned as-is with zero calls to complete_structured."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    cached_plan = {
        "title": "Cached Plan", "subject": "Cached Subject", "objectives": [],
        "complexity_level": "medium", "total_segments": 3, "total_duration_min": 12.0,
        "segments": [{"segment_id": "sec_0", "title": "Cached", "summary": "x", "duration_min": 4.0}],
    }
    mock_provider = AsyncMock()
    sb = _mock_supabase(node_outputs={"lesson_planner": cached_plan})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state())

    assert result["lesson_plan"] == cached_plan
    mock_provider.complete_structured.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_run_writes_checkpoint() -> None:
    """AC-5: a successful generation writes last_node + node_outputs."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        await lesson_planner_node(_base_state())

    # _update_job_progress makes its own separate, later .update() call (just
    # {"last_node", "status"}) on the same mocked table — find the checkpoint
    # write specifically rather than assuming it's the last call.
    checkpoint_calls = [
        call.args[0]
        for call in sb.table.return_value.update.call_args_list
        if "node_outputs" in call.args[0]
    ]
    assert len(checkpoint_calls) == 1, f"expected exactly one checkpoint write, got {checkpoint_calls}"
    update_call = checkpoint_calls[0]
    assert update_call["last_node"] == "lesson_planner"
    assert "lesson_planner" in update_call["node_outputs"]


# ---------------------------------------------------------------------------
# 2026-07-14 code review patches
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_segment_summaries_rejected_before_llm_call() -> None:
    """Review finding (Edge Case Hunter): empty segment_summaries must reject
    before ever calling the LLM, not trivially pass the count guard (0 == 0)."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="zero segment_summaries"):
            await lesson_planner_node(_base_state(segment_summaries=[]))

    mock_provider.complete_structured.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_segment_summaries_entry_raises_contextual_error() -> None:
    """Review finding (Edge Case Hunter): a segment_summaries entry missing
    segment_id/summary raises a contextual RuntimeError, not a raw KeyError."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="malformed segment_summaries"):
            await lesson_planner_node(_base_state(segment_summaries=[{"segment_id": "sec_0"}]))

    mock_provider.complete_structured.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_duration", [0.0, -1.0, float("nan"), float("inf")])
async def test_invalid_duration_min_is_rejected(bad_duration: float) -> None:
    """Review finding (Blind Hunter + Edge Case Hunter): a non-positive or
    non-finite duration_min must be rejected, not silently summed."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[
            {"segment_id": "sec_0", "title": "Getting Started", "duration_min": bad_duration},
            {"segment_id": "sec_1", "title": "How It Works", "duration_min": 6.0},
            {"segment_id": "sec_2", "title": "Examples", "duration_min": 5.0},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="duration_min"):
            await lesson_planner_node(_base_state())

    sb.table.return_value.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_objectives_is_rejected() -> None:
    """Review finding (Edge Case Hunter): an empty objectives list is rejected,
    not silently checkpointed."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(objectives=[])
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        with pytest.raises(RuntimeError, match="objectives"):
            await lesson_planner_node(_base_state())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complexity_level_clamped_to_medium_when_invalid() -> None:
    """Review finding (Blind Hunter): an unrecognized complexity_level is
    clamped to 'medium', mirroring quiz_generator_node's difficulty-clamp
    pattern, rather than accepted verbatim or rejected outright."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(complexity_level="extremely-hard")
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state())

    assert result["lesson_plan"]["complexity_level"] == "medium"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_segment_order_follows_input_not_llm_response_order() -> None:
    """Review finding (Edge Case Hunter): the assembled plan's segment order
    must follow segment_summaries' original order, even if the LLM returns
    the same set of segment_ids in a shuffled order."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    # Shuffled relative to SUMMARIES' sec_0, sec_1, sec_2 order.
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[
            {"segment_id": "sec_2", "title": "Examples", "duration_min": 5.0},
            {"segment_id": "sec_0", "title": "Getting Started", "duration_min": 4.0},
            {"segment_id": "sec_1", "title": "How It Works", "duration_min": 6.0},
        ]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state())

    ordered_ids = [seg["segment_id"] for seg in result["lesson_plan"]["segments"]]
    assert ordered_ids == ["sec_0", "sec_1", "sec_2"], (
        f"segment order must follow segment_summaries input order, got {ordered_ids}"
    )


# ── Story S2-LM3/LM4/LM5: tier-aware slide budget + prompt framing ─────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_tier_produces_t2_slide_budget_and_no_framing() -> None:
    """AC-6/AC-8: omitting state["tier"] entirely must behave exactly as
    before this story — T2 slide_budget, no tier framing in the prompt."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state())  # no "tier" key at all

    for seg in result["lesson_plan"]["segments"]:
        # T2 band (12,15) / 3 segments -> per_min=4, per_max=5.
        assert seg["slide_budget"] == {"min": 4, "max": 5}

    sent_prompt = mock_provider.complete_structured.call_args.args[0][0]["content"]
    assert "CRITICAL-TOPICS-ONLY" not in sent_prompt
    assert "FULL-DEPTH" not in sent_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tier_t1_produces_full_depth_framing_and_wider_budget() -> None:
    """AC-4/AC-6: T1 -> full-depth prompt framing + a wider per-segment
    slide_budget than T2's default."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state(tier="T1"))

    for seg in result["lesson_plan"]["segments"]:
        # T1 band (20,25) / 3 segments -> per_min=ceil(20/3)=7, per_max=8 (clamped).
        # per_min uses ceiling division (2026-07-17 review fix, Blind Hunter)
        # so 3 segments' worst-case total (21) never falls below total_min=20.
        assert seg["slide_budget"] == {"min": 7, "max": 8}

    sent_prompt = mock_provider.complete_structured.call_args.args[0][0]["content"]
    assert "FULL-DEPTH" in sent_prompt
    assert "CRITICAL-TOPICS-ONLY" not in sent_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tier_t3_produces_refresher_framing_and_narrower_budget() -> None:
    """AC-4/AC-6: T3 -> critical-topics-only/refresher framing + a narrower
    per-segment slide_budget than T2's default."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state(tier="T3"))

    for seg in result["lesson_plan"]["segments"]:
        # T3 band (6,8) / 3 segments -> per_min=2, per_max=3.
        assert seg["slide_budget"] == {"min": 2, "max": 3}

    sent_prompt = mock_provider.complete_structured.call_args.args[0][0]["content"]
    assert "CRITICAL-TOPICS-ONLY" in sent_prompt
    assert "FULL-DEPTH" not in sent_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_single_segment_t1_slide_budget_clamped_to_structural_ceiling() -> None:
    """Dev Notes edge case: a 1-segment T1 lesson's naive per-segment
    allocation (total_min // 1 = 20) would exceed slide_generator's 1-8
    structural ceiling — both bounds must be clamped to 8, not just per_max."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(
        segments=[{"segment_id": "sec_0", "title": "Only Segment", "duration_min": 10.0}]
    )
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(
            _base_state(
                tier="T1",
                segment_summaries=[{"segment_id": "sec_0", "summary": "Only segment summary."}],
            )
        )

    budget = result["lesson_plan"]["segments"][0]["slide_budget"]
    assert budget["min"] <= 8
    assert budget["max"] <= 8
    assert budget["min"] <= budget["max"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_tier_value_falls_back_to_t2_budget_and_framing() -> None:
    """_tier_slide_budget_per_segment/prompt framing must fall back to T2
    for a garbage tier value, not raise — this is a soft budget hint, not a
    validated contract field (validation happens at the router, S2-LM3)."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response()
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state(tier="not-a-real-tier"))

    for seg in result["lesson_plan"]["segments"]:
        assert seg["slide_budget"] == {"min": 4, "max": 5}  # same as T2 default
    sent_prompt = mock_provider.complete_structured.call_args.args[0][0]["content"]
    assert "CRITICAL-TOPICS-ONLY" not in sent_prompt
    assert "FULL-DEPTH" not in sent_prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tier_t3_five_segments_never_undercuts_total_min() -> None:
    """Code review fix (Blind Hunter): with floor division, T3's total_min=6
    over 5 segments gave per_min=1, allowing a worst-case actual total of 5
    slides — below the tier's own advertised floor. Ceiling division fixes
    this: 5 segments * per_min must sum to >= 6."""
    from app.modules.content.pipeline.graph import lesson_planner_node

    summaries_5 = [{"segment_id": f"sec_{i}", "summary": f"Summary {i}."} for i in range(5)]
    plan_segments_5 = [
        {"segment_id": f"sec_{i}", "title": f"Title {i}", "duration_min": 3.0} for i in range(5)
    ]
    mock_provider = AsyncMock()
    mock_provider.complete_structured.return_value = _plan_llm_response(segments=plan_segments_5)
    sb = _mock_supabase()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider),
    ):
        result = await lesson_planner_node(_base_state(tier="T3", segment_summaries=summaries_5))

    total_min_possible = sum(seg["slide_budget"]["min"] for seg in result["lesson_plan"]["segments"])
    assert total_min_possible >= 6, f"worst-case total ({total_min_possible}) undercuts T3's advertised min of 6"
