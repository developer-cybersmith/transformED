"""Story S5-5b / D195 — segment expansion must dispatch the units it plans.

Production lesson d1d6a4e2 (T1, 45 min) planned 7 units and shipped 2. The
node passed `settings.section_body_max_chars` (45,000, raised by Story 233)
to `split_body` as the slice size; split_body returns a body whole when it is
under that, so every topic below 45,000 chars became a single unit.

The S5-5 suites passed throughout: they call split_body directly with
max_chars=6000, and their one node-level test used bodies above 45,000. So
every node test here runs under the REAL `get_settings()` configuration, with
realistic paragraph text rather than "y" * n.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings
from app.modules.content.pipeline.nodes.segment_expansion import (
    CHARS_PER_WORD,
    coverage_per_topic,
    plan_segments,
    split_body,
    split_into,
    unit_slice_chars,
)

# The diagnosed chapter: topic bodies after topic_selection, from production.
DIAGNOSED = [5_677, 28_870]
PRODUCTION_WPM = 150.0  # derived from d1d6a4e2's capacity_min: 34,547 / 6 / 38.39


def _prose(n_chars: int, para: int = 420) -> str:
    """Deterministic text of exactly *n_chars*, in ~420-char paragraphs."""
    paragraphs: list[str] = []
    total = 0
    i = 0
    while total < n_chars:
        words = " ".join(f"w{i}x{j}" for j in range(para // 6))[:para]
        paragraphs.append(words)
        total += len(words) + 2
        i += 1
    return "\n\n".join(paragraphs)[:n_chars]


async def _run_node(
    sizes: list[int], tier: str, *, wpm: float | None = None, settings: Any = None
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Run the real node; return (result, checkpoint, bodies)."""
    from app.modules.content.pipeline import graph as g

    written: dict[str, Any] = {}
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}

    def _capture(payload: dict[str, Any]) -> MagicMock:
        written.update(payload.get("node_outputs", {}))
        return MagicMock(eq=lambda *a: MagicMock(execute=lambda: MagicMock()))

    sb.table.return_value.update.side_effect = _capture

    bodies = [_prose(n) for n in sizes]
    sections = [{"id": f"t{i}", "title": f"Topic {i}", "body": b} for i, b in enumerate(bodies)]

    patches = [
        patch("app.core.db.get_supabase", return_value=sb),
        patch.object(g, "_update_job_progress", new=AsyncMock(return_value=None)),
    ]
    if wpm is not None:
        patches.append(patch.object(g, "_effective_narration_wpm", return_value=wpm))
    if settings is not None:
        patches.append(patch("app.config.get_settings", return_value=settings))
    for p in patches:
        p.start()
    try:
        result = await g.segment_expansion_node(
            {
                "lesson_id": "5b5b5b5b-5b5b-5b5b-5b5b-5b5b5b5b5b5b",
                "tier": tier,
                "sections": sections,
            }
        )
    finally:
        for p in reversed(patches):
            p.stop()
    return result, written.get("segment_expansion", {}), bodies


# ── AC1 / AC9: two sizes, never interchangeable ──────────────────────────────


def test_unit_slice_is_derived_from_the_word_target():
    assert unit_slice_chars(words_per_segment=900, window_chars=45_000) == int(900 * CHARS_PER_WORD)


def test_unit_slice_never_exceeds_the_window():
    assert unit_slice_chars(words_per_segment=100_000, window_chars=45_000) == 45_000


def test_real_config_slice_is_strictly_below_the_phase1_window():
    """AC9 guard. If these two ever coincide, expansion is inert again: every
    topic under the window comes back as one unit."""
    s = get_settings()
    slice_chars = unit_slice_chars(
        words_per_segment=s.narration_words_per_segment, window_chars=s.section_body_max_chars
    )
    assert slice_chars == int(s.narration_words_per_segment * CHARS_PER_WORD)
    assert slice_chars < s.section_body_max_chars, (
        "the unit slice size must be smaller than the Phase-1 window -- D195"
    )


@pytest.mark.asyncio
async def test_checkpoint_records_the_slice_size_and_it_is_not_the_window():
    _, record, _ = await _run_node(DIAGNOSED, "T1", wpm=PRODUCTION_WPM)
    s = get_settings()
    assert record["unit_slice_chars"] == unit_slice_chars(
        words_per_segment=s.narration_words_per_segment, window_chars=s.section_body_max_chars
    )
    assert record["unit_slice_chars"] != s.section_body_max_chars


@pytest.mark.asyncio
async def test_node_derives_the_slice_from_the_configured_word_target():
    """AC1. At the default (900) a hardcoded 5,400 in the node would pass every
    other test; a non-default word target is what tells the two apart."""
    s = get_settings().model_copy(update={"narration_words_per_segment": 600})
    result, record, bodies = await _run_node([200_000], "T1", wpm=PRODUCTION_WPM, settings=s)

    assert record["unit_slice_chars"] == int(600 * CHARS_PER_WORD)
    plan = plan_segments(
        topic_bodies=bodies,
        min_narration_minutes=45.0,
        effective_wpm=PRODUCTION_WPM,
        words_per_segment=600,
        max_segments=s.max_narration_segments,
    )
    assert record["per_topic_segments"] == plan.per_topic_segments
    assert len(result["sections"]) == plan.segment_count
    taught = sum(len(u["body"]) for u in result["sections"])
    assert taught >= plan.segment_count * int(600 * CHARS_PER_WORD)


# ── AC5: THE regression ──────────────────────────────────────────────────────


def test_the_old_call_was_inert_for_a_sub_window_topic():
    """Documents the defect: the window as max_chars returns the topic whole."""
    body = _prose(28_870)
    assert split_body(
        body, target_chars=5_400, max_chars=get_settings().section_body_max_chars
    ) == [body]


@pytest.mark.asyncio
async def test_a_sub_window_topic_larger_than_one_slice_is_split_when_planned():
    s = get_settings()
    size = 20_000
    assert (
        unit_slice_chars(
            words_per_segment=s.narration_words_per_segment, window_chars=s.section_body_max_chars
        )
        < size
        < s.section_body_max_chars
    )

    result, record, _ = await _run_node([size], "T1")

    assert record["per_topic_segments"][0] > 1, "precondition: the planner asked for several"
    assert len(result["sections"]) == record["per_topic_segments"][0]
    assert len(result["sections"]) > 1


# ── AC3: the diagnosed chapter ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diagnosed_chapter_dispatches_seven_units_at_production_wpm():
    result, record, bodies = await _run_node(DIAGNOSED, "T1", wpm=PRODUCTION_WPM)

    assert record["per_topic_segments"] == [2, 5]
    assert len(result["sections"]) == 7
    assert record["segment_count"] == 7
    assert record["untaught_chars_per_topic"] == [0, 0], "content-limited: teach all of it"

    for topic_index, body in enumerate(bodies):
        units = [u["body"] for u in result["sections"] if u["topic_index"] == topic_index]
        assert "".join(units) == body, f"topic {topic_index} was not tiled losslessly"
    window = get_settings().section_body_max_chars
    assert all(len(u["body"]) <= window for u in result["sections"])
    assert all(u["body"].strip() for u in result["sections"])


@pytest.mark.asyncio
async def test_diagnosed_chapter_units_get_distinct_storage_titles():
    """Slices of one topic share a title; without the part suffix their audio
    would overwrite each other in Storage."""
    result, _, _ = await _run_node(DIAGNOSED, "T1", wpm=PRODUCTION_WPM)
    titles = [u["title"] for u in result["sections"]]
    assert len(set(titles)) == len(titles)


# ── AC4: dispatched == planned, under the REAL configuration ─────────────────


@pytest.mark.asyncio
async def test_real_config_diagnosed_chapter_dispatches_exactly_the_plan():
    result, record, _ = await _run_node(DIAGNOSED, "T1")

    assert len(result["sections"]) == sum(record["per_topic_segments"])
    assert record["segment_count"] == sum(record["per_topic_segments"])


@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
@pytest.mark.parametrize(
    "sizes",
    [
        [5_677, 28_870],
        [5_000, 30_000],  # the old mechanism dispatched 6 of 7 here
        [300, 40_000],
        [12_000, 12_000],
        [44_000],
        [3_000],
        [60_000, 90_000],
        [200_000],
    ],
)
@pytest.mark.asyncio
async def test_real_config_sweep_dispatches_exactly_the_plan(sizes, tier):
    result, record, bodies = await _run_node(sizes, tier)

    assert len(result["sections"]) == sum(record["per_topic_segments"]), (
        f"{sizes} {tier}: planned {record['per_topic_segments']}, "
        f"dispatched {len(result['sections'])}"
    )
    # AC6: every usable topic still reaches a unit.
    assert {u["topic_index"] for u in result["sections"]} == set(range(len(bodies)))
    # Nothing exceeds the window; nothing is blank.
    window = get_settings().section_body_max_chars
    assert all(0 < len(u["body"]) <= window for u in result["sections"])
    # AC11: covered + untaught accounts for every character of every topic.
    for topic_index, body in enumerate(bodies):
        taught = sum(len(u["body"]) for u in result["sections"] if u["topic_index"] == topic_index)
        assert taught + record["untaught_chars_per_topic"][topic_index] == len(body)


# ── AC8: content-limited lessons teach everything ────────────────────────────


@pytest.mark.parametrize(
    ("sizes", "wpm"),
    [
        ([5_677, 28_870], 150.0),
        ([5_000, 30_000], 150.0),
        ([2_000, 9_000], 150.0),
        ([2_000, 9_000], 127.5),
        ([15_000], 150.0),
        ([15_000], 127.5),
    ],
)
@pytest.mark.asyncio
async def test_content_limited_lessons_teach_every_character(sizes, wpm):
    """AC8. Each case is asserted content-limited first, so a change to the
    planner cannot turn this into a test that checks nothing."""
    result, record, bodies = await _run_node(sizes, "T1", wpm=wpm)

    assert record["content_limited"] is True, "precondition: this chapter is content-limited"
    assert record["untaught_chars_per_topic"] == [0] * len(sizes)
    for topic_index, body in enumerate(bodies):
        units = [u["body"] for u in result["sections"] if u["topic_index"] == topic_index]
        assert "".join(units) == body


@pytest.mark.parametrize("sizes", [[5_677, 28_870], [5_000, 30_000]])
@pytest.mark.asyncio
async def test_a_plan_that_needs_the_whole_chapter_gets_it(sizes):
    """AC8's boundary: at 127.5 WPM these are NOT content-limited, but the plan
    claims every character. Per-topic prefixes without the coverage hand-off
    strand the small topic's spare allocation and fail here."""
    result, record, _ = await _run_node(sizes, "T1", wpm=127.5)

    assert record["content_limited"] is False, "precondition: the plan claims the full minimum"
    assert record["untaught_chars_per_topic"] == [0] * len(sizes)
    assert sum(len(u["body"]) for u in result["sections"]) == sum(sizes)


# ── AC11: the D194 prefix case is recorded, not silent ───────────────────────


@pytest.mark.asyncio
async def test_a_topic_larger_than_the_duration_needs_records_its_untaught_tail():
    _, record, _ = await _run_node([200_000], "T3", wpm=PRODUCTION_WPM)
    assert record["content_limited"] is False
    assert record["untaught_chars_per_topic"][0] > 0


# ── AC7: cap-overrun behaviour and telemetry unchanged ───────────────────────


def _plan_for(bodies: list[str], tier_minutes: float, settings: Any) -> Any:
    return plan_segments(
        topic_bodies=bodies,
        min_narration_minutes=tier_minutes,
        effective_wpm=PRODUCTION_WPM,
        words_per_segment=settings.narration_words_per_segment,
        max_segments=settings.max_narration_segments,
    )


@pytest.mark.asyncio
async def test_cap_overrun_is_unchanged():
    """Option A: the cap is exceeded only to give every topic one unit."""
    capped = get_settings().model_copy(update={"max_narration_segments": 2})
    result, record, bodies = await _run_node(
        [20_000] * 4, "T1", wpm=PRODUCTION_WPM, settings=capped
    )
    plan = _plan_for(bodies, 45.0, capped)

    assert record["cap_overrun"] == plan.cap_overrun == 2
    assert record["max_segments_configured"] == plan.max_segments_configured == 2
    assert record["capped_by_max_segments"] is plan.capped_by_max_segments is True
    assert record["segment_count"] == 4
    assert len(result["sections"]) == 4
    assert {u["topic_index"] for u in result["sections"]} == {0, 1, 2, 3}


@pytest.mark.asyncio
async def test_a_cap_that_shortens_the_lesson_is_recorded_without_an_overrun():
    """AC7's other half, and review finding 7: a low word target multiplies
    units until max_narration_segments binds. The WINDOW does not bind; the
    cap does, and the record must say so rather than read as a thin chapter."""
    low = get_settings().model_copy(update={"narration_words_per_segment": 100})
    result, record, bodies = await _run_node([60_000], "T1", wpm=PRODUCTION_WPM, settings=low)
    plan = _plan_for(bodies, 45.0, low)

    assert record["capped_by_max_segments"] is plan.capped_by_max_segments is True
    assert record["cap_overrun"] == plan.cap_overrun == 0
    assert len(result["sections"]) == low.max_narration_segments
    assert record["unit_slice_chars"] == 600 < low.section_body_max_chars
    assert record["untaught_chars_per_topic"][0] > 0


# ── AC10: split_into ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("units", [1, 2, 5, 7])
@pytest.mark.parametrize(
    "body",
    [
        _prose(28_870),
        _prose(5_677),
        "x" * 12_345,  # no whitespace at all: hard cuts
        " ".join(["word"] * 3_000),  # no paragraph breaks
    ],
)
def test_split_into_is_lossless_and_exact(body, units):
    pieces = split_into(body, units, max_chars=45_000)
    assert "".join(pieces) == body
    assert len(pieces) == units
    assert all(pieces)


def test_split_into_balances_the_pieces():
    pieces = split_into(_prose(28_870), 5, max_chars=45_000)
    sizes = [len(p) for p in pieces]
    assert max(sizes) - min(sizes) < 28_870 / 5 * 0.5


def test_split_into_cannot_make_more_pieces_than_characters():
    assert split_into("abc", 5, max_chars=45_000) == ["a", "b", "c"]


def test_split_into_empty_body_is_empty():
    assert split_into("", 3, max_chars=45_000) == []


@pytest.mark.parametrize(
    "body",
    [
        "a " + "x" * (2 * 45_000 - 2),  # the only space sits at the very start
        _prose(2 * 45_000, para=4_000),  # ordinary prose, exactly at the bound
        _prose(3 * 45_000 - 7, para=4_000),
    ],
    ids=["sparse-whitespace", "prose-2x-window", "prose-3x-window"],
)
def test_split_into_never_exceeds_the_window_at_the_bound(body):
    """PR #257 review, finding 1. A cut that snapped short used to push its
    shortfall onto the last slice: 89,998 and 45,978 chars against a 45,000
    window. Holds whenever len(body) <= units x max_chars."""
    units = math.ceil(len(body) / 45_000)
    pieces = split_into(body, units, max_chars=45_000)
    assert "".join(pieces) == body
    assert len(pieces) == units
    assert max(len(p) for p in pieces) <= 45_000


# ── PR #257 review, finding 2: whitespace-only topics ───────────────────────


def test_a_whitespace_only_topic_is_allocated_nothing():
    plan = plan_segments(
        topic_bodies=["  \n\n \t ", _prose(20_000)],
        min_narration_minutes=45.0,
        effective_wpm=PRODUCTION_WPM,
        words_per_segment=900,
        max_segments=24,
    )
    assert plan.per_topic_segments[0] == 0
    assert plan.per_topic_segments[1] == plan.segment_count > 0


@pytest.mark.asyncio
async def test_a_whitespace_only_topic_never_becomes_a_blank_unit(monkeypatch):
    import tests.unit.test_s5_5b_slice_size as this

    real_prose = this._prose
    monkeypatch.setattr(
        this, "_prose", lambda n, para=420: " \n\n " * 10 if n == 40 else real_prose(n)
    )
    result, record, _ = await _run_node([40, 20_000], "T1", wpm=PRODUCTION_WPM)

    assert all(u["body"].strip() for u in result["sections"])
    assert {u["topic_index"] for u in result["sections"]} == {1}
    assert record["per_topic_segments"][0] == 0
    assert record["untaught_chars_per_topic"][0] == 0, "whitespace is not untaught text"
    assert len(result["sections"]) == sum(record["per_topic_segments"])


# ── PR #257 review, finding 4: coverage never snaps below the plan ──────────


@pytest.mark.parametrize("para", [420, 4_000])
@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
@pytest.mark.parametrize("wpm", [150.0, 127.5])
@pytest.mark.asyncio
async def test_a_large_topic_is_never_reported_content_limited_by_lesson_planner(
    para, tier, wpm, monkeypatch
):
    """Snapping the covered prefix BACK to a paragraph break left T2 at 150 WPM
    with 26,898 chars against a planned 27,000, and lesson_planner — which
    measures capacity from the dispatched units — flagged a 200,000-char topic
    content_limited at 29.89 min. The capacity maths below is
    lesson_planner_node's own (graph.py, `total_source_chars`)."""
    import tests.unit.test_s5_5b_slice_size as this
    from app.modules.content.pipeline.graph import _narration_capacity_minutes
    from app.schemas.lesson import narration_budget_minutes

    real_prose = this._prose
    monkeypatch.setattr(this, "_prose", lambda n, para_=420: real_prose(n, para=para))
    result, record, _ = await _run_node([200_000], tier, wpm=wpm)

    window = get_settings().section_body_max_chars
    visible = sum(min(len(u["body"]), window) for u in result["sections"])
    capacity = _narration_capacity_minutes(visible, wpm)
    assert record["content_limited"] is False, "precondition: the chapter can fill the tier"
    assert capacity >= narration_budget_minutes(tier), (
        f"{tier} @ {wpm}: dispatched {visible} chars = {capacity:.2f} min, "
        f"below the {narration_budget_minutes(tier)}-min minimum the plan met"
    )
    assert visible >= sum(record["per_topic_segments"]) * record["unit_slice_chars"]


# ── PR #257 review, finding 5: withheld source reaches duration_report ──────


@pytest.mark.parametrize(("untaught", "expected"), [([173_102], True), ([0, 0], False)])
@pytest.mark.asyncio
async def test_duration_report_says_when_segment_expansion_withheld_source(untaught, expected):
    """A max_narration_segments clamp reads as content_limited, because
    capacity_min is measured from the dispatched units. Without this flag the
    admin sees a 'thin chapter' while the checkpoint records 173k untaught."""
    from app.modules.content.pipeline.graph import package_builder_node
    from tests.unit.test_package_builder_node import _base_state, _mock_supabase

    sb, jobs_table, _ = _mock_supabase(
        node_outputs={"segment_expansion": {"untaught_chars_per_topic": untaught}}
    )
    state = {**_base_state(), "section_truncations": []}
    with patch("app.core.db.get_supabase", return_value=sb):
        await package_builder_node(state)

    report = jobs_table.update.call_args.args[0]["node_outputs"]["duration_report"]
    assert report["source_was_truncated"] is expected


# ── The hard invariants, swept ───────────────────────────────────────────────


@pytest.mark.parametrize("words_per_segment", [600, 900, 2_000])
@pytest.mark.parametrize("para", [420, 4_000])
@pytest.mark.parametrize("wpm", [150.0, 127.5])
@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
@pytest.mark.parametrize("sizes", [[5_677, 28_870], [300, 40_000], [60_000, 90_000], [200_000]])
@pytest.mark.asyncio
async def test_expansion_invariants_hold_across_the_sweep(
    sizes, tier, wpm, para, words_per_segment, monkeypatch
):
    """What the design guarantees. A unit may exceed `unit_slice_chars`, and so
    may one topic's coverage: the diagnosed chapter teaches 28,870 chars in the
    5 units planned for it, and AC3/AC8 require that. The window is the per-unit
    ceiling, and the LESSON's coverage is what the plan counted on."""
    import tests.unit.test_s5_5b_slice_size as this
    from app.modules.content.pipeline.graph import _narration_capacity_minutes
    from app.schemas.lesson import narration_budget_minutes

    real_prose = this._prose
    monkeypatch.setattr(this, "_prose", lambda n, para_=420: real_prose(n, para=para))
    s = get_settings().model_copy(update={"narration_words_per_segment": words_per_segment})
    result, record, bodies = await _run_node(sizes, tier, wpm=wpm, settings=s)

    window = s.section_body_max_chars
    unit_chars = record["unit_slice_chars"]
    units = record["per_topic_segments"]
    planned = min(sum(sizes), sum(units) * unit_chars)
    taught_by_topic = [
        sum(len(u["body"]) for u in result["sections"] if u["topic_index"] == i)
        for i in range(len(sizes))
    ]
    coverage = coverage_per_topic(sizes, units, unit_chars=unit_chars, window_chars=window)

    assert len(result["sections"]) == sum(units)
    assert all(0 < len(u["body"]) <= window for u in result["sections"])
    for i, taught in enumerate(taught_by_topic):
        assert taught <= units[i] * window
        # Forward snapping only ever ADDS, by at most one slack-fraction.
        assert coverage[i] <= taught <= coverage[i] + max(1, int(coverage[i] * 0.25))
    assert sum(taught_by_topic) >= planned, "coverage fell below what the plan counted on"
    visible = sum(min(len(u["body"]), window) for u in result["sections"])
    planner_capacity = _narration_capacity_minutes(visible, wpm)
    if not record["content_limited"]:
        assert planner_capacity >= narration_budget_minutes(tier)
    else:
        assert (
            record["untaught_chars_per_topic"] == [0] * len(sizes)
            or record["capped_by_max_segments"]
        )


# ── coverage_per_topic ───────────────────────────────────────────────────────


def test_coverage_hands_a_short_topics_spare_allocation_to_the_long_one():
    """At 127.5 WPM the diagnosed chapter needs nearly all its source. The
    small topic cannot use its second slice; that coverage must move."""
    cover = coverage_per_topic(DIAGNOSED, [2, 5], unit_chars=5_400, window_chars=45_000)
    assert cover == DIAGNOSED


def test_coverage_is_bounded_by_what_the_units_are_sized_for():
    cover = coverage_per_topic([200_000], [3], unit_chars=5_400, window_chars=45_000)
    assert cover == [3 * 5_400]


def test_coverage_never_exceeds_units_times_window():
    cover = coverage_per_topic([500_000], [2], unit_chars=500_000, window_chars=45_000)
    assert cover == [90_000]


def test_coverage_for_a_topic_with_no_units_is_zero():
    assert coverage_per_topic([10_000, 10_000], [0, 2], unit_chars=5_400, window_chars=45_000) == [
        0,
        10_000,
    ]


def test_plan_for_the_diagnosed_chapter_is_unchanged():
    plan = plan_segments(
        topic_bodies=[_prose(n) for n in DIAGNOSED],
        min_narration_minutes=45.0,
        effective_wpm=PRODUCTION_WPM,
        words_per_segment=900,
        max_segments=24,
    )
    assert plan.per_topic_segments == [2, 5]
