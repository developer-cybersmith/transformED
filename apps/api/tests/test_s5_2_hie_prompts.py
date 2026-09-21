"""Tests for S5-2: HIE lecture-format system prompts.

Verifies that _TIER_PROMPT_FRAMING contains full HIE specs for all three tiers,
that T2 is no longer missing, and that _TIER_MINUTES_PER_SLIDE_BAND is
re-derived to align with HIE's fixed slide counts (7 for T3, 10 for T1/T2).
"""

from __future__ import annotations

import pytest

from app.modules.content.pipeline.graph import (
    _TIER_MINUTES_PER_SLIDE_BAND,
    _TIER_PROMPT_FRAMING,
    _tier_slide_budget_per_segment,
)


class TestTierPromptFramingT2:
    """T2 previously had no key — AC2 requires it exist and be non-empty."""

    def test_t2_key_exists(self) -> None:
        assert "T2" in _TIER_PROMPT_FRAMING

    def test_t2_non_empty(self) -> None:
        assert len(_TIER_PROMPT_FRAMING["T2"].strip()) > 0

    def test_t2_mentions_ten_slides(self) -> None:
        assert "10" in _TIER_PROMPT_FRAMING["T2"]

    def test_t2_mentions_thirty_minutes(self) -> None:
        framing = _TIER_PROMPT_FRAMING["T2"]
        assert "30" in framing or "thirty" in framing.lower()


class TestTierPromptFramingT1:
    """T1 must contain the HIE Master Session Structure with binding timings."""

    def test_t1_mentions_ten_slides(self) -> None:
        assert "10" in _TIER_PROMPT_FRAMING["T1"]

    def test_t1_mentions_forty_five_minutes(self) -> None:
        framing = _TIER_PROMPT_FRAMING["T1"]
        assert "45" in framing

    def test_t1_contains_binding_timings(self) -> None:
        framing = _TIER_PROMPT_FRAMING["T1"]
        # The binding timings total must be present — "45:00" or the sum notation
        assert "45:00" in framing or ("3:00" in framing and "7:00" in framing)

    def test_t1_contains_split_screen(self) -> None:
        assert "Split-Screen" in _TIER_PROMPT_FRAMING["T1"] or "split-screen" in _TIER_PROMPT_FRAMING["T1"].lower()


class TestTierPromptFramingT3:
    """T3 must contain the HIE Compressed First-Teach Protocol with 7 slides."""

    def test_t3_mentions_seven_slides(self) -> None:
        assert "7" in _TIER_PROMPT_FRAMING["T3"]

    def test_t3_mentions_fifteen_minutes(self) -> None:
        framing = _TIER_PROMPT_FRAMING["T3"]
        assert "15" in framing or "fifteen" in framing.lower()

    def test_t3_contains_split_screen(self) -> None:
        assert "Split-Screen" in _TIER_PROMPT_FRAMING["T3"] or "split-screen" in _TIER_PROMPT_FRAMING["T3"].lower()


class TestTierMinutesPerSlideBand:
    """AC4: _TIER_MINUTES_PER_SLIDE_BAND updated to align with HIE slide counts."""

    def test_t1_band_values(self) -> None:
        assert _TIER_MINUTES_PER_SLIDE_BAND["T1"] == (4.0, 5.0)

    def test_t2_band_values(self) -> None:
        assert _TIER_MINUTES_PER_SLIDE_BAND["T2"] == (2.8, 3.5)

    def test_t3_band_values(self) -> None:
        assert _TIER_MINUTES_PER_SLIDE_BAND["T3"] == (2.0, 2.5)

    def test_t1_45min_produces_approx_ten_slides(self) -> None:
        """A 45-min T1 lesson should budget ~9-12 total slides (HIE target: 10)."""
        # 10 equal segments of 4.5 min each → 45 min total
        segment_durations = [4.5] * 10
        budgets = _tier_slide_budget_per_segment("T1", segment_durations)
        total_min = sum(lo for lo, _ in budgets)
        total_max = sum(hi for _, hi in budgets)
        assert total_min >= 9, f"Expected total_min >= 9, got {total_min}"
        assert total_max <= 15, f"Expected total_max <= 15, got {total_max}"

    def test_t2_30min_produces_approx_ten_slides(self) -> None:
        """A 30-min T2 lesson should budget ~8-12 total slides (HIE target: 10)."""
        segment_durations = [3.0] * 10
        budgets = _tier_slide_budget_per_segment("T2", segment_durations)
        total_min = sum(lo for lo, _ in budgets)
        total_max = sum(hi for _, hi in budgets)
        assert total_min >= 8, f"Expected total_min >= 8, got {total_min}"
        assert total_max <= 14, f"Expected total_max <= 14, got {total_max}"

    def test_t3_15min_produces_approx_seven_slides(self) -> None:
        """A 15-min T3 lesson should budget slides such that HIE target (7) is achievable.

        5 equal segments of 3 min (total 15 min): each segment floors to 1 slide
        (floor=1 structural minimum) → total_min=5, total_max=10.  The HIE target
        of 7 must fall within [total_min, total_max], not necessarily equal total_min.
        """
        segment_durations = [3.0] * 5  # 5 segments of 3 min = 15 min
        budgets = _tier_slide_budget_per_segment("T3", segment_durations)
        total_min = sum(lo for lo, _ in budgets)
        total_max = sum(hi for _, hi in budgets)
        hie_target = 7
        assert total_min <= hie_target <= total_max, (
            f"HIE target {hie_target} slides not achievable in range [{total_min}, {total_max}]"
        )

    def test_45_divided_by_max_gives_at_least_nine(self) -> None:
        """Direct arithmetic verification: 45 / 5.0 >= 9."""
        t1_min_per_slide, t1_max_per_slide = _TIER_MINUTES_PER_SLIDE_BAND["T1"]
        total_min_slides = 45.0 / t1_max_per_slide
        assert total_min_slides >= 9.0
