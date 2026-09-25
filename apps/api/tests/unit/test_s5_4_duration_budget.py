"""Story S5-4 — duration-driven lessons (enforced 15/30/45 min seat time).

RED before implementation, GREEN after. Covers the pure/arithmetic ACs and the
planner-prompt shape. The node-level wiring ACs are covered where the behaviour
already has a home: test_fan_out_state_keys.py (budget threading through the
real fan-out), test_lesson_planner_node.py (rescale + slide budgets),
test_quiz_generator_tier.py (allocation + zero-allocation skip) and
tests/integration/test_tier_differentiation_and_cost.py (lesson totals end to
end).

Everything here asserts an observable value (a constant, a returned budget, a
prompt string), never a conversation with a mock — binding rule 2 of
docs/DEFECT-REGISTER.md.
"""

from __future__ import annotations

import math

import pytest

from app.schemas.lesson import (
    TIER_MIN_NARRATION_MINUTES,
    TIER_QA_SECONDS,
    TIER_QUIZ_SECONDS,
    TIER_SEAT_MINUTES,
    narration_budget_minutes,
    qa_budget_seconds,
    quiz_budget_seconds,
)

# ── AC1 / AC2 — one source of truth for duration ─────────────────────────────


class TestSeatTimeConstants:
    def test_seat_minutes_are_the_locked_durations(self):
        assert TIER_SEAT_MINUTES == {"T1": 45, "T2": 30, "T3": 15}

    def test_seat_minutes_are_int_not_float(self):
        # Mirrors test_f2_3_tier_label_verify's identical pin on _TIER_MINUTES,
        # which is now an alias of this map (AC3).
        assert all(isinstance(v, int) for v in TIER_SEAT_MINUTES.values())

    def test_tier_minutes_are_the_narration_minimum(self):
        # Product decision 2026-09-25: 15/30/45 are the minimum minutes of
        # spoken NARRATION, not total seat time and not a 65% share of it.
        # The first draft of this story read them as seat time and targeted
        # 29.25 min for a lesson sold as 45 — the headline number was never
        # the number being enforced.
        assert TIER_MIN_NARRATION_MINUTES == {"T1": 45, "T2": 30, "T3": 15}
        assert TIER_SEAT_MINUTES is TIER_MIN_NARRATION_MINUTES

    def test_quiz_and_qa_are_additive_not_carved_out(self):
        # Under the old share table these were fractions of the tier minutes.
        # They are now stated directly and sit ON TOP of the narration
        # minimum, so a T1 session is ~45 min narration + ~7 min quiz + 4.5
        # min Q&A. Values deliberately unchanged from the seat-time draft:
        # the quiz recalibration they came from fixed a real defect and is
        # independent of this semantics change.
        assert TIER_QUIZ_SECONDS == {"T1": 405, "T2": 270, "T3": 135}
        assert TIER_QA_SECONDS == {"T1": 270, "T2": 180, "T3": 90}

    def test_no_share_table_survives(self):
        # A leftover SEAT_TIME_SHARES would mean two live readings of the same
        # enum — exactly the drift this story exists to remove.
        import app.schemas.lesson as lesson_mod

        assert not hasattr(lesson_mod, "SEAT_TIME_SHARES")


class TestDerivedBudgets:
    @pytest.mark.parametrize(
        ("tier", "expected"),
        [("T1", 45.0), ("T2", 30.0), ("T3", 15.0)],
    )
    def test_narration_budget_minutes_is_the_tier_minimum(self, tier, expected):
        assert math.isclose(narration_budget_minutes(tier), expected, abs_tol=1e-9)

    @pytest.mark.parametrize(
        ("tier", "expected"),
        [("T1", 405.0), ("T2", 270.0), ("T3", 135.0)],
    )
    def test_quiz_budget_seconds(self, tier, expected):
        assert math.isclose(quiz_budget_seconds(tier), expected, abs_tol=1e-9)

    @pytest.mark.parametrize(
        ("tier", "expected"),
        [("T1", 270), ("T2", 180), ("T3", 90)],
    )
    def test_qa_budget_seconds(self, tier, expected):
        assert qa_budget_seconds(tier) == expected

    def test_qa_budget_seconds_returns_int(self):
        # It feeds config defaults typed `int` — a float would fail validation
        # at import time on every worker boot.
        assert all(isinstance(qa_budget_seconds(t), int) for t in TIER_SEAT_MINUTES)

    def test_unknown_tier_falls_back_to_default_not_raises(self):
        # Same soft-fallback convention as _tier_slide_budget_per_segment: a
        # budget hint must never be the thing that crashes a paid-for lesson.
        assert narration_budget_minutes("nonsense") == narration_budget_minutes("T2")
        assert quiz_budget_seconds(None) == quiz_budget_seconds("T2")
        assert qa_budget_seconds("") == qa_budget_seconds("T2")

    def test_narration_minimum_is_the_whole_tier_figure(self):
        # The arithmetic is only honest if the number a student is shown IS the
        # number the pipeline enforces. Under the old share table a "45 minute"
        # lesson targeted 29.25; now it targets 45.
        for tier, minutes in TIER_MIN_NARRATION_MINUTES.items():
            assert narration_budget_minutes(tier) == float(minutes), tier


# ── AC3 / AC4 / AC5 — consumers point at the shared map ──────────────────────


class TestConsumersUseSharedSource:
    def test_assessment_tier_minutes_is_the_shared_map(self):
        from app.modules.assessment.service import _TIER_MINUTES

        # AC3: an alias, not a second literal. Identity, not equality — an
        # equal-but-separate dict is exactly the drift this AC exists to stop.
        assert _TIER_MINUTES is TIER_SEAT_MINUTES

    @pytest.mark.parametrize(
        ("field_name", "expected"),
        [
            ("learner_tier_t1_qa_seconds", 270),
            ("learner_tier_t2_qa_seconds", 180),
            ("learner_tier_t3_qa_seconds", 90),
        ],
    )
    def test_qa_seconds_defaults_are_seat_time_derived(self, field_name, expected):
        from app.config import Settings

        assert Settings.model_fields[field_name].default == expected

    def test_default_qa_seconds_matches_t2(self):
        from app.config import Settings

        assert Settings.model_fields[
            "learner_tier_default_qa_seconds"
        ].default == qa_budget_seconds("T2")

    def test_quiz_seconds_per_question_setting_exists(self):
        from app.config import Settings

        field = Settings.model_fields["quiz_seconds_per_question"]
        assert field.default == 25

    def test_qa_phase_seconds_docstring_drops_the_ability_reading(self):
        # AC5: the docstring documented "T1 (beginner) ... T3 (advanced)" — a
        # third, unrelated reading of the same enum. Under S5-4 the enum means
        # duration and nothing else.
        from app.modules.tutor.service import qa_phase_seconds

        doc = (qa_phase_seconds.__doc__ or "").lower()
        assert doc, "qa_phase_seconds must keep a docstring"
        for banned in ("beginner", "intermediate", "advanced"):
            assert banned not in doc, f"{banned!r} is the pre-S5-4 ability reading"

    def test_qa_phase_seconds_returns_the_new_defaults(self):
        from app.modules.tutor.service import qa_phase_seconds

        assert qa_phase_seconds("T1") == 270
        assert qa_phase_seconds("T2") == 180
        assert qa_phase_seconds("T3") == 90
        assert qa_phase_seconds(None) == 180


# ── AC6 — planner prompt is anchored, depth framing is gone ──────────────────


class TestPlannerPromptAnchor:
    def test_depth_framing_dict_is_removed(self):
        # AC6/D-G: deleted, not left unreferenced — a dangling constant is how
        # the next contributor reintroduces depth semantics.
        from app.modules.content.pipeline import graph

        assert not hasattr(graph, "_TIER_PROMPT_FRAMING")

    def test_prompt_states_the_narration_budget(self):
        from app.modules.content.pipeline.graph import _planner_system_prompt

        # S5-1 (#231) made this return (prompt, was_book_context_truncated).
        prompt, _ = _planner_system_prompt(narration_budget_min=19.5)
        assert "19.5" in prompt
        assert "duration_min" in prompt

    def test_prompt_no_longer_carries_depth_wording(self):
        from app.modules.content.pipeline.graph import _planner_system_prompt

        prompt, _ = _planner_system_prompt(narration_budget_min=29.25)
        prompt = prompt.upper()
        assert "FULL-DEPTH" not in prompt
        assert "CRITICAL-TOPICS-ONLY" not in prompt

    def test_chapter_context_still_reaches_the_prompt(self):
        # S5-3 shipped chapter context into this prompt; S5-4 must not drop it
        # while rewriting the signature.
        from app.modules.content.pipeline.graph import _planner_system_prompt

        prompt, _ = _planner_system_prompt(
            narration_budget_min=19.5, chapter_context="[Chapter Instructions]\nfocus on osmosis"
        )
        assert "osmosis" in prompt


# ── AC10 — effective narration rate ──────────────────────────────────────────


class TestEffectiveNarrationRate:
    def test_effective_wpm_applies_the_tts_pace(self):
        from app.config import get_settings
        from app.modules.content.pipeline.graph import _effective_narration_wpm

        settings = get_settings()
        # The pace comes from whichever tier is configured PRIMARY. Story 232
        # put 60db ahead of Sarvam at speed 1.0, so pinning this to Sarvam's
        # 0.85 would silently mis-budget every 60db deployment by ~18%.
        primary_pace = (
            settings.sixtydb_speed
            if (settings.sixtydb_api_key and settings.sixtydb_voice_id)
            else settings.sarvam_narration_pace
        )
        expected = settings.narration_words_per_minute * primary_pace
        assert math.isclose(_effective_narration_wpm(settings), expected, abs_tol=1e-9)

    def test_effective_wpm_follows_the_primary_tier_not_a_hardcoded_vendor(self):
        """A deployment with 60db credentials narrates at 60db's speed; one
        without falls through to Sarvam and must use Sarvam's pace."""
        from types import SimpleNamespace

        from app.modules.content.pipeline.graph import _effective_narration_wpm

        with_60db = SimpleNamespace(
            narration_words_per_minute=150,
            sarvam_narration_pace=0.85,
            sixtydb_api_key="k",
            sixtydb_voice_id="v",
            sixtydb_speed=1.0,
        )
        without_60db = SimpleNamespace(
            narration_words_per_minute=150,
            sarvam_narration_pace=0.85,
            sixtydb_api_key=None,
            sixtydb_voice_id=None,
            sixtydb_speed=1.0,
        )
        assert _effective_narration_wpm(with_60db) == 150.0
        assert _effective_narration_wpm(without_60db) == pytest.approx(127.5)

    def test_effective_wpm_is_not_the_raw_rate(self):
        # The whole point: using the raw 150 as a generation target overshoots
        # the clock by ~18% at the default pace of 0.85.
        from app.config import get_settings
        from app.modules.content.pipeline.graph import _effective_narration_wpm

        settings = get_settings()
        if settings.sarvam_narration_pace != 1.0:
            assert _effective_narration_wpm(settings) != settings.narration_words_per_minute


# ── AC7 — planner durations are rescaled onto the budget ─────────────────────


class TestRescaleSegmentDurations:
    def test_sum_within_tolerance_is_left_alone(self):
        from app.modules.content.pipeline.graph import _rescale_segment_durations

        durations = [10.0, 10.0]
        rescaled, factor = _rescale_segment_durations(durations, target_min=19.5)
        assert factor == 1.0
        assert rescaled == durations

    def test_overshoot_is_scaled_down_onto_the_target(self):
        from app.modules.content.pipeline.graph import _rescale_segment_durations

        rescaled, factor = _rescale_segment_durations([30.0, 30.0], target_min=19.5)
        assert math.isclose(sum(rescaled), 19.5, abs_tol=1e-9)
        assert math.isclose(factor, 19.5 / 60.0, abs_tol=1e-9)

    def test_undershoot_is_scaled_up_onto_the_target(self):
        from app.modules.content.pipeline.graph import _rescale_segment_durations

        rescaled, factor = _rescale_segment_durations([2.0, 3.0], target_min=29.25)
        assert math.isclose(sum(rescaled), 29.25, abs_tol=1e-9)
        assert factor > 1.0

    def test_relative_shares_are_preserved(self):
        # Slide budgets are already derived from these numbers — rescaling must
        # not silently re-weight the lesson.
        from app.modules.content.pipeline.graph import _rescale_segment_durations

        rescaled, _ = _rescale_segment_durations([1.0, 3.0], target_min=19.5)
        assert math.isclose(rescaled[1] / rescaled[0], 3.0, abs_tol=1e-9)

    def test_degenerate_input_is_not_divided_by_zero(self):
        from app.modules.content.pipeline.graph import _rescale_segment_durations

        rescaled, factor = _rescale_segment_durations([], target_min=19.5)
        assert rescaled == []
        assert factor == 1.0

        rescaled, factor = _rescale_segment_durations([0.0, 0.0], target_min=19.5)
        assert factor == 1.0
        assert rescaled == [0.0, 0.0]


# ── AC12 / AC13 — quiz volume is a lesson-level budget ───────────────────────


class TestQuizBudgetAllocation:
    @pytest.mark.parametrize(("tier", "expected_total"), [("T1", 16), ("T2", 10), ("T3", 5)])
    def test_lesson_total_matches_the_locked_table(self, tier, expected_total):
        from app.modules.content.pipeline.graph import _quiz_budget_per_segment

        counts = _quiz_budget_per_segment(tier, [5.0, 5.0, 5.0], seconds_per_question=25)
        assert sum(counts) == expected_total

    def test_total_does_not_scale_with_segment_count(self):
        # The defect this AC exists to kill: the old per-segment band multiplied
        # by segment count, so a 15-segment T1 chapter produced 45-75 questions.
        from app.modules.content.pipeline.graph import _quiz_budget_per_segment

        few = _quiz_budget_per_segment("T1", [10.0, 10.0], seconds_per_question=25)
        many = _quiz_budget_per_segment("T1", [2.0] * 15, seconds_per_question=25)
        assert sum(few) == sum(many) == 16

    def test_allocation_is_proportional_to_duration(self):
        from app.modules.content.pipeline.graph import _quiz_budget_per_segment

        counts = _quiz_budget_per_segment("T1", [1.0, 3.0], seconds_per_question=25)
        assert sum(counts) == 16
        assert counts[1] > counts[0]

    def test_zero_allocation_when_budget_is_smaller_than_segment_count(self):
        # AC13: T3 buys 5 questions; a 15-segment chapter cannot give every
        # segment one. Some segments legitimately get zero.
        from app.modules.content.pipeline.graph import _quiz_budget_per_segment

        counts = _quiz_budget_per_segment("T3", [1.0] * 15, seconds_per_question=25)
        assert sum(counts) == 5
        assert counts.count(0) == 10

    def test_never_negative_and_one_entry_per_segment(self):
        from app.modules.content.pipeline.graph import _quiz_budget_per_segment

        durations = [0.5, 12.0, 3.0, 0.1]
        counts = _quiz_budget_per_segment("T2", durations, seconds_per_question=25)
        assert len(counts) == len(durations)
        assert all(c >= 0 for c in counts)

    def test_degenerate_durations_do_not_crash(self):
        from app.modules.content.pipeline.graph import _quiz_budget_per_segment

        assert _quiz_budget_per_segment("T2", [], seconds_per_question=25) == []
        counts = _quiz_budget_per_segment("T2", [0.0, 0.0], seconds_per_question=25)
        assert len(counts) == 2
        assert sum(counts) <= 10


# ── AC8 / AC18 — content capacity, measured before spending ──────────────────


class TestContentCapacity:
    def test_capacity_scales_with_available_source_text(self):
        from app.modules.content.pipeline.graph import _narration_capacity_minutes

        small = _narration_capacity_minutes(total_source_chars=6_000, effective_wpm=127.5)
        large = _narration_capacity_minutes(total_source_chars=60_000, effective_wpm=127.5)
        assert large > small > 0

    def test_empty_source_has_zero_capacity(self):
        from app.modules.content.pipeline.graph import _narration_capacity_minutes

        assert _narration_capacity_minutes(total_source_chars=0, effective_wpm=127.5) == 0.0

    def test_a_thin_chapter_cannot_fill_a_t1_budget(self):
        # The short-chapter case D-E covers: run shorter, never pad.
        from app.modules.content.pipeline.graph import _narration_capacity_minutes

        capacity = _narration_capacity_minutes(total_source_chars=4_000, effective_wpm=127.5)
        assert capacity < narration_budget_minutes("T1")


# ── AC16 — two kinds of miss, not one flag ───────────────────────────────────


class TestDurationOutcome:
    def test_on_target_within_tolerance(self):
        from app.modules.content.pipeline.graph import _classify_duration_outcome

        assert (
            _classify_duration_outcome(target_min=30.0, measured_min=31.0, content_limited=False)
            == "on_target"
        )

    def test_content_limited_wins_over_target_missed(self):
        # A thin chapter that runs short is expected behaviour, not a generator
        # defect — conflating them is what makes the admin signal useless.
        from app.modules.content.pipeline.graph import _classify_duration_outcome

        assert (
            _classify_duration_outcome(target_min=29.25, measured_min=8.0, content_limited=True)
            == "content_limited"
        )

    def test_target_missed_on_adequate_content(self):
        from app.modules.content.pipeline.graph import _classify_duration_outcome

        assert (
            _classify_duration_outcome(target_min=29.25, measured_min=8.0, content_limited=False)
            == "target_missed"
        )

    def test_overshoot_is_also_a_miss(self):
        from app.modules.content.pipeline.graph import _classify_duration_outcome

        assert (
            _classify_duration_outcome(target_min=15.0, measured_min=40.0, content_limited=False)
            == "target_missed"
        )

    def test_tolerance_boundary_is_inclusive(self):
        from app.modules.content.pipeline.graph import _classify_duration_outcome

        # +/-15% exactly is still on target; a hair beyond is not.
        assert (
            _classify_duration_outcome(target_min=100.0, measured_min=115.0, content_limited=False)
            == "on_target"
        )
        assert (
            _classify_duration_outcome(target_min=100.0, measured_min=115.5, content_limited=False)
            == "target_missed"
        )

    def test_unknown_measurement_is_not_reported_as_on_target(self):
        from app.modules.content.pipeline.graph import _classify_duration_outcome

        assert (
            _classify_duration_outcome(target_min=30.0, measured_min=None, content_limited=False)
            == "unknown"
        )
