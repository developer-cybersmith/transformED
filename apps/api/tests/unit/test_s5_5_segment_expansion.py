"""Story S5-5 — segment expansion makes the narration minimum reachable.

`topic_selection` collapses a chapter to 1-2 topics; each Phase-1 call reads at
most `section_body_max_chars` of one. So before this story the ceiling was
`n_topics x 6,000` chars — 13.3 min (T1/T2), 6.7 min (T3) — regardless of how
long the chapter was. Every tier was structurally short of its minimum.

The window is not too small: 900 narration words is 5,400 chars, inside it.
These tests pin the real fix — reading it once per delivery unit instead of once
per topic — and, above all, that slicing never loses a character.
"""

from __future__ import annotations

import pytest

from app.schemas.lesson import TIER_MIN_NARRATION_MINUTES

# The real diagnosed chapter (lesson be32c289-d22e-4f11-afc0-44d529adb48c):
# 26,209 chars -> ~4,368 source words -> ~29.1 min at 150 wpm.
DIAGNOSED_CHAPTER_CHARS = 26_209
DIAGNOSED_SOURCE_WORDS = 4_368
DIAGNOSED_MAX_MINUTES = 29.1


def _paragraphs(n: int, words_each: int = 60) -> str:
    """Realistic multi-paragraph prose — blank-line separated, varying lengths,
    so paragraph-boundary slicing is exercised rather than a uniform string."""
    out = []
    for i in range(n):
        w = words_each + (i % 7) * 5
        out.append(f"Paragraph {i}. " + " ".join(f"word{j}" for j in range(w)) + ".")
    return "\n\n".join(out)


# ── AC8 / AC16 — nothing is lost ─────────────────────────────────────────────


class TestTextPreservation:
    def test_concatenated_slices_reproduce_the_topic_body_exactly(self):
        """AC8/AC16: the whole point. A slicer that drops a character is the
        same defect class as the truncation it replaces, just harder to see."""
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = _paragraphs(40)
        slices = split_body(body, target_chars=5_400, max_chars=6_000)

        assert "".join(slices) == body, "slicing must be byte-for-byte lossless"

    @pytest.mark.parametrize("n_paragraphs", [1, 2, 3, 17, 200])
    def test_preservation_holds_across_topic_sizes(self, n_paragraphs):
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = _paragraphs(n_paragraphs)
        assert "".join(split_body(body, target_chars=5_400, max_chars=6_000)) == body

    def test_preservation_holds_for_one_giant_paragraph(self):
        """No paragraph boundary to cut on — the fallback path must still be
        lossless, not merely best-effort."""
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = " ".join(f"word{i}" for i in range(20_000))  # ~150k chars, no "\n\n"
        slices = split_body(body, target_chars=5_400, max_chars=6_000)

        assert "".join(slices) == body
        assert all(len(s) <= 6_000 for s in slices)

    def test_preservation_holds_for_a_body_with_no_whitespace_at_all(self):
        """Pathological extraction output (a scanned table, a base64 blob): no
        paragraph AND no space to cut on. Must hard-cut, still losslessly."""
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = "x" * 20_000
        slices = split_body(body, target_chars=5_400, max_chars=6_000)

        assert "".join(slices) == body
        assert all(len(s) <= 6_000 for s in slices)


# ── AC9 / AC10 — paragraph boundaries, and the window ────────────────────────


class TestSliceShape:
    def test_slices_prefer_paragraph_boundaries(self):
        """AC9: a slice should end at a paragraph break when one is available,
        so a narration segment does not begin mid-sentence."""
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = _paragraphs(40)
        slices = split_body(body, target_chars=5_400, max_chars=6_000)

        assert len(slices) > 1, "test is vacuous unless the body actually split"
        # Every slice but the last should end on a paragraph separator.
        ends_clean = sum(1 for s in slices[:-1] if s.endswith("\n\n"))
        assert ends_clean == len(slices) - 1, (
            f"only {ends_clean} of {len(slices) - 1} slices ended at a paragraph break"
        )

    @pytest.mark.parametrize("size", [500, 6_000, 6_001, 26_209, 500_000])
    def test_no_slice_ever_exceeds_the_window(self, size):
        """AC10/AC19: the 6,000-char window is NOT raised by this story — slices
        are sized so it is sufficient."""
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = _paragraphs(max(1, size // 400))[:size] or "x"
        slices = split_body(body, target_chars=5_400, max_chars=6_000)

        assert slices, "must always produce at least one slice"
        assert all(len(s) <= 6_000 for s in slices), (
            f"largest slice {max(len(s) for s in slices)} exceeds the 6,000 window"
        )

    def test_a_body_already_inside_the_window_is_not_split(self):
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        body = _paragraphs(3)
        assert len(body) < 6_000
        assert split_body(body, target_chars=5_400, max_chars=6_000) == [body]

    def test_empty_body_yields_no_slices_rather_than_a_blank_one(self):
        from app.modules.content.pipeline.nodes.segment_expansion import split_body

        assert split_body("", target_chars=5_400, max_chars=6_000) == []


# ── AC1-AC4, AC17 — the 15 / 30 / 45 plan ────────────────────────────────────


class TestDurationPlanning:
    @pytest.mark.parametrize(("tier", "minutes"), [("T3", 15), ("T2", 30), ("T1", 45)])
    def test_enough_slices_are_planned_to_meet_the_minimum(self, tier, minutes):
        """AC1-AC3/AC17: with ample source, the planned slices x per-slice word
        target must MEET OR EXCEED the tier minimum. A floor, not a target."""
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        wpm = 150.0
        ample = _paragraphs(2_000)  # far more than any tier needs
        plan = plan_segments(
            topic_bodies=[ample],
            min_narration_minutes=float(minutes),
            effective_wpm=wpm,
            words_per_segment=900,
            max_segments=60,
        )

        assert plan.segment_count * 900 >= minutes * wpm, (
            f"{tier}: {plan.segment_count} slices x 900 words cannot fill {minutes} min"
        )
        assert plan.content_limited is False

    def test_tier_minimums_come_from_the_shared_table(self):
        """AC4: not retyped here — a second copy is how 45 becomes 29.25 again."""
        assert TIER_MIN_NARRATION_MINUTES == {"T1": 45, "T2": 30, "T3": 15}

    def test_effective_wpm_changes_the_plan(self):
        """AC4: the plan must be computed at the SAME rate the audio is measured
        against. A slower provider needs fewer words for the same minutes."""
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        ample = _paragraphs(2_000)
        fast = plan_segments(
            topic_bodies=[ample],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        slow = plan_segments(
            topic_bodies=[ample],
            min_narration_minutes=45.0,
            effective_wpm=127.5,
            words_per_segment=900,
            max_segments=60,
        )
        assert slow.segment_count < fast.segment_count


# ── AC5 / AC6 / AC18 — the real content-limited case ─────────────────────────


class TestContentLimited:
    def test_the_diagnosed_chapter_is_content_limited_at_about_29_minutes(self):
        """AC18: the exact lesson this story came from. A T1/45 request over
        26,209 chars must be reported as ~29 min and content-limited — never as
        a satisfied 45."""
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        body = "x" * DIAGNOSED_CHAPTER_CHARS
        plan = plan_segments(
            topic_bodies=[body],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )

        assert plan.content_limited is True
        assert plan.achievable_minutes == pytest.approx(DIAGNOSED_MAX_MINUTES, abs=0.5)
        assert plan.requested_min_minutes == 45.0
        assert plan.achievable_minutes < 45.0

    def test_the_same_chapter_satisfies_the_15_minute_tier(self):
        """The counter-case: content_limited must not fire when the chapter is
        genuinely sufficient, or the signal is worthless."""
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        plan = plan_segments(
            topic_bodies=["x" * DIAGNOSED_CHAPTER_CHARS],
            min_narration_minutes=15.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        assert plan.content_limited is False

    def test_a_short_chapter_is_never_padded_to_hit_the_clock(self):
        """AC5: the plan must ask for LESS, not fabricate more. Slice count is
        capped by available content."""
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        thin = _paragraphs(2)  # a few hundred words
        plan = plan_segments(
            topic_bodies=[thin],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        assert plan.content_limited is True
        assert plan.segment_count * 900 <= len(thin) / 6.0 + 900, (
            "planned words must not exceed what the source can support"
        )


# ── AC11 / AC15 — allocation and bounds ──────────────────────────────────────


class TestAllocationAndBounds:
    def test_slices_are_allocated_across_topics_by_body_length(self):
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        big, small = _paragraphs(400), _paragraphs(40)
        plan = plan_segments(
            topic_bodies=[big, small],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        assert plan.per_topic_segments[0] > plan.per_topic_segments[1]

    def test_every_topic_gets_at_least_one_slice(self):
        """AC11: a short second topic must not be erased by proportional
        allocation — topic_selection chose it deliberately."""
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        plan = plan_segments(
            topic_bodies=[_paragraphs(500), _paragraphs(1)],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        assert all(n >= 1 for n in plan.per_topic_segments)

    def test_slice_count_is_bounded_by_max_segments(self):
        """AC15/Scale Q2: when the MINIMUM needs more slices than the cap
        allows, the cap binds and the result says so rather than fanning out.

        Note what does NOT trigger this: a huge topic. The slice count is
        driven by the duration minimum, not by available text — 45 min needs 8
        slices whether the topic holds 50,000 chars or 500,000. The cap is a
        fan-out backstop, not a content limit.
        """
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        plan = plan_segments(
            topic_bodies=["x" * 500_000],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=5,
        )
        assert plan.segment_count <= 5
        assert plan.capped_by_max_segments is True
        assert plan.content_limited is True, (
            "a capped lesson is shorter than requested and must say so"
        )

    def test_a_huge_topic_is_not_capped_merely_for_being_huge(self):
        """The counter-case. 500,000 chars could fill 92 slices, but 45 minutes
        only needs 8 — and satisfying the minimum is the contract. The unread
        remainder is a SELECTION question (which content to teach), owned by
        topic_selection, not a loss caused by this node.

        Known limitation, recorded rather than hidden: slices tile from the
        START of each topic body, so a topic far larger than the duration needs
        is taught from its prefix. See the story's Out-of-scope note.
        """
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        plan = plan_segments(
            topic_bodies=["x" * 500_000],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        assert plan.capped_by_max_segments is False
        assert plan.content_limited is False
        assert plan.segment_count == 8

    def test_zero_topics_degrades_rather_than_raising(self):
        from app.modules.content.pipeline.nodes.segment_expansion import plan_segments

        plan = plan_segments(
            topic_bodies=[],
            min_narration_minutes=45.0,
            effective_wpm=150.0,
            words_per_segment=900,
            max_segments=60,
        )
        assert plan.segment_count == 0


# ── AC12 / AC13 — the node is wired, and downstream still works ──────────────


class TestNodeWiring:
    def test_segment_expansion_is_in_the_compiled_graph(self):
        """A correct slicer that is never called is the inert-`structure_node`
        precedent this repo has already paid for once (binding rule 5)."""
        from app.modules.content.pipeline.graph import _build_pipeline_graph

        compiled = _build_pipeline_graph()
        nodes = set(compiled.get_graph().nodes)
        assert "segment_expansion" in nodes
        assert "topic_selection" in nodes

    @pytest.mark.asyncio
    async def test_node_expands_topics_into_multiple_units(self):
        """AC12: the node must actually lengthen `sections`, and every unit must
        stay inside the unchanged 6,000-char window."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.modules.content.pipeline import graph as g

        body = _paragraphs(400)  # far more than one window
        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value
        chain.single.return_value.execute.return_value.data = {"node_outputs": {}}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        state = {
            "lesson_id": "60606060-6060-6060-6060-606060606060",
            "tier": "T1",
            "sections": [{"id": "s0", "title": "Topic One", "body": body}],
        }
        with (
            patch("app.core.db.get_supabase", return_value=sb),
            patch.object(g, "_update_job_progress", new=AsyncMock(return_value=None)),
        ):
            result = await g.segment_expansion_node(state)

        out = result["sections"]
        assert len(out) > 1, "a 45-min T1 lesson needs more than one delivery unit"
        assert all(len(s["body"]) <= 6_000 for s in out)
        assert all(s["topic_index"] == 0 for s in out)

    @pytest.mark.asyncio
    async def test_slices_of_one_topic_get_unique_storage_safe_ids(self):
        """AC13: slices share a topic title, and `_derive_section_id` builds the
        audio Storage path from the title — identical ids would have one slice's
        MP3 overwrite another's."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.modules.content.pipeline import graph as g

        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value
        chain.single.return_value.execute.return_value.data = {"node_outputs": {}}
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        state = {
            "lesson_id": "60606060-6060-6060-6060-606060606060",
            "tier": "T1",
            "sections": [{"id": "s0", "title": "Topic One", "body": _paragraphs(400)}],
        }
        with (
            patch("app.core.db.get_supabase", return_value=sb),
            patch.object(g, "_update_job_progress", new=AsyncMock(return_value=None)),
        ):
            result = await g.segment_expansion_node(state)

        ids = [g._derive_section_id(s, i) for i, s in enumerate(result["sections"])]
        assert len(set(ids)) == len(ids), f"duplicate section ids would collide in Storage: {ids}"
