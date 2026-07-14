"""
RED-phase unit tests for Story 2-1 (Phase 1 economy nodes) — graph.py lane.

Covers, per docs/stories/2-1-phase1-economy-nodes.md:
- AC-0: graph re-architecture — Phase 1 economy nodes must all execute (fanned
  out once per section) before lesson_planner runs; lesson_planner must not
  depend on raw_text/chunks content.
- AC-1: summarise_segment — <=100 words, one call per section.
- AC-2: segment_complexity — SegmentComplexity validation, intervention_sensitivity
  range guard.

These tests are written against the DESIRED post-implementation behavior and
are expected to FAIL against the current stub graph.py (RED phase). All
external services (OpenAI provider) are mocked; patching targets the SOURCE
modules per the project's established convention (graph.py uses lazy
in-function imports — see test_pipeline_tier1.py's module docstring).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force the submodule into sys.modules / onto the parent package's namespace so
# patch("app.providers.llm.openai.OpenAILLMProvider", ...) can resolve it —
# graph.py's lazy in-function imports mean nothing else guarantees this import
# has already happened by the time these tests run.
import app.providers.llm.openai as openai_provider_module  # noqa: E402

FAKE_LESSON_ID = "20202020-2020-2020-2020-202020202020"
FAKE_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _no_checkpoint_infra():
    """Story 2-1b added a per-section checkpoint (Supabase read/write) and a
    Redis progress counter to summarise_segment_node/segment_complexity_node.
    This file's tests predate that and don't care about checkpoint behavior
    (that's test_phase1_checkpoint_idempotency.py's job) — auto-mock both as
    a permanent cache-miss / no-op so these tests keep exercising only what
    they originally intended, per Story 2-1's AC-5 ("this story only adds
    idempotency, it does not change external behavior when no cache hit
    exists" — the tests needed this mocking added since real Supabase/Redis
    calls didn't exist when they were first written).
    """
    mock_jobs_table = MagicMock()
    mock_jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": {}
    }
    mock_supabase = MagicMock()
    mock_supabase.table.return_value = mock_jobs_table
    mock_supabase.rpc.return_value.execute.return_value = MagicMock()

    # Story 2-1 AC-7 added a cost_tracker.check_ceiling() call to
    # _fan_out_phase1_economy_nodes -> get_cost() -> redis.get(). An
    # unconfigured AsyncMock's .get() resolves to a MagicMock (not None or a
    # numeric string), and get_cost() does float(raw) unconditionally when
    # raw is not None — that would raise TypeError for every test in this
    # file that reaches the router, not just AC-7's own tests. Pin .get() to
    # None so get_cost() takes its documented "unknown -> 0.0" branch,
    # matching this fixture's existing "no real infra" intent for every test
    # EXCEPT TestAC7CostCeiling, which overrides this mock itself per-test.
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
        "app.core.redis.get_redis", return_value=mock_redis
    ):
        yield

THREE_SECTIONS: list[dict[str, Any]] = [
    {"title": "Spaced Repetition", "body": "prose about spaced repetition. " * 20, "page_start": 1, "page_end": 3},
    {"title": "Active Recall", "body": "prose about active recall. " * 20, "page_start": 4, "page_end": 6},
    {"title": "Interleaving", "body": "prose about interleaving practice. " * 20, "page_start": 7, "page_end": 9},
]

ECONOMY_NODE_NAMES = [
    "summarise_segment",
    "quiz_generator",
    "segment_complexity",
    "jargon_extractor",
    "intervention_messages",
    "narration_generator",
]


def _base_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "lesson_id": FAKE_LESSON_ID,
        "user_id": FAKE_USER_ID,
        "book_id": FAKE_BOOK_ID,
        "sections": THREE_SECTIONS,
        "progress_pct": 28.0,
        "error": None,
    }
    state.update(overrides)
    return state


# ── AC-0: graph ordering ──────────────────────────────────────────────────────


class TestAC0GraphOrdering:
    """The stub graph currently wires lesson_planner directly after embed,
    before any economy node runs — this is the exact 5x-cost-overrun bug
    described in Story 2-1's Context section. These tests assert the fix.
    """

    def test_no_direct_edge_from_embed_to_lesson_planner(self) -> None:
        """embed must NOT route straight to lesson_planner — it must route
        through the six economy nodes first (directly or via a fan-out
        dispatcher node), with lesson_planner only reachable after a barrier.
        """
        from app.modules.content.pipeline.graph import get_pipeline_graph

        compiled = get_pipeline_graph()
        edges = compiled.get_graph().edges
        direct_edge = any(e.source == "embed" and e.target == "lesson_planner" for e in edges)
        assert not direct_edge, (
            "embed -> lesson_planner is wired directly, bypassing all Phase 1 "
            "economy nodes (AC-0 violation — see Story 2-1 Context)"
        )

    def test_all_six_economy_nodes_present_in_graph(self) -> None:
        from app.modules.content.pipeline.graph import get_pipeline_graph

        compiled = get_pipeline_graph()
        node_names = set(compiled.get_graph().nodes.keys())
        missing = [n for n in ECONOMY_NODE_NAMES if n not in node_names]
        assert not missing, f"Economy nodes missing from compiled graph: {missing}"

    @pytest.mark.asyncio
    async def test_economy_nodes_run_before_lesson_planner_and_fan_out_per_section(self) -> None:
        """Behavioral test: instrument every node function to record call order
        and state snapshot, run the graph end-to-end from a post-embed state,
        and assert (a) all 6 economy nodes were called strictly before
        lesson_planner, and (b) each economy node was invoked once per section
        (3 sections -> 3 calls each), not once for the whole chapter.
        """
        from app.modules.content.pipeline import graph as graph_module

        call_log: list[str] = []

        def _make_economy_stub(name: str):
            # Economy-node stubs must NOT spread **state / return progress_pct:
            # up to len(sections) * 6 parallel Send() dispatches write concurrently
            # in the same superstep, and progress_pct has no reducer — a second
            # concurrent writer to a non-reducer key raises LangGraph's
            # InvalidUpdateError. Only contribute this node's own reduced key.
            async def _stub(state: dict[str, Any]) -> dict[str, Any]:
                call_log.append(name)
                return {}

            return _stub

        def _make_barrier_stub(name: str):
            # Barrier/downstream nodes (including Phase A, which only runs once
            # per pipeline invocation) — safe to spread state.
            async def _stub(state: dict[str, Any]) -> dict[str, Any]:
                call_log.append(name)
                return {**state, "progress_pct": state.get("progress_pct", 0.0) + 1.0}

            return _stub

        patches = [
            patch.object(graph_module, f"{name}_node", _make_economy_stub(name)) for name in ECONOMY_NODE_NAMES
        ] + [
            patch.object(graph_module, name, _make_barrier_stub(name))
            for name in [
                "extract_node",
                "structure_node",
                "chunk_node",
                "embed_node",
                "lesson_planner_node",
                "slide_generator_node",
                "tts_node",
                "image_generator_node",
                "package_builder_node",
            ]
        ]
        for p in patches:
            p.start()
        try:
            # get_pipeline_graph() caches a module-level compiled graph built
            # from whichever function bindings existed at first call in this
            # process — irrelevant to what's patched now. Build fresh so this
            # test's patches actually take effect.
            compiled = graph_module._build_pipeline_graph()
            initial_state = _base_state()
            config = {"configurable": {"thread_id": FAKE_LESSON_ID}}
            await compiled.ainvoke(initial_state, config=config)
        finally:
            for p in patches:
                p.stop()

        assert "lesson_planner_node" in call_log, "lesson_planner was never invoked"
        planner_index = call_log.index("lesson_planner_node")
        assert call_log.count("lesson_planner_node") == 1, (
            f"lesson_planner_node ran {call_log.count('lesson_planner_node')} times — "
            f"expected exactly 1 (a bug causing it to run once per fanned-out dispatch, "
            f"e.g. 18x, would silently multiply Phase 2's premium-model cost)"
        )
        for economy_node in ECONOMY_NODE_NAMES:
            occurrences = [i for i, n in enumerate(call_log) if n == economy_node]
            assert occurrences, f"{economy_node} was never invoked"
            assert all(i < planner_index for i in occurrences), (
                f"{economy_node} was invoked at index {occurrences} but lesson_planner "
                f"ran at index {planner_index} — Phase 1 must fully complete before Phase 2 starts"
            )
            assert len(occurrences) == len(THREE_SECTIONS), (
                f"{economy_node} was invoked {len(occurrences)} time(s) for "
                f"{len(THREE_SECTIONS)} sections — expected one call per section (Send() fan-out), "
                f"not once for the whole chapter"
            )

    @pytest.mark.asyncio
    async def test_empty_sections_raises_clear_error(self) -> None:
        """Review finding (2026-07-13, decision: fail fast): an empty
        state["sections"] must not let the pipeline silently end after embed
        with no lesson_package and no failed status — it must raise clearly
        so content_pipeline_job can mark the job failed.

        Story 2-1 AC-7 made this router async (it now awaits
        cost_tracker.check_ceiling()) — this test awaits it accordingly. The
        empty-sections check runs BEFORE the cost-ceiling check (see AC-7
        docstring), so this still raises without touching cost_tracker at all.
        """
        from app.modules.content.pipeline.graph import _fan_out_phase1_economy_nodes

        with pytest.raises(RuntimeError, match="zero sections"):
            await _fan_out_phase1_economy_nodes(_base_state(sections=[]))

    @pytest.mark.asyncio
    async def test_lesson_planner_does_not_require_raw_text_or_chunks(self) -> None:
        """lesson_planner_node must be callable from a state that has
        segment_summaries populated but raw_text/chunks entirely absent, and
        must actually read segment_summaries (not ignore them) — proving the
        graph wiring delivers Phase 1 output where lesson_planner can consume
        it. NOTE: this only asserts AC-0 (wiring/consumption), not full content
        generation — real GPT-4o lesson planning is S2-7, a separate story.
        """
        from app.modules.content.pipeline.graph import lesson_planner_node

        summaries = [
            {"segment_id": s["title"], "summary": f"Summary of {s['title']}."} for s in THREE_SECTIONS
        ]
        state = _base_state(segment_summaries=summaries)
        assert "raw_text" not in state
        assert "chunks" not in state

        result = await lesson_planner_node(state)

        assert result["lesson_plan"]["total_segments"] == len(summaries), (
            "lesson_planner_node did not read state['segment_summaries'] — "
            "AC-0 requires the graph to actually deliver Phase 1 output to "
            "this node, not just avoid crashing"
        )


# ── AC-1: summarise_segment ───────────────────────────────────────────────────


class TestAC1SummariseSegment:
    """Story 2-1 AC-0 commits to Send()-based fan-out: the graph dispatches
    summarise_segment_node ONCE PER SECTION via state['_section'], not once
    for the whole chapter (that per-section dispatch COUNT is verified at the
    graph level by TestAC0GraphOrdering). These tests exercise a single
    section-scoped invocation.
    """

    @pytest.mark.asyncio
    async def test_single_invocation_makes_exactly_one_provider_call(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, summarise_segment_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = type(
            "Summary", (), {"summary": "A short summary under the word cap."}
        )()

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await summarise_segment_node(state)

        assert mock_provider.complete_structured.call_count == 1, (
            f"a single section-scoped invocation must make exactly one "
            f"complete_structured call, got {mock_provider.complete_structured.call_count}"
        )
        assert len(result["segment_summaries"]) == 1
        assert result["segment_summaries"][0]["segment_id"] == _derive_section_id(THREE_SECTIONS[0], 0)

    @pytest.mark.asyncio
    async def test_llm_refusal_degrades_section_instead_of_crashing(self) -> None:
        """A content-policy refusal (or failed function-call parse) leaves
        message.parsed = None — complete_structured returning None must
        degrade this one section, not raise an unhandled AttributeError.
        """
        from app.modules.content.pipeline.graph import summarise_segment_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await summarise_segment_node(state)

        assert result["segment_summaries"] == []

    @pytest.mark.asyncio
    async def test_rejects_summary_over_100_words(self) -> None:
        from app.modules.content.pipeline.graph import summarise_segment_node

        too_long = " ".join(["word"] * 150)
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = type("Summary", (), {"summary": too_long})()

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await summarise_segment_node(state)

        summaries = result["segment_summaries"]
        assert len(summaries) == 1
        word_count = len(summaries[0]["summary"].split())
        assert word_count <= 100, (
            f"summary has {word_count} words — AC-1 requires <=100 words, "
            f"node must truncate/reject/regenerate an over-length LLM response"
        )


# ── AC-2: segment_complexity ─────────────────────────────────────────────────


class TestAC2SegmentComplexity:
    @pytest.mark.asyncio
    async def test_output_validates_against_segment_complexity_schema(self) -> None:
        from app.modules.content.pipeline.graph import _derive_section_id, segment_complexity_node
        from app.schemas.lesson import SegmentComplexity

        mock_output = SegmentComplexity(
            level="medium",
            cognitive_load="moderate",
            abstraction_level="concrete-to-abstract",
            prerequisite_concepts=["memory basics"],
            narration_style="conversational",
            quiz_difficulty="medium",
            intervention_sensitivity=0.5,
        )
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await segment_complexity_node(state)

        assert len(result["complexity_scores"]) == 1
        score = result["complexity_scores"][0]
        assert score["segment_id"] == _derive_section_id(THREE_SECTIONS[0], 0)
        # The complexity fields (everything but the segment_id correlation key)
        # must round-trip through the frozen SegmentComplexity model without
        # error — segment_id itself is NOT part of that model (it lives on the
        # parent Segment; SegmentComplexity has extra="forbid" so it would
        # reject a dict that still included it).
        SegmentComplexity.model_validate({k: v for k, v in score.items() if k != "segment_id"})

    @pytest.mark.asyncio
    async def test_out_of_range_intervention_sensitivity_is_rejected_not_silently_clamped(self, caplog) -> None:
        """An LLM response with intervention_sensitivity=1.4 must not silently
        pass through — the node must reject/clamp-with-logging, never trust
        the raw value into state unchanged. Also verifies the clamp is not
        silent: a warning must actually be logged (review finding — the prior
        version of this test only checked the final value, not that logging
        occurred).
        """
        import logging

        from app.modules.content.pipeline.graph import segment_complexity_node

        bad_dict = {
            "level": "high",
            "cognitive_load": "high",
            "abstraction_level": "abstract",
            "prerequisite_concepts": [],
            "narration_style": "formal",
            "quiz_difficulty": "hard",
            "intervention_sensitivity": 1.4,
        }
        mock_provider = AsyncMock()
        # _SegmentComplexityLLM has no ge/le constraint (that's the point — see
        # its docstring), so this out-of-range value parses without raising,
        # exercising the real code path rather than a hand-built non-Pydantic mock.
        mock_provider.complete_structured.return_value = type("Bad", (), bad_dict)()

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            with caplog.at_level(logging.WARNING):
                state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
                result = await segment_complexity_node(state)

        score = result["complexity_scores"][0]
        assert 0.0 <= score["intervention_sensitivity"] <= 1.0, (
            f"intervention_sensitivity={score['intervention_sensitivity']} escaped the "
            f"[0.0, 1.0] guard — AC-2 requires reject/clamp, not pass-through"
        )
        assert any("out of range" in r.message for r in caplog.records), (
            "clamping intervention_sensitivity must log a warning — the guard "
            "must not be silent, per this test's own name"
        )

    @pytest.mark.asyncio
    async def test_llm_refusal_degrades_section_instead_of_crashing(self) -> None:
        from app.modules.content.pipeline.graph import segment_complexity_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await segment_complexity_node(state)

        assert result["complexity_scores"] == []

    @pytest.mark.asyncio
    async def test_duplicate_section_titles_do_not_collide_on_segment_id(self) -> None:
        """Two sections sharing a title (e.g. two "Introduction" sections in
        different chapters) must NOT produce the same segment_id — otherwise
        operator.add's no-dedup concatenation gives lesson_planner two scores
        under one ambiguous key (review finding).
        """
        from app.modules.content.pipeline.graph import segment_complexity_node

        duplicate_title_sections = [
            {"title": "Introduction", "body": "First introduction section body."},
            {"title": "Introduction", "body": "Second, different introduction section body."},
        ]
        mock_output = type(
            "Bad",
            (),
            {
                "level": "low",
                "cognitive_load": "low",
                "abstraction_level": "concrete",
                "prerequisite_concepts": [],
                "narration_style": "casual",
                "quiz_difficulty": "easy",
                "intervention_sensitivity": 0.2,
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            results = [
                await segment_complexity_node(_base_state(_section=s, _section_index=i))
                for i, s in enumerate(duplicate_title_sections)
            ]

        ids = [r["complexity_scores"][0]["segment_id"] for r in results]
        assert ids[0] != ids[1], f"duplicate-titled sections collided on segment_id: {ids}"


# ── AC-3: quiz_generator ────────────────────────────────────────────────────


class TestAC3QuizGenerator:
    @pytest.mark.asyncio
    async def test_single_invocation_makes_exactly_one_provider_call(self) -> None:
        from app.schemas.lesson import QuizQuestion
        from app.modules.content.pipeline.graph import _derive_section_id, quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "What is spaced repetition?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 1,
                "explanation": "B is correct because...",
                "difficulty": "medium",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert mock_provider.complete_structured.call_count == 1
        assert len(result["quiz_questions"]) == 1
        q = result["quiz_questions"][0]
        assert q["segment_id"] == _derive_section_id(THREE_SECTIONS[0], 0)
        assert len(q["data"]["options"]) == 4
        # AC-3: "Output validates against app.schemas.lesson.QuizQuestion list."
        # Output is nested (2026-07-14 review finding, decision resolved same
        # day): {"segment_id": ..., "data": {...}} — segment_id lives outside
        # the QuizQuestion-shaped sub-object, so data validates with ZERO
        # stripping (the AC's literal "no reshaping" requirement, actually met).
        QuizQuestion.model_validate(q["data"])

    @pytest.mark.asyncio
    async def test_five_options_are_truncated_to_exactly_four_not_passed_through(self) -> None:
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "Which is a memory technique?",
                "options": ["A", "B", "C", "D", "E"],
                "correct_index": 0,
                "explanation": "A is correct.",
                "difficulty": "easy",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert len(result["quiz_questions"]) == 1
        assert len(result["quiz_questions"][0]["data"]["options"]) == 4, (
            "5-option LLM output must be truncated to exactly 4, not passed through"
        )

    @pytest.mark.asyncio
    async def test_duplicate_options_are_rejected(self) -> None:
        """2026-07-14 review finding (Edge Case Hunter, decision resolved same
        day): all 4 options being identical text must not ship as a
        nonsensical MCQ."""
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "Which is a memory technique?",
                "options": ["Spaced repetition", "Spaced repetition", "Spaced repetition", "Spaced repetition"],
                "correct_index": 0,
                "explanation": "A is correct.",
                "difficulty": "easy",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert result["quiz_questions"] == []

    @pytest.mark.asyncio
    async def test_blank_correct_option_text_is_rejected(self) -> None:
        """2026-07-14 review finding (Edge Case Hunter, decision resolved same
        day): the correct option's own text being blank while distractors are
        populated must not ship."""
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "Which is a memory technique?",
                "options": ["   ", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "A is correct.",
                "difficulty": "easy",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert result["quiz_questions"] == []

    @pytest.mark.asyncio
    async def test_too_few_options_is_rejected(self) -> None:
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "Which is a memory technique?",
                "options": ["A", "B"],
                "correct_index": 0,
                "explanation": "A is correct.",
                "difficulty": "easy",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert result["quiz_questions"] == []

    @pytest.mark.asyncio
    async def test_out_of_range_correct_index_is_rejected(self) -> None:
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "Which is a memory technique?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 7,
                "explanation": "A is correct.",
                "difficulty": "easy",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert result["quiz_questions"] == []

    @pytest.mark.asyncio
    async def test_blank_question_or_explanation_is_rejected(self) -> None:
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_output = type(
            "Quiz",
            (),
            {
                "question": "   ",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "A is correct.",
                "difficulty": "easy",
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert result["quiz_questions"] == []

    @pytest.mark.asyncio
    async def test_llm_refusal_degrades_section_instead_of_crashing(self) -> None:
        from app.modules.content.pipeline.graph import quiz_generator_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await quiz_generator_node(state)

        assert result["quiz_questions"] == []


# ── AC-4: jargon_extractor ──────────────────────────────────────────────────


class TestAC4JargonExtractor:
    @pytest.mark.asyncio
    async def test_output_validates_against_jargon_entry_schema(self) -> None:
        from app.schemas.lesson import JargonEntry
        from app.modules.content.pipeline.graph import jargon_extractor_node

        mock_output = type(
            "Jargon",
            (),
            {
                "terms": [
                    type("Entry", (), {"term": "Encoding", "definition": "Converting info into memory."})(),
                ]
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await jargon_extractor_node(state)

        assert len(result["glossary"]) == 1
        entry = result["glossary"][0]
        # Nested output (2026-07-14 review finding, decision resolved same
        # day): {"segment_id": ..., "data": {"term", "definition"}} — validates
        # with zero stripping.
        JargonEntry.model_validate(entry["data"])

    @pytest.mark.asyncio
    async def test_empty_term_or_definition_is_filtered_out(self) -> None:
        from app.modules.content.pipeline.graph import jargon_extractor_node

        mock_output = type(
            "Jargon",
            (),
            {
                "terms": [
                    type("Entry", (), {"term": "Encoding", "definition": "Converting info into memory."})(),
                    type("Entry", (), {"term": "  ", "definition": "Has a blank term."})(),
                    type("Entry", (), {"term": "Chunking", "definition": "   "})(),
                ]
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await jargon_extractor_node(state)

        assert len(result["glossary"]) == 1, (
            f"expected only the one valid entry to survive, got {result['glossary']}"
        )
        assert result["glossary"][0]["data"]["term"] == "Encoding"

    @pytest.mark.asyncio
    async def test_llm_refusal_degrades_section_instead_of_crashing(self) -> None:
        from app.modules.content.pipeline.graph import jargon_extractor_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await jargon_extractor_node(state)

        assert result["glossary"] == []


# ── AC-5: intervention_messages ─────────────────────────────────────────────


class TestAC5InterventionMessages:
    @pytest.mark.asyncio
    async def test_output_validates_with_exactly_3x3_messages(self) -> None:
        from app.schemas.lesson import SegmentInterventions
        from app.modules.content.pipeline.graph import intervention_messages_node

        mock_output = type(
            "Interventions",
            (),
            {
                "distraction": ["d1", "d2", "d3"],
                "confusion": ["c1", "c2", "c3"],
                "fatigue": ["f1", "f2", "f3"],
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await intervention_messages_node(state)

        assert len(result["intervention_prompts"]) == 1
        prompts = result["intervention_prompts"][0]
        # Nested output (2026-07-14 review finding, decision resolved same
        # day) — validates with zero stripping.
        SegmentInterventions.model_validate(prompts["data"])

    @pytest.mark.asyncio
    async def test_output_shape_pins_what_package_builder_will_assign_verbatim(self) -> None:
        """AC-5's second test requirement: 'a snapshot test asserting the dict
        shape matches what package_builder_node (S2-11, future) will assign
        verbatim to Segment.interventions.' package_builder_node doesn't exist
        yet (S2-11), so this pins the best available proxy today — the exact
        key set intervention_messages_node produces — so a future S2-11
        implementation has a concrete, tested contract to assign from, and any
        accidental key rename/addition here is caught now rather than at S2-11
        integration time (review finding, 2026-07-14).
        """
        from app.modules.content.pipeline.graph import intervention_messages_node

        mock_output = type(
            "Interventions",
            (),
            {"distraction": ["d1", "d2", "d3"], "confusion": ["c1", "c2", "c3"], "fatigue": ["f1", "f2", "f3"]},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await intervention_messages_node(state)

        prompts = result["intervention_prompts"][0]
        assert set(prompts.keys()) == {"segment_id", "data"}, (
            f"intervention_messages_node's top-level output shape changed to "
            f"{set(prompts.keys())} — package_builder_node (S2-11) will need "
            f"segment_id for correlation and data for the SegmentInterventions "
            f"payload; an unreviewed shape change here breaks that future "
            f"integration silently"
        )
        assert set(prompts["data"].keys()) == {"distraction", "confusion", "fatigue"}, (
            f"intervention_messages_node's data shape changed to {set(prompts['data'].keys())} — "
            f"package_builder_node (S2-11) will need to assign this dict verbatim to "
            f"Segment.interventions; an unreviewed shape change here breaks that "
            f"future integration silently"
        )

    @pytest.mark.asyncio
    async def test_off_count_messages_are_forced_to_exactly_three_each(self) -> None:
        """CRITICAL (PRD §10): the runtime tutor never calls an LLM for
        intervention text — these messages are the entire supply. A 2-message
        or 5-message type must never survive into state; always exactly 3.
        """
        from app.modules.content.pipeline.graph import intervention_messages_node

        mock_output = type(
            "Interventions",
            (),
            {
                "distraction": ["d1", "d2"],  # too few
                "confusion": ["c1", "c2", "c3", "c4", "c5"],  # too many
                "fatigue": ["f1", "f2", "f3"],  # exactly right
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await intervention_messages_node(state)

        prompts = result["intervention_prompts"][0]
        assert len(prompts["data"]["distraction"]) == 3
        assert len(prompts["data"]["confusion"]) == 3
        assert len(prompts["data"]["fatigue"]) == 3

    @pytest.mark.asyncio
    async def test_llm_refusal_still_produces_guaranteed_3x3_fallback(self) -> None:
        """2026-07-14 review finding (Blind Hunter, CRITICAL, fixed): a total
        LLM refusal previously returned an empty list here, bypassing the
        pad-to-3 guarantee this node otherwise provides — silently disabling
        all three trigger types for the section (PRD §10: this is the ENTIRE
        runtime supply, no LLM fallback exists at intervention time). A
        refusal must still produce exactly 3x3 messages via the same padding
        path as a partial response.
        """
        from app.modules.content.pipeline.graph import intervention_messages_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await intervention_messages_node(state)

        assert len(result["intervention_prompts"]) == 1, (
            "a total LLM refusal must still yield a guaranteed 3x3 fallback, not an empty list"
        )
        prompts = result["intervention_prompts"][0]["data"]
        assert len(prompts["distraction"]) == 3
        assert len(prompts["confusion"]) == 3
        assert len(prompts["fatigue"]) == 3

    @pytest.mark.asyncio
    async def test_degraded_padded_output_is_not_checkpointed(self) -> None:
        """2026-07-14 review finding (decision resolved same day): padded
        output must not be checkpointed as if it were a clean success — a
        transient bad LLM response should get a fresh attempt on the next ARQ
        retry, not permanently supply padded/generic messages.
        """
        from app.modules.content.pipeline.graph import intervention_messages_node

        mock_output = type(
            "Interventions",
            (),
            {
                "distraction": ["d1", "d2"],  # too few -> padding required
                "confusion": ["c1", "c2", "c3"],
                "fatigue": ["f1", "f2", "f3"],
            },
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output
        mock_supabase = MagicMock()
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider), patch(
            "app.core.db.get_supabase", return_value=mock_supabase
        ):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            await intervention_messages_node(state)

        mock_supabase.rpc.assert_not_called()

    @pytest.mark.asyncio
    async def test_clean_3x3_output_is_checkpointed(self) -> None:
        """Counterpart to the degraded-output test above — a genuinely clean
        3x3 response (no padding needed) must still be checkpointed normally."""
        from app.modules.content.pipeline.graph import intervention_messages_node

        mock_output = type(
            "Interventions",
            (),
            {"distraction": ["d1", "d2", "d3"], "confusion": ["c1", "c2", "c3"], "fatigue": ["f1", "f2", "f3"]},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output
        mock_supabase = MagicMock()
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider), patch(
            "app.core.db.get_supabase", return_value=mock_supabase
        ):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            await intervention_messages_node(state)

        mock_supabase.rpc.assert_called_once()


# ── AC-6: narration_generator ───────────────────────────────────────────────


class TestAC6NarrationGenerator:
    @pytest.mark.asyncio
    async def test_narration_style_sourced_from_matching_section_complexity_when_available(self) -> None:
        """AC-6: 'the prompt must include the corresponding complexity's
        narration_style field, not generate narration blind to complexity.'
        Review finding (2026-07-14): the original implementation never read
        segment_complexity's output at all. When segment_complexity_node's
        checkpoint for the SAME section is already written (a real, common
        case — Send()-dispatched sibling calls do not resolve in lockstep),
        narration_generator_node must use that known narration_style, not the
        LLM's own guess — this is the AC's actual requirement.
        """
        from app.modules.content.pipeline.graph import _derive_section_id, narration_generator_node

        section_id = _derive_section_id(THREE_SECTIONS[0], 0)
        known_complexity = {
            "segment_id": section_id,
            "narration_style": "formal-technical",
        }
        mock_jobs_table = MagicMock()

        def _select_side_effect():
            table = MagicMock()
            table.eq.return_value.maybe_single.return_value.execute.return_value.data = {
                "node_outputs": {f"segment_complexity:{section_id}": known_complexity}
            }
            return table

        mock_jobs_table.select.side_effect = lambda *a, **k: _select_side_effect()
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_jobs_table
        mock_supabase.rpc.return_value.execute.return_value = MagicMock()

        mock_output = type(
            "Narration",
            (),
            {"narration_style": "energetic", "script": "Let's talk about spaced repetition."},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
        ), patch("app.core.redis.get_redis", return_value=AsyncMock()):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await narration_generator_node(state)

        script = result["narration_scripts"][0]
        assert script["narration_style"] == "formal-technical", (
            f"expected the known segment_complexity narration_style to win over the "
            f"LLM's own guess ('energetic'), got {script['narration_style']!r}"
        )
        # The prompt sent to the LLM must reference the known style, per AC-6's
        # "the prompt must include the corresponding complexity's narration_style field".
        sent_messages = mock_provider.complete_structured.call_args.args[0]
        system_content = sent_messages[0]["content"]
        assert "formal-technical" in system_content, (
            "AC-6 requires the prompt itself to include the matching section's "
            "narration_style, not just the final result dict"
        )

    @pytest.mark.asyncio
    async def test_single_invocation_produces_script_and_narration_style(self) -> None:
        from app.modules.content.pipeline.graph import narration_generator_node

        mock_output = type(
            "Narration",
            (),
            {"narration_style": "conversational", "script": "Let's talk about spaced repetition."},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await narration_generator_node(state)

        assert len(result["narration_scripts"]) == 1
        script = result["narration_scripts"][0]
        assert script["narration_style"] == "conversational"
        assert script["script"]

    @pytest.mark.asyncio
    async def test_pacing_guard_rejects_script_too_dense_for_target_duration(self) -> None:
        """A script whose word count implies >15 words/sec against an explicit
        target_duration_sec must be rejected (AC-6 pacing guard).
        """
        from app.modules.content.pipeline.graph import narration_generator_node

        dense_script = " ".join(["word"] * 200)  # 200 words
        mock_output = type(
            "Narration",
            (),
            {"narration_style": "energetic", "script": dense_script},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        section_with_target = {**THREE_SECTIONS[0], "target_duration_sec": 10}  # 200/10 = 20 words/sec > 15
        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=section_with_target, _section_index=0)
            result = await narration_generator_node(state)

        assert result["narration_scripts"] == [], (
            "a script implying 20 words/sec against a 10s target duration must be rejected (cap 15/sec)"
        )

    @pytest.mark.asyncio
    async def test_no_explicit_target_duration_falls_back_to_page_count_estimate(self) -> None:
        """THREE_SECTIONS[0] carries page_start/page_end, so without an
        explicit target_duration_sec the page-count-based estimate (~90s/page)
        applies — this section's estimate (3 pages x 90s = 270s) comfortably
        covers a 200-word script (~0.7 wps), so it must not reject.
        """
        from app.modules.content.pipeline.graph import narration_generator_node

        mock_output = type(
            "Narration",
            (),
            {"narration_style": "formal", "script": " ".join(["word"] * 200)},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await narration_generator_node(state)

        assert len(result["narration_scripts"]) == 1

    @pytest.mark.asyncio
    async def test_no_target_duration_and_no_page_range_does_not_reject(self) -> None:
        """2026-07-14 review finding (Acceptance Auditor, fixed): the prior
        'no target duration' test used THREE_SECTIONS[0], which HAS
        page_start/page_end, so it only ever exercised the page-count-estimate
        branch, never the genuinely-unguarded fallback (neither
        target_duration_sec nor page range present) — this test constructs a
        section with neither, so the true no-estimate `else: logger.info(...)`
        branch actually runs.
        """
        from app.modules.content.pipeline.graph import narration_generator_node

        section_no_metadata = {"title": "No Metadata Section", "body": "prose with no page metadata. " * 20}
        mock_output = type(
            "Narration",
            (),
            {"narration_style": "formal", "script": " ".join(["word"] * 200)},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=section_no_metadata, _section_index=0)
            result = await narration_generator_node(state)

        assert len(result["narration_scripts"]) == 1

    @pytest.mark.asyncio
    async def test_explicit_zero_target_duration_is_not_treated_as_absent(self) -> None:
        """2026-07-14 review finding (Edge Case Hunter, fixed): `target_duration_sec: 0`
        is a falsy Python value but a semantically real (pathological,
        infinite-implied-rate) explicit duration — it must be treated as such
        and rejected, not silently fall back to the page-count estimate.
        """
        from app.modules.content.pipeline.graph import narration_generator_node

        section_zero_duration = {**THREE_SECTIONS[0], "target_duration_sec": 0}
        mock_output = type(
            "Narration",
            (),
            {"narration_style": "formal", "script": " ".join(["word"] * 10)},
        )()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=section_zero_duration, _section_index=0)
            result = await narration_generator_node(state)

        assert result["narration_scripts"] == [], (
            "target_duration_sec=0 implies an infinite words/sec rate and must be "
            "rejected, not silently treated as 'absent' and estimated from page count"
        )

    @pytest.mark.asyncio
    async def test_blank_script_is_rejected(self) -> None:
        """2026-07-14 review finding (Edge Case Hunter, fixed): unlike
        quiz_generator_node/jargon_extractor_node, nothing previously rejected
        a blank script — it trivially passed the pacing guard (word_count=0).
        """
        from app.modules.content.pipeline.graph import narration_generator_node

        mock_output = type("Narration", (), {"narration_style": "formal", "script": "   "})()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await narration_generator_node(state)

        assert result["narration_scripts"] == []

    @pytest.mark.asyncio
    async def test_narration_style_falls_back_to_default_when_both_sources_blank(self) -> None:
        """2026-07-14 review finding (Edge Case Hunter, fixed): neither a
        missing segment_complexity checkpoint nor a blank LLM-self-reported
        narration_style should ever result in an empty narration_style being
        checkpointed — falls back to a sane default (mirrors
        quiz_generator_node's difficulty enum-clamp pattern).
        """
        from app.modules.content.pipeline.graph import narration_generator_node

        mock_output = type("Narration", (), {"narration_style": "   ", "script": "A valid script."})()
        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = mock_output

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await narration_generator_node(state)

        assert result["narration_scripts"][0]["narration_style"] == "conversational"

    @pytest.mark.asyncio
    async def test_llm_refusal_degrades_section_instead_of_crashing(self) -> None:
        from app.modules.content.pipeline.graph import narration_generator_node

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await narration_generator_node(state)

        assert result["narration_scripts"] == []


# ── AC-7: cost ceiling wiring ────────────────────────────────────────────────


class TestAC7CostCeiling:
    @pytest.mark.asyncio
    async def test_ceiling_breach_before_fan_out_raises_cost_ceiling_runtime_error(self) -> None:
        """A lesson already over budget must not start a new Phase 1 fan-out
        at all. content_pipeline_job's except RuntimeError handler matches on
        "cost ceiling" in the message to produce the cost_ceiling_exceeded:
        error prefix — this test asserts the router raises that shape.
        """
        from app.modules.content.pipeline.graph import _fan_out_phase1_economy_nodes

        with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=True)):
            with pytest.raises(RuntimeError, match="cost ceiling"):
                await _fan_out_phase1_economy_nodes(_base_state())

    @pytest.mark.asyncio
    async def test_ceiling_not_breached_dispatches_normally(self) -> None:
        from app.modules.content.pipeline.graph import _fan_out_phase1_economy_nodes

        with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
            dispatches = await _fan_out_phase1_economy_nodes(_base_state())

        assert len(dispatches) == len(THREE_SECTIONS) * len(ECONOMY_NODE_NAMES)

    @pytest.mark.asyncio
    async def test_empty_sections_checked_before_cost_ceiling(self) -> None:
        """Empty sections must raise its own "zero sections" error without
        ever consulting cost_tracker — asserted by never patching check_ceiling
        here (the fixture's redis.get=None default would make check_ceiling
        return False anyway, but this proves ordering, not just outcome, by
        making check_ceiling raise if it's ever called).
        """
        from app.modules.content.pipeline.graph import _fan_out_phase1_economy_nodes

        with patch(
            "app.core.cost_tracker.check_ceiling",
            new=AsyncMock(side_effect=AssertionError("check_ceiling must not be called for empty sections")),
        ):
            with pytest.raises(RuntimeError, match="zero sections"):
                await _fan_out_phase1_economy_nodes(_base_state(sections=[]))

    @pytest.mark.asyncio
    async def test_missing_lesson_id_fails_closed_not_skipped(self) -> None:
        """2026-07-14 review finding (Blind Hunter + Edge Case Hunter,
        independently, fixed): `if lesson_id:` previously SKIPPED the AC-7
        ceiling gate entirely for a falsy lesson_id, proceeding to dispatch
        as if the check had passed. Must fail closed (raise) instead.
        """
        from app.modules.content.pipeline.graph import _fan_out_phase1_economy_nodes

        with patch(
            "app.core.cost_tracker.check_ceiling",
            new=AsyncMock(side_effect=AssertionError("check_ceiling must not be called with no lesson_id")),
        ):
            with pytest.raises(RuntimeError, match="lesson_id"):
                await _fan_out_phase1_economy_nodes(_base_state(lesson_id=None))

    @pytest.mark.asyncio
    async def test_check_ceiling_failure_fails_open_and_dispatches(self) -> None:
        """2026-07-14 review finding (Edge Case Hunter, fixed): a transient
        failure of check_ceiling() itself (e.g. a Redis outage) must not
        crash the fan-out with an opaque exception — fail open (assume not
        over ceiling) and proceed, consistent with this file's established
        convention for non-critical infra checks.
        """
        from app.modules.content.pipeline.graph import _fan_out_phase1_economy_nodes

        with patch(
            "app.core.cost_tracker.check_ceiling",
            new=AsyncMock(side_effect=ConnectionError("redis unavailable")),
        ):
            dispatches = await _fan_out_phase1_economy_nodes(_base_state())

        assert len(dispatches) == len(THREE_SECTIONS) * len(ECONOMY_NODE_NAMES)

    @pytest.mark.asyncio
    async def test_section_count_is_capped_to_bound_fan_out_dos_exposure(self) -> None:
        """Review finding (2026-07-14, blind-hunter): AC-7's single pre-dispatch
        ceiling check can't see the cost the fan-out it approves will itself
        incur, and nothing bounded section count — an adversarial/oversized
        upload could dispatch an unbounded number of concurrent LLM calls
        approved by one near-$0 check. This asserts the cap actually applies.
        """
        from app.modules.content.pipeline.graph import _MAX_PHASE1_SECTIONS, _fan_out_phase1_economy_nodes

        too_many_sections = [
            {"title": f"Section {i}", "body": f"body {i}"} for i in range(_MAX_PHASE1_SECTIONS + 10)
        ]
        with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
            dispatches = await _fan_out_phase1_economy_nodes(_base_state(sections=too_many_sections))

        assert len(dispatches) == _MAX_PHASE1_SECTIONS * len(ECONOMY_NODE_NAMES), (
            f"expected fan-out capped at {_MAX_PHASE1_SECTIONS} sections x "
            f"{len(ECONOMY_NODE_NAMES)} nodes, got {len(dispatches)} dispatches "
            f"for {len(too_many_sections)} input sections"
        )

    @pytest.mark.asyncio
    async def test_economy_node_functions_never_call_circuit_breaker_or_cost_accumulation_directly(self) -> None:
        """AC-7 Test line: 'a node never calls is_circuit_open/accumulate_cost
        itself (regression guard against re-duplicating provider-layer logic)'
        — that's already handled inside OpenAILLMProvider.complete_structured().
        Patches both with a spy that raises if called, then drives every
        economy node through its normal LLM-call path.
        """
        from app.modules.content.pipeline.graph import (
            intervention_messages_node,
            jargon_extractor_node,
            narration_generator_node,
            quiz_generator_node,
            segment_complexity_node,
            summarise_segment_node,
        )

        def _forbidden(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("economy node called circuit-breaker/cost-accumulation logic directly")

        mock_provider = AsyncMock()
        mock_provider.complete_structured.return_value = None  # degrade-and-return path, cheapest to drive

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider), patch(
            "app.core.circuit_breaker.is_circuit_open", side_effect=_forbidden
        ), patch("app.core.cost_tracker.accumulate_cost", side_effect=_forbidden):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            for node in (
                summarise_segment_node,
                segment_complexity_node,
                quiz_generator_node,
                jargon_extractor_node,
                intervention_messages_node,
                narration_generator_node,
            ):
                await node(state)  # no AssertionError raised == the guard held


class TestAC7CostCeilingEndToEnd:
    @pytest.mark.asyncio
    async def test_ceiling_breach_produces_failed_status_with_cost_ceiling_exceeded_prefix(self) -> None:
        """AC-7 Test line: 'simulated ceiling breach mid-fan-out results in a
        failed status with the correct error prefix, not a stranded running
        row.' Drives content_pipeline_job's actual except-RuntimeError handler
        (apps/api/app/workers/jobs/content_pipeline.py) with the real message
        _fan_out_phase1_economy_nodes raises, confirming the 'cost ceiling'
        substring match still routes to status='failed' with the
        'cost_ceiling_exceeded:' prefix end-to-end, not just at the router
        boundary (review finding, 2026-07-14 — no prior test crossed this
        boundary).
        """
        from app.workers.jobs.content_pipeline import content_pipeline_job

        mock_jobs_table = MagicMock()
        update_calls: list[dict[str, Any]] = []

        def _capture_update(payload: dict[str, Any]) -> MagicMock:
            update_calls.append(payload)
            m = MagicMock()
            m.eq.return_value.execute.return_value = MagicMock()
            return m

        mock_jobs_table.update.side_effect = _capture_update
        mock_lessons_table = MagicMock()
        mock_lessons_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "user_id": FAKE_USER_ID,
            "source_file_path": "fake/path.pdf",
            "book_id": FAKE_BOOK_ID,
        }

        def _table(name: str) -> MagicMock:
            return mock_jobs_table if name == "lesson_jobs" else mock_lessons_table

        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = _table

        with patch("app.core.db.get_supabase", return_value=mock_supabase), patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(
                side_effect=RuntimeError(
                    f"cost ceiling exceeded before Phase 1 economy-node dispatch for lesson_id={FAKE_LESSON_ID}"
                )
            ),
        ), patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock()):
            # content_pipeline_job's cost-ceiling branch returns a dict rather
            # than re-raising (unlike other RuntimeErrors, which propagate for
            # ARQ retry) — see content_pipeline.py's except RuntimeError block.
            result = await content_pipeline_job({}, FAKE_LESSON_ID)

        assert result["status"] == "failed"
        assert result["error"].startswith("cost_ceiling_exceeded:"), (
            f"expected error prefixed 'cost_ceiling_exceeded:', got {result['error']!r}"
        )
        failed_updates = [c for c in update_calls if c.get("status") == "failed"]
        assert failed_updates, "lesson_jobs.status was never updated to 'failed' — row would be stranded at 'running'"
        assert failed_updates[-1]["error"].startswith("cost_ceiling_exceeded:")
