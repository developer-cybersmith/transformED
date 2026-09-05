"""Tests for Story F2-3 — Learner Mode tier label / minute mapping verification.

All 8 tests must be RED before implementation and GREEN after.
"""

from app.modules.assessment.service import _TIER_LABELS, _TIER_MINUTES


class TestTierMinutesConstant:
    def test_tier_minutes_values(self):
        assert _TIER_MINUTES == {"T1": 45, "T2": 30, "T3": 15}

    def test_tier_minutes_keys_match_labels(self):
        assert set(_TIER_MINUTES.keys()) == set(_TIER_LABELS.keys())

    def test_tier_ordering_t1_longest(self):
        assert _TIER_MINUTES["T1"] > _TIER_MINUTES["T2"] > _TIER_MINUTES["T3"]

    def test_tier_minutes_values_are_int_not_float(self):
        # AC8 — _TIER_MINUTES must use int, not float (guard test would catch floats repo-wide,
        # but this explicitly pins the type for this constant per the story's own AC)
        assert all(isinstance(v, int) for v in _TIER_MINUTES.values())


class TestConfigDescriptions:
    def test_config_t1_description_no_beginner(self):
        from app.config import Settings

        field = Settings.model_fields["learner_tier_t1_qa_seconds"]
        desc = field.description or ""
        assert "beginner" not in desc.lower(), "T1 must not say 'beginner'"
        assert "Full-Depth" in desc
        assert "45" in desc

    def test_config_t2_description_no_intermediate(self):
        from app.config import Settings

        field = Settings.model_fields["learner_tier_t2_qa_seconds"]
        desc = field.description or ""
        assert "intermediate" not in desc.lower(), "T2 must not say 'intermediate'"
        assert "Standard" in desc
        assert "30" in desc

    def test_config_t3_description_no_advanced(self):
        from app.config import Settings

        field = Settings.model_fields["learner_tier_t3_qa_seconds"]
        desc = field.description or ""
        assert "advanced" not in desc.lower(), "T3 must not say 'advanced'"
        assert "Refresher" in desc
        assert "15" in desc

    def test_qa_seconds_ordering(self):
        from app.config import Settings

        s = Settings()
        assert (
            s.learner_tier_t1_qa_seconds
            > s.learner_tier_t2_qa_seconds
            > s.learner_tier_t3_qa_seconds
        )


class TestSessionReportContract:
    def test_session_report_no_tier_minutes_field(self):
        from app.modules.assessment.router import SessionReport

        assert "tier_minutes" not in SessionReport.model_fields, (
            "tier_minutes must NOT be added to SessionReport — confirmed internal-only per F2-3"
        )
