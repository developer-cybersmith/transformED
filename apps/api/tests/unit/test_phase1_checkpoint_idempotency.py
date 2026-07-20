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
    """A lesson_jobs table mock whose .select(...).eq(...).maybe_single().execute()
    returns the given node_outputs. `.maybe_single()` (not `.single()`, which
    raises on 0 rows) is what _read_phase1_checkpoint uses — see its docstring.
    No `.update(...)` mock here: checkpoint writes go through `.rpc()`
    exclusively (Story 2-1b review finding — a lingering `.update()` mock
    with no corresponding assertion was dead scaffolding)."""
    t = MagicMock()
    t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs
    }
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

    @pytest.mark.asyncio
    async def test_quiz_generator_skips_llm_call_on_cache_hit(self) -> None:
        """Story 3-28 (AC-9): cache-hit uses new batch checkpoint shape.

        Checkpoint format changed from single-question {"segment_id": ..., "data": {...}}
        to batch {"segment_id": ..., "questions": [...]}. The LLM must NOT be
        called when a valid batch checkpoint exists.
        """
        from app.modules.content.pipeline.graph import _derive_section_id, quiz_generator_node

        section_id = _derive_section_id(SECTION_0, 0)
        q0 = {
            "segment_id": section_id,
            "data": {
                "question_id": f"quiz_{section_id}_0",
                "type": "mcq",
                "question": "Already-computed question?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "Already-computed explanation.",
                "difficulty": "medium",
            },
        }
        # Story 3-28 AC-9: batch-shaped checkpoint — "questions" key, not "data".
        cached_batch = {
            "segment_id": section_id,
            "questions": [q0],
        }
        mock_jobs_table = _make_jobs_table({f"quiz_generator:{section_id}": cached_batch})

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_provider = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await quiz_generator_node(state)

        mock_provider.complete_structured.assert_not_called()
        assert result["quiz_questions"] == [q0]

    @pytest.mark.asyncio
    async def test_jargon_extractor_skips_llm_call_on_cache_hit(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, jargon_extractor_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_terms = [
            {"segment_id": section_id, "data": {"term": "Encoding", "definition": "Already-computed definition."}}
        ]
        mock_jobs_table = _make_jobs_table({f"jargon_extractor:{section_id}": {"terms": cached_terms}})

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_provider = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await jargon_extractor_node(state)

        mock_provider.complete_structured.assert_not_called()
        assert result["glossary"] == cached_terms

    @pytest.mark.asyncio
    async def test_intervention_messages_skips_llm_call_on_cache_hit(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, intervention_messages_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_interventions = {
            "segment_id": section_id,
            "data": {
                "distraction": ["d1", "d2", "d3"],
                "confusion": ["c1", "c2", "c3"],
                "fatigue": ["f1", "f2", "f3"],
            },
        }
        mock_jobs_table = _make_jobs_table({f"intervention_messages:{section_id}": cached_interventions})

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_provider = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await intervention_messages_node(state)

        mock_provider.complete_structured.assert_not_called()
        assert result["intervention_prompts"] == [cached_interventions]

    @pytest.mark.asyncio
    async def test_narration_generator_skips_llm_call_on_cache_hit(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, narration_generator_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_narration = {
            "segment_id": section_id,
            "script": "Already-computed script.",
            "narration_style": "conversational",
            "word_count": 3,
        }
        mock_jobs_table = _make_jobs_table({f"narration_generator:{section_id}": cached_narration})

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_provider = AsyncMock()

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state()
            result = await narration_generator_node(state)

        mock_provider.complete_structured.assert_not_called()
        assert result["narration_scripts"] == [cached_narration]


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

        # Dev Notes / AC-2: a client-side node_outputs blob update must NOT
        # also happen — that's the exact race this story exists to remove
        # (review finding: this assertion was previously mislabeled "AC-5",
        # which is actually about test_phase1_economy_nodes.py's behavior
        # staying unchanged, not the write mechanism).
        mock_jobs_table.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_dispatches_for_different_sections_write_independent_rpc_calls(self) -> None:
        """Review finding: the original test suite never exercised real
        concurrency despite that being the stated justification for the RPC.
        A mock can't prove server-side atomicity, but it CAN prove there is
        no client-side shared/mutable buffer for concurrent dispatches to
        race on — `_write_phase1_checkpoint` passes each call's key/value
        straight through to `.rpc()` with no local read-modify-write step at
        all, so concurrent asyncio tasks calling it cannot clobber each
        other's params (unlike the old read-modify-write pattern this design
        replaces). Runs 3 sections through summarise_segment_node via
        asyncio.gather and asserts 3 distinct, uncorrupted RPC calls.
        """
        import asyncio

        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        sections = [SECTION_0, SECTION_1, SECTION_2]
        mock_jobs_table = _make_jobs_table({})
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        mock_provider = AsyncMock()

        async def _fake_complete_structured(messages, model, schema):
            # Distinguish which section this call is for via the prompt body,
            # so concurrent calls can be told apart in the assertions below.
            body = messages[1]["content"]
            return type("Summary", (), {"summary": f"Summary for: {body[:20]}"})()

        mock_provider.complete_structured.side_effect = _fake_complete_structured

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            await asyncio.gather(
                *[
                    summarise_segment_node(_base_state(_section=s, _section_index=i))
                    for i, s in enumerate(sections)
                ]
            )

        assert mock_supabase.rpc.call_count == 3
        written_keys = {call.args[1]["p_key"] for call in mock_supabase.rpc.call_args_list}
        expected_keys = {f"summarise_segment:{_derive_section_id(s, i)}" for i, s in enumerate(sections)}
        assert written_keys == expected_keys, "concurrent dispatches must each write their own distinct key"


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
    async def test_completing_a_dispatch_adds_to_redis_progress_set(self) -> None:
        """AC-4: progress_pct can't be written by economy nodes directly
        (concurrent writes to a non-reducer PipelineState key raise
        InvalidUpdateError — see Story 2-1's review findings), so Phase 1
        progress visibility must go through a separate channel: a Redis SET
        of completed checkpoint keys (SADD, counted via SCARD) — not a plain
        INCR counter, which would double-count a section re-visited on an
        ARQ retry (review finding). SADD is idempotent: re-adding the same
        key is a no-op.
        """
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

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

        mock_redis.sadd.assert_called_once()
        set_key, member = mock_redis.sadd.call_args[0][0], mock_redis.sadd.call_args[0][1]
        assert set_key == f"job:{FAKE_LESSON_ID}:phase1_completed_keys"
        assert member == f"summarise_segment:{_derive_section_id(SECTION_0, 0)}"
        mock_redis.scard.assert_called_once_with(set_key)

    @pytest.mark.asyncio
    async def test_retry_revisiting_a_cached_section_does_not_double_count(self) -> None:
        """Review finding: an INCR-based counter double-counts on ARQ retry —
        re-visiting an already-checkpointed section on retry must NOT inflate
        the progress count past the true number of distinct completed
        sections. SADD's idempotency (same member added twice = no growth)
        is what this test actually verifies, in place of the old INCR-based
        test that (per the review) locked in the double-counting bug as
        "correct."
        """
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        section_id = _derive_section_id(SECTION_0, 0)
        cached_summary = {"segment_id": section_id, "summary": "Cached."}
        mock_jobs_table = _make_jobs_table({f"summarise_segment:{section_id}": cached_summary})
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table

        # A real Redis SADD returns 0 when the member already exists — assert
        # the node doesn't misinterpret that as "not completed."
        mock_redis = AsyncMock()
        mock_redis.sadd.return_value = 0
        mock_redis.scard.return_value = 1

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.core.redis.get_redis", return_value=mock_redis
        ):
            state = _base_state(_total_sections=3)
            result = await summarise_segment_node(state)

        mock_redis.sadd.assert_called_once_with(
            f"job:{FAKE_LESSON_ID}:phase1_completed_keys", f"summarise_segment:{section_id}"
        )
        assert result["segment_summaries"] == [cached_summary]


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
