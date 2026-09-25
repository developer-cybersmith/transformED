"""Story S5-5, Option A — content preservation outranks the fan-out cap.

`max_narration_segments` is a SAFETY BOUND, not a hard ceiling. When more
usable topics exist than the cap allows, the cap is exceeded by exactly
`len(usable) - cap` so that every topic with content still reaches a
dispatched unit.

Before this, the surplus topics were allocated zero units. Because slices are
cut from ONE topic's body, a topic allocated zero has its text taught nowhere,
and the node skipped it with a bare `continue` that logged nothing — silent
content loss, in the story whose entire purpose is removing that class.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.content.pipeline.nodes.segment_expansion import plan_segments


def _paragraphs(n: int, words_each: int = 60) -> str:
    out = []
    for i in range(n):
        w = words_each + (i % 7) * 5
        out.append(f"Paragraph {i}. " + " ".join(f"word{j}" for j in range(w)) + ".")
    return "\n\n".join(out)


def _plan(bodies: list[str], *, minutes: float = 45.0, cap: int = 60):
    return plan_segments(
        topic_bodies=bodies,
        min_narration_minutes=minutes,
        effective_wpm=150.0,
        words_per_segment=900,
        max_segments=cap,
    )


# ── (1) usable_topics > max_segments ─────────────────────────────────────────


def test_usable_topics_greater_than_cap_keeps_every_topic():
    plan = _plan([_paragraphs(400)] * 4, cap=2)

    assert plan.segment_count == 4
    assert all(n >= 1 for n in plan.per_topic_segments)
    assert plan.cap_overrun == 2


# ── (3) the overrun amount is recorded ───────────────────────────────────────


@pytest.mark.parametrize(
    ("topics", "cap", "expected_overrun"),
    [(4, 2, 2), (2, 1, 1), (3, 3, 0), (2, 60, 0)],
)
def test_cap_overrun_amount_is_recorded(topics, cap, expected_overrun):
    plan = _plan([_paragraphs(400)] * topics, cap=cap)

    assert plan.cap_overrun == expected_overrun
    assert plan.max_segments_configured == max(1, cap)


def test_overrun_is_never_more_than_the_minimum_needed():
    """The cap is exceeded to preserve topics and for no other reason — never
    rounded up to whatever the duration wanted."""
    plan = _plan([_paragraphs(4000)] * 3, cap=1)  # duration alone wants 8

    assert plan.segment_count == 3, "one per topic, not the 8 the duration wanted"
    assert plan.cap_overrun == 2


# ── (8) capped and overrun are orthogonal ────────────────────────────────────


def test_capped_by_max_segments_now_means_the_cap_shortened_the_lesson():
    """Independent of whether the cap was exceeded. The previous code conflated
    the two and reported capped=True while simultaneously exceeding the cap,
    which reads as nonsense in the record."""
    shortened = _plan([_paragraphs(4000)] * 2, cap=3)
    assert shortened.capped_by_max_segments is True
    assert shortened.cap_overrun == 0

    both = _plan([_paragraphs(4000)] * 4, cap=2)
    assert both.capped_by_max_segments is True
    assert both.cap_overrun == 2

    neither = _plan([_paragraphs(4000)] * 2, cap=60)
    assert neither.capped_by_max_segments is False
    assert neither.cap_overrun == 0


# ── (4) empty topics still skipped ───────────────────────────────────────────


def test_empty_topics_are_skipped_and_do_not_count_as_usable():
    """Preservation applies to topics with CONTENT. An empty body has nothing
    to teach and must not consume a unit — nor force an overrun."""
    plan = _plan(["", _paragraphs(400), "", _paragraphs(400)], cap=2)

    assert plan.per_topic_segments[0] == 0
    assert plan.per_topic_segments[2] == 0
    assert plan.per_topic_segments[1] >= 1
    assert plan.per_topic_segments[3] >= 1
    assert plan.cap_overrun == 0, "2 usable topics against cap 2 needs no overrun"


# ── (5) tiny topic beside a very large one ───────────────────────────────────


def test_tiny_topic_beside_a_very_large_one_keeps_its_unit():
    plan = _plan([_paragraphs(1), _paragraphs(4000)])

    assert plan.per_topic_segments[0] >= 1
    assert plan.per_topic_segments[1] > plan.per_topic_segments[0]


# ── (6) content-limited short chapter ────────────────────────────────────────


def test_content_limited_short_chapter_still_covers_every_topic():
    """A chapter too thin for the tier runs short — but not by erasing a topic."""
    plan = _plan([_paragraphs(3), _paragraphs(2)])

    assert plan.content_limited is True
    assert all(n >= 1 for n in plan.per_topic_segments)
    assert plan.cap_overrun == 0


# ── (7) the normal case is unchanged ─────────────────────────────────────────


def test_normal_case_is_unchanged():
    """The change must fire ONLY where a topic would otherwise be dropped."""
    plan = _plan([_paragraphs(4000)] * 2, cap=24)

    assert plan.segment_count == 8
    assert plan.per_topic_segments == [4, 4]
    assert plan.cap_overrun == 0
    assert plan.capped_by_max_segments is False


# ── (2) THE invariant, end to end at the node ────────────────────────────────


@pytest.mark.asyncio
async def test_every_usable_topic_reaches_a_dispatched_unit():
    """The invariant this whole review question was about: the set of
    topic_index values in the dispatched units must equal the set of topics
    that had content. Nothing asserted this before.
    """
    from app.modules.content.pipeline import graph as g

    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    sections = [
        {"id": "s0", "title": "Empty", "body": ""},
        {"id": "s1", "title": "Big", "body": _paragraphs(400)},
        {"id": "s2", "title": "Tiny", "body": _paragraphs(2)},
        {"id": "s3", "title": "Also empty", "body": ""},
        {"id": "s4", "title": "Medium", "body": _paragraphs(60)},
    ]
    expected = {i for i, s in enumerate(sections) if s["body"]}

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch.object(g, "_update_job_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.segment_expansion_node(
            {
                "lesson_id": "80808080-8080-8080-8080-808080808080",
                "tier": "T1",
                "sections": sections,
            }
        )

    represented = {s["topic_index"] for s in result["sections"]}
    assert represented == expected, (
        f"topics {sorted(expected - represented)} had content but reached no dispatched "
        "unit — their text would be taught nowhere"
    )
    assert all(s["body"].strip() for s in result["sections"]), "no blank unit may ship"


@pytest.mark.asyncio
async def test_node_records_the_overrun_in_its_checkpoint():
    """The overrun must be visible in `lesson_jobs.node_outputs`, not inferable
    only by recomputing the allocation."""
    from app.modules.content.pipeline import graph as g

    written: dict = {}

    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}

    def _capture(payload):
        written.update(payload.get("node_outputs", {}))
        return MagicMock(eq=lambda *a: MagicMock(execute=lambda: MagicMock()))

    sb.table.return_value.update.side_effect = _capture

    sections = [{"id": f"s{i}", "title": f"T{i}", "body": _paragraphs(400)} for i in range(4)]

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch.object(g, "_update_job_progress", new=AsyncMock(return_value=None)),
    ):
        await g.segment_expansion_node(
            {
                "lesson_id": "90909090-9090-9090-9090-909090909090",
                "tier": "T1",
                "sections": sections,
            }
        )

    record = written.get("segment_expansion", {})
    assert "cap_overrun" in record, "the overrun must be recorded, not inferred"
    assert "max_segments_configured" in record
