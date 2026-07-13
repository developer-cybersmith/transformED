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
from unittest.mock import AsyncMock, patch

import pytest

# Force the submodule into sys.modules / onto the parent package's namespace so
# patch("app.providers.llm.openai.OpenAILLMProvider", ...) can resolve it —
# graph.py's lazy in-function imports mean nothing else guarantees this import
# has already happened by the time these tests run.
import app.providers.llm.openai as openai_provider_module  # noqa: E402

FAKE_LESSON_ID = "20202020-2020-2020-2020-202020202020"
FAKE_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"

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
        from app.modules.content.pipeline.graph import summarise_segment_node

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
        assert result["segment_summaries"][0]["segment_id"] == THREE_SECTIONS[0]["title"]

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
        from app.modules.content.pipeline.graph import segment_complexity_node
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
        assert score["segment_id"] == THREE_SECTIONS[0]["title"]
        # The complexity fields (everything but the segment_id correlation key)
        # must round-trip through the frozen SegmentComplexity model without
        # error — segment_id itself is NOT part of that model (it lives on the
        # parent Segment; SegmentComplexity has extra="forbid" so it would
        # reject a dict that still included it).
        SegmentComplexity.model_validate({k: v for k, v in score.items() if k != "segment_id"})

    @pytest.mark.asyncio
    async def test_out_of_range_intervention_sensitivity_is_rejected_not_silently_clamped(self) -> None:
        """An LLM response with intervention_sensitivity=1.4 must not silently
        pass through — the node must reject/clamp-with-logging, never trust
        the raw value into state unchanged.
        """
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
        # Simulate the provider returning a dict/object with an out-of-range value
        # (structured-output providers can still surface invalid values that
        # violate the response_format's own constraints under model drift).
        mock_provider.complete_structured.return_value = type("Bad", (), bad_dict)()

        with patch("app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider):
            state = _base_state(_section=THREE_SECTIONS[0], _section_index=0)
            result = await segment_complexity_node(state)

        score = result["complexity_scores"][0]
        assert 0.0 <= score["intervention_sensitivity"] <= 1.0, (
            f"intervention_sensitivity={score['intervention_sensitivity']} escaped the "
            f"[0.0, 1.0] guard — AC-2 requires reject/clamp, not pass-through"
        )
