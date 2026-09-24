"""Story S5-4 — the WIRING half: budgets reaching the nodes that must obey them.

`test_s5_4_duration_budget.py` proves the arithmetic. Pure helpers can be
perfectly correct and never called — that is the inert-`structure_node`
precedent this repo has already paid for once (CLAUDE.md, binding rule 5).
Every test here fails if the corresponding wiring is deleted while the helper
survives:

* AC8/AC18 — content capacity actually becomes the planner's target
* AC10     — the word budget actually reaches narration's prompt
* AC11     — out-of-band scripts are kept AND flagged on the node's output
* AC12     — the fan-out actually allocates the lesson's quiz budget
* AC13     — a zero allocation actually skips the LLM call
* AC15/16/17 — `duration_report` is actually written, with the right outcome
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FAKE_LESSON_ID = "50505050-5050-5050-5050-505050505050"


# ── AC8 / AC18 — capacity becomes the target, before any premium spend ───────


def _planner_state(sections: list[dict[str, Any]], tier: str) -> dict[str, Any]:
    return {
        "lesson_id": FAKE_LESSON_ID,
        "tier": tier,
        "sections": sections,
        "segment_summaries": [
            {"segment_id": f"sec_{i}", "summary": f"Summary {i}."} for i in range(len(sections))
        ],
        "progress_pct": 30.0,
        "error": None,
    }


def _mock_supabase() -> MagicMock:
    sb = MagicMock()
    jobs = MagicMock()
    jobs.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": {}
    }
    jobs.update.return_value.eq.return_value.execute.return_value = MagicMock()
    sb.table.return_value = jobs
    return sb


def _plan_llm(graph: Any, n: int, duration_min: float) -> Any:  # noqa: ANN401
    return graph._LessonPlanLLM(
        title="A Lesson",
        subject="Science",
        objectives=["Understand it"],
        complexity_level="medium",
        segments=[
            graph._LessonPlanSegmentLLM(
                segment_id=f"sec_{i}", title=f"Title {i}", duration_min=duration_min
            )
            for i in range(n)
        ],
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_thin_chapter_plans_to_its_capacity_not_the_tier_budget() -> None:
    """AC8/AC18: a chapter that cannot fill T1's 29.25 min must be planned at
    the capacity its own text supports — D-E says run short, never pad.

    Deleting the `narration_budget_min = capacity_min` line makes this fail:
    the prompt would demand 29.25 minutes of a chapter holding ~1,200 chars.
    """
    from app.modules.content.pipeline import graph as g

    # ~1,200 chars total => ~200 source words => ~1.6 min at 127.5 wpm.
    sections = [{"title": f"S{i}", "body": "word " * 120} for i in range(2)]
    provider = AsyncMock()
    provider.complete_structured.return_value = _plan_llm(g, 2, 3.0)

    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=provider),
    ):
        result = await g.lesson_planner_node(_planner_state(sections, "T1"))

    budget = result["lesson_plan"]["duration_budget"]
    assert budget["content_limited"] is True
    assert budget["tier_budget_min"] == pytest.approx(29.25)
    assert budget["narration_target_min"] < 29.25, (
        "a capacity-limited chapter must not be planned against the full tier budget"
    )
    prompt = provider.complete_structured.call_args.args[0][0]["content"]
    assert "29.25 minutes" not in prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rich_chapter_keeps_the_full_tier_budget() -> None:
    """The other side of AC8 — capacity must not quietly shrink a real chapter."""
    from app.modules.content.pipeline import graph as g

    sections = [{"title": f"S{i}", "body": "word " * 6000} for i in range(3)]
    provider = AsyncMock()
    provider.complete_structured.return_value = _plan_llm(g, 3, 8.0)

    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=provider),
    ):
        result = await g.lesson_planner_node(_planner_state(sections, "T2"))

    budget = result["lesson_plan"]["duration_budget"]
    assert budget["content_limited"] is False
    assert budget["narration_target_min"] == pytest.approx(19.5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_chapter_with_no_extractable_text_is_content_limited_not_full_budget() -> None:
    """Zero capacity is the MOST content-limited case, not an exception to it.

    An image-only / failed-OCR chapter previously fell through the `0 <`
    guard and was handed the full tier budget, so it would later be reported
    as `target_missed` — blaming the generator for a lesson the source could
    never have filled.
    """
    from app.modules.content.pipeline import graph as g

    sections = [{"title": "S0", "body": ""}, {"title": "S1", "body": ""}]
    provider = AsyncMock()
    provider.complete_structured.return_value = _plan_llm(g, 2, 4.0)

    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=provider),
    ):
        result = await g.lesson_planner_node(_planner_state(sections, "T2"))

    budget = result["lesson_plan"]["duration_budget"]
    assert budget["content_limited"] is True
    assert budget["capacity_min"] == 0.0
    # Floored for the prompt's sake, never inflated to the tier budget.
    assert 0 < budget["narration_target_min"] < 19.5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_each_planner_batch_is_given_its_own_share_of_the_budget() -> None:
    """The batching-specific hazard, guarded where it actually lives.

    Every batch is issued the SAME system prompt, so passing the whole-lesson
    figure to each would have the reassembled plan sum to budget x batch_count.
    Asserting on the reassembled total cannot catch this — the post-assembly
    rescale normalises it either way — so the only place the bug is visible is
    the per-batch prompt itself.
    """
    from app.modules.content.pipeline import graph as g

    n = 20  # > lesson_planner_batch_size (10) => 2 batches of 10
    sections = [{"title": f"S{i}", "body": "word " * 4000} for i in range(n)]
    prompts: list[str] = []

    def _capture(messages: list[dict[str, str]], *_a: Any, **_k: Any) -> Any:  # noqa: ANN401
        prompts.append(messages[0]["content"])
        ids = [
            line.split("segment_id=")[1].split(":")[0]
            for line in messages[1]["content"].splitlines()
            if "segment_id=" in line
        ]
        return g._LessonPlanLLM(
            title="Full Plan",
            subject="Subject",
            objectives=["Obj"],
            complexity_level="medium",
            segments=[
                g._LessonPlanSegmentLLM(segment_id=sid, title=f"T {sid}", duration_min=3.0)
                for sid in ids
            ],
        )

    provider = AsyncMock()
    provider.complete_structured.side_effect = _capture

    with (
        patch("app.core.db.get_supabase", return_value=_mock_supabase()),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=provider),
    ):
        await g.lesson_planner_node(_planner_state(sections, "T2"))

    assert len(prompts) >= 2, "test is vacuous unless the batched path engaged"
    # T2's 19.5 min split across batches — no single batch may be told the
    # whole-lesson figure, and the shares must add up to it.
    assert not any("19.5 minutes" in p for p in prompts), (
        "a batch was given the whole-lesson budget; the reassembled plan would "
        "sum to budget x batch_count"
    )
    shares = [
        float(p.split("budget of about ")[1].split(" minutes")[0])
        for p in prompts
        if "budget of about " in p
    ]
    assert len(shares) == len(prompts)
    assert sum(shares) == pytest.approx(19.5, abs=0.01)


# ── AC10 / AC11 — the word budget reaches narration, variance is flagged ─────


def _narration_state(duration_min: float | None) -> dict[str, Any]:
    section = {"title": "Osmosis", "body": "Osmosis is water movement. " * 40}
    plan_segment: dict[str, Any] = {
        "segment_id": "sec_0",
        "title": "Osmosis",
        "continuity_notes": "",
    }
    if duration_min is not None:
        plan_segment["duration_min"] = duration_min
    return {
        "lesson_id": FAKE_LESSON_ID,
        "tier": "T2",
        "_section": section,
        "_section_index": 0,
        "_plan_segment": plan_segment,
        "_total_sections": 1,
    }


async def _run_narration(graph: Any, state: dict[str, Any], script: str) -> tuple[Any, list[str]]:  # noqa: ANN401
    prompts: list[str] = []

    async def _capture(messages: list[dict[str, str]], *_a: Any, **_k: Any) -> Any:  # noqa: ANN401
        prompts.append(" ".join(m["content"] for m in messages))
        return graph._NarrationScriptLLM(script=script, narration_style="conversational")

    provider = MagicMock()
    provider.complete_structured = AsyncMock(side_effect=_capture)
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.maybe_single.return_value.execute.return_value.data = {"node_outputs": {}}
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch.object(graph, "_write_phase1_checkpoint", new=AsyncMock(return_value=None)),
        patch.object(graph, "_persist_section_truncation_checkpoint", new=AsyncMock()),
        patch.object(graph, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await graph.narration_generator_node(state)
    return result, prompts


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_prompt_states_the_segment_word_budget() -> None:
    """AC10: the whole point of the story. Before S5-4 this node had NO length
    target, so a 45-min and a 15-min lesson got identical narration."""
    from app.config import get_settings
    from app.modules.content.pipeline import graph as g

    _, prompts = await _run_narration(g, _narration_state(4.0), "word " * 500)

    expected = round(4.0 * g._effective_narration_wpm(get_settings()))
    assert prompts, "narration never called the LLM — test vacuous"
    assert f"about {expected} words" in prompts[0], (
        f"expected a {expected}-word budget in the prompt; got: {prompts[0][:300]}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_word_target_uses_the_pace_adjusted_rate() -> None:
    """AC10: the raw 150 wpm as a generation target overshoots the clock by
    ~18% at the default pace. The target must come from the pace-adjusted rate."""
    from app.config import get_settings
    from app.modules.content.pipeline import graph as g

    settings = get_settings()
    _, prompts = await _run_narration(g, _narration_state(10.0), "word " * 100)

    raw_target = round(10.0 * settings.narration_words_per_minute)
    paced_target = round(10.0 * g._effective_narration_wpm(settings))
    if raw_target != paced_target:
        assert f"about {paced_target} words" in prompts[0]
        assert f"about {raw_target} words" not in prompts[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_in_band_script_records_its_target_and_variance() -> None:
    """AC11: the variance is recorded on the node's own output, not just logged
    — `duration_report` is assembled from these values."""
    from app.config import get_settings
    from app.modules.content.pipeline import graph as g

    target = round(4.0 * g._effective_narration_wpm(get_settings()))
    result, _ = await _run_narration(g, _narration_state(4.0), "word " * target)

    entry = result["narration_scripts"][0]
    assert entry["target_words"] == target
    assert entry["word_variance_pct"] == pytest.approx(0.0, abs=0.5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_out_of_band_script_is_kept_not_trimmed() -> None:
    """AC11/D-D: silent truncation is banned outright. A script far over its
    budget ships in full, flagged — never cut to fit."""
    from app.config import get_settings
    from app.modules.content.pipeline import graph as g

    target = round(2.0 * g._effective_narration_wpm(get_settings()))
    overlong = target * 3
    result, _ = await _run_narration(g, _narration_state(2.0), "word " * overlong)

    entry = result["narration_scripts"][0]
    assert entry["word_count"] == overlong, "the script must be kept whole"
    assert entry["word_variance_pct"] > 15.0, "an over-budget script must be flagged"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_duration_min_degrades_without_a_bogus_budget() -> None:
    """A pre-S5-4 checkpoint resumed across this deploy has no `duration_min`.
    That must produce no length instruction at all, never a target of 0 words."""
    from app.modules.content.pipeline import graph as g

    result, prompts = await _run_narration(g, _narration_state(None), "word " * 200)

    assert "words:" not in prompts[0].split("untrusted")[0] or "about 0 words" not in prompts[0]
    assert "target_words" not in result["narration_scripts"][0]


# ── AC12 / AC13 — the fan-out allocates, and zero actually skips the call ────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_zero_allocation_skips_the_llm_call_entirely() -> None:
    """AC13: a zero-allocation segment must not generate questions that are
    then discarded — the saving is the point, not a side effect."""
    from app.modules.content.pipeline import graph as g

    provider = MagicMock()
    provider.complete_structured = AsyncMock()
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.maybe_single.return_value.execute.return_value.data = {"node_outputs": {}}
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "tier": "T3",
        "_section": {"title": "S0", "body": "Body."},
        "_section_index": 0,
        "_quiz_count": 0,
        "_total_sections": 15,
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.quiz_generator_node(state)

    provider.complete_structured.assert_not_awaited()
    assert result["quiz_questions"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_quiz_count_never_yields_a_quiz_free_lesson() -> None:
    """The pre-S5-4-resume fallback. An earlier version divided the lesson
    total by section count with integer division, so T2 over 15 sections gave
    `10 // 15 == 0` for EVERY section — a lesson shipped with no assessment at
    all, reporting success. The fallback must reproduce the real allocation."""
    from app.config import get_settings
    from app.modules.content.pipeline import graph as g

    sections = [{"title": f"S{i}", "body": "word " * 200} for i in range(15)]
    counts: list[int] = []

    for idx in range(len(sections)):
        provider = MagicMock()
        provider.complete_structured = AsyncMock(return_value=None)
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value
        chain.maybe_single.return_value.execute.return_value.data = {"node_outputs": {}}
        chain.single.return_value.execute.return_value.data = {"node_outputs": {}}
        state = {
            "lesson_id": FAKE_LESSON_ID,
            "tier": "T2",
            "sections": sections,
            "_section": sections[idx],
            "_section_index": idx,
            "_total_sections": 15,
        }
        with (
            patch("app.core.db.get_supabase", return_value=sb),
            patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
            patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
        ):
            await g.quiz_generator_node(state)
        if provider.complete_structured.await_count:
            prompt = provider.complete_structured.await_args.args[0][0]["content"]
            counts.append(int(prompt.split("Write ")[1].split(" to ")[0]))
        else:
            counts.append(0)

    expected = g._quiz_budget_per_segment(
        "T2",
        [float(len(s["body"])) for s in sections],
        get_settings().quiz_seconds_per_question,
    )
    assert sum(counts) == sum(expected) == 10, (
        f"fallback allocated {sum(counts)} questions across 15 sections; T2 budgets 10"
    )


@pytest.mark.unit
def test_oversized_section_cannot_take_the_whole_quiz_budget() -> None:
    """A chapter whose headings fail to split yields one giant section. Weighting
    by raw body length would hand it ~all the questions — generated from only the
    first `section_body_max_chars` of it — and starve every other section to zero."""
    from app.config import get_settings
    from app.modules.content.pipeline import graph as g

    settings = get_settings()
    cap = settings.section_body_max_chars
    oversized_weight = float(min(500_000, cap))
    normal_weight = float(min(3_000, cap))
    weights = [oversized_weight] + [normal_weight for _ in range(14)]
    counts = g._quiz_budget_per_segment("T1", weights, settings.quiz_seconds_per_question)

    assert sum(counts) == 16
    # Bound computed from the LIVE cap (Story 233 re-derived section_body_max_chars
    # upward, so a fixed magic number here would go stale the next time this value
    # is re-tuned) rather than a proportional match — the invariant under test is
    # "capped, not the section's raw uncapped length", not an exact ratio.
    expected_share = oversized_weight / (oversized_weight + 14 * normal_weight)
    max_expected = round(16 * expected_share) + 2
    assert counts[0] <= max_expected, (
        f"the oversized section took {counts[0]} of 16 questions for a "
        f"{expected_share:.0%} weight share (cap={cap}) — weights must be capped "
        "at the text the LLM is actually shown, not the section's raw (uncapped) length"
    )
    assert sum(1 for c in counts if c > 0) >= 8, "most sections must still get questions"


# ── AC15 / AC16 / AC17 — the report is actually written ──────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_package_builder_writes_a_duration_report() -> None:
    """AC15: the duration report is the story's only admin-visible instrument.
    Asserting on the pure classifier proves nothing if the report is never
    written — delete the `duration_report` block and this test fails."""
    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(_base_state())

    written = jobs_table.update.call_args.args[0]["node_outputs"]
    assert "duration_report" in written, (
        "package_builder must persist duration_report alongside "
        "package_builder_degraded / section_truncations"
    )
    report = written["duration_report"]
    for key in (
        "tier",
        "seat_minutes",
        "narration_target_min",
        "measured_narration_min",
        "measured_source",
        "variance_pct",
        "outcome",
        "content_limited",
        "quiz_questions_shipped",
        "qa_phase_seconds",
        "segment_word_variances",
    ):
        assert key in report, f"duration_report is missing {key!r}"
    assert report["outcome"] in {
        "on_target",
        "content_limited",
        "target_missed",
        "unknown",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duration_report_counts_quiz_volume_not_just_narration() -> None:
    """AC15 + D-A: the tier is TOTAL SEAT TIME. A report measuring narration
    alone would read `on_target` for a lesson whose quiz volume had blown the
    budget — the story's own defect class, invisible to its own instrument."""
    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        result = await package_builder_node(_base_state())

    report = jobs_table.update.call_args.args[0]["node_outputs"]["duration_report"]
    shipped = sum(len(s.get("quiz") or []) for s in result["lesson_package"]["segments"])
    assert report["quiz_questions_shipped"] == shipped
    assert report["quiz_budget_questions"] > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partly_synthesised_lesson_is_not_reported_as_a_generator_miss() -> None:
    """AC17: the TTS chain degrades to browser speech rather than failing, so a
    lesson with some segments unsynthesised is ordinary. Counting only the
    measured segments would under-report it and blame the generator
    (`target_missed`) for a TTS outage."""
    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    state = _base_state()
    # `duration_ms` is a sibling of "data" on each audio_assets wrapper (S3-38),
    # written by tts_node from tinytag. Give the first segment a real measured
    # duration and leave the second without one — exactly the shape the
    # browser-speech fallback produces for a segment Sarvam and Azure both
    # declined.
    assets = [dict(a) for a in state["audio_assets"]]
    assets[0] = {**assets[0], "duration_ms": 60_000.0}
    state["audio_assets"] = assets

    sb, jobs_table, _ = _mock_supabase()
    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(state)

    report = jobs_table.update.call_args.args[0]["node_outputs"]["duration_report"]
    assert report["estimated_segments"] >= 1, (
        "the unsynthesised segment must contribute its word-count estimate, not zero"
    )
    assert report["measured_source"] == "partly_measured_audio"
