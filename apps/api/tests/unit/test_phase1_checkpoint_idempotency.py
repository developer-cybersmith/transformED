"""
RED-phase unit tests for Story 2-1b (Phase 1 economy node checkpoint/idempotency).

Covers, per docs/stories/2-1b-phase1-checkpoint-idempotency.md:
- AC-1/AC-2: each economy node checks lesson_jobs.node_outputs for a
  per-section completion record before calling its provider, and writes one
  on success.
- AC-3: a simulated ARQ retry (2 of 3 sections already checkpointed) makes 0
  additional LLM calls for the cached sections and exactly 1 for the rest.
- AC-4: Phase 1 progress visibility via a Redis counter.

Mocking conventions follow test_pipeline_tier1.py / test_phase1_economy_nodes.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.providers.llm.openai as openai_provider_module  # noqa: E402  (force submodule import, see test_phase1_economy_nodes.py)

FAKE_LESSON_ID = "20202020-2020-2020-2020-202020202020"

SECTION_0 = {"title": "Spaced Repetition", "body": "prose about spaced repetition. " * 20}
SECTION_1 = {"title": "Active Recall", "body": "prose about active recall. " * 20}
SECTION_2 = {"title": "Interleaving", "body": "prose about interleaving practice. " * 20}


def _make_jobs_table(node_outputs: dict[str, Any]) -> MagicMock:
    """Mirrors test_pipeline_tier1.py's helper: a lesson_jobs table mock whose
    .select(...).eq(...).single().execute() returns the given node_outputs,
    and whose .update(...) can be inspected afterward."""
    t = MagicMock()
    t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs
    }
    t.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return t


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "_section": SECTION_0,
        "_section_index": 0,
    }
    state.update(overrides)
    return state


class TestCheckpointCacheHit:
    @pytest.mark.asyncio
    async def test_summarise_segment_skips_llm_call_on_cache_hit(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_summary = {"segment_id": section_id, "summary": "Already-computed summary."}
        mock_jobs_table = _make_jobs_table({f"summarise_segment:{section_id}": cached_summary})

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_provider = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await summarise_segment_node(state)

        mock_provider.complete_structured.assert_not_called()
        assert result["segment_summaries"] == [cached_summary]

    @pytest.mark.asyncio
    async def test_segment_complexity_skips_llm_call_on_cache_hit(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, segment_complexity_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_score = {
            "segment_id": section_id,
            "level": "medium",
            "cognitive_load": "moderate",
            "abstraction_level": "concrete",
            "prerequisite_concepts": [],
            "narration_style": "casual",
            "quiz_difficulty": "easy",
            "intervention_sensitivity": 0.4,
        }
        mock_jobs_table = _make_jobs_table({f"segment_complexity:{section_id}": cached_score})

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_provider = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await segment_complexity_node(state)

        mock_provider.complete_structured.assert_not_called()
        assert result["complexity_scores"] == [cached_score]


class TestCheckpointWriteOnSuccess:
    @pytest.mark.asyncio
    async def test_summarise_segment_writes_checkpoint_via_atomic_merge_rpc(self) -> None:
        """A client-side read-modify-write of the whole node_outputs blob would
        lose concurrent sibling dispatches' writes (Story 2-1b Context/Dev
        Notes) — the write must go through the atomic merge RPC, not
        `.update({"node_outputs": {...}})`.
        """
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        section_id = _derive_section_id(SECTION_0, 0)
        mock_jobs_table = _make_jobs_table({})  # no prior checkpoint — cache miss

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_rpc_execute = MagicMock()
        mock_supabase.rpc.return_value.execute.return_value = mock_rpc_execute

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = type(
            "Summary", (), {"summary": "A fresh summary."}
        )()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            await summarise_segment_node(state)

        mock_provider.complete_structured.assert_called_once()
        mock_supabase.rpc.assert_called_once()
        rpc_name, rpc_params = mock_supabase.rpc.call_args[0][0], mock_supabase.rpc.call_args[0][1]
        assert rpc_name == "merge_lesson_job_node_output"
        assert rpc_params["p_lesson_id"] == FAKE_LESSON_ID
        assert rpc_params["p_key"] == f"summarise_segment:{section_id}"
        assert rpc_params["p_value"]["summary"] == "A fresh summary."

        # AC-5: a client-side node_outputs blob update must NOT also happen —
        # that's the exact race this story exists to remove.
        mock_jobs_table.update.assert_not_called()


class TestSimulatedRetry:
    @pytest.mark.asyncio
    async def test_retry_after_partial_completion_makes_zero_duplicate_calls(self) -> None:
        """AC-3: simulate an ARQ retry where 2 of 3 sections already
        completed summarise_segment before a worker crash. Re-invoking the
        node for all 3 sections must make exactly 1 LLM call (the uncached
        section) and 0 for the 2 already-cached ones.
        """
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        cached_0 = {"segment_id": _derive_section_id(SECTION_0, 0), "summary": "Cached summary 0."}
        cached_1 = {"segment_id": _derive_section_id(SECTION_1, 1), "summary": "Cached summary 1."}
        node_outputs = {
            f"summarise_segment:{_derive_section_id(SECTION_0, 0)}": cached_0,
            f"summarise_segment:{_derive_section_id(SECTION_1, 1)}": cached_1,
            # SECTION_2 has no checkpoint — simulates the section that hadn't
            # completed yet when the worker crashed.
        }
        mock_jobs_table = _make_jobs_table(node_outputs)
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = type(
            "Summary", (), {"summary": "Freshly computed summary for section 2."}
        )()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            result_0 = await summarise_segment_node(_base_state(_section=SECTION_0, _section_index=0))
            result_1 = await summarise_segment_node(_base_state(_section=SECTION_1, _section_index=1))
            result_2 = await summarise_segment_node(_base_state(_section=SECTION_2, _section_index=2))

        assert mock_provider.complete_structured.call_count == 1, (
            f"expected exactly 1 LLM call for the 1 uncached section, "
            f"got {mock_provider.complete_structured.call_count} — a retry must not "
            f"re-bill already-completed sections"
        )
        assert result_0["segment_summaries"] == [cached_0]
        assert result_1["segment_summaries"] == [cached_1]
        assert result_2["segment_summaries"][0]["summary"] == "Freshly computed summary for section 2."


class TestPhase1ProgressVisibility:
    @pytest.mark.asyncio
    async def test_completing_a_dispatch_increments_redis_progress_counter(self) -> None:
        """AC-4: progress_pct can't be written by economy nodes directly
        (concurrent writes to a non-reducer PipelineState key raise
        InvalidUpdateError — see Story 2-1's review findings), so Phase 1
        progress visibility must go through a separate channel: a Redis
        counter incremented once per completed dispatch (cache hit or real
        completion), independent of the graph's PipelineState channel.
        """
        from app.modules.content.pipeline.graph import summarise_segment_node

        mock_jobs_table = _make_jobs_table({})
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = type("Summary", (), {"summary": "Summary."})()

        mock_redis = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=mock_redis):
            state = _base_state(_total_sections=3)
            await summarise_segment_node(state)

        mock_redis.incr.assert_called_once()
        incr_key = mock_redis.incr.call_args[0][0]
        assert incr_key == f"job:{FAKE_LESSON_ID}:phase1_completed"

    @pytest.mark.asyncio
    async def test_cache_hit_also_increments_progress_counter(self) -> None:
        """A cache-hit completion still counts toward Phase 1 progress — it's
        a completed dispatch either way, cached or freshly computed.
        """
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_summary = {"segment_id": section_id, "summary": "Cached."}
        mock_jobs_table = _make_jobs_table({f"summarise_segment:{section_id}": cached_summary})
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table

        mock_redis = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.core.redis.get_redis", return_value=mock_redis
        ):
            state = _base_state(_total_sections=3)
            await summarise_segment_node(state)

        mock_redis.incr.assert_called_once()


class TestExistingStory21TestsUnaffected:
    """AC-5: this story only adds idempotency — it must not change node
    behavior when there's no cache hit. A cheap smoke test here; the full
    regression guard is running test_phase1_economy_nodes.py unmodified.
    """

    @pytest.mark.asyncio
    async def test_no_cache_hit_behaves_like_before(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        mock_jobs_table = _make_jobs_table({})  # cache miss
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = type(
            "Summary", (), {"summary": "A short summary under the word cap."}
        )()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await summarise_segment_node(state)

        assert result["segment_summaries"][0]["segment_id"] == _derive_section_id(SECTION_0, 0)
        assert result["segment_summaries"][0]["summary"] == "A short summary under the word cap."
