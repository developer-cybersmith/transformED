"""Tests for config.py Settings validators.

Verifies the @model_validator that guards CES weight integrity.
If CES weights don't sum to 1.0, the tutor state machine silently fires
interventions at wrong thresholds for every student session — the highest
blast-radius misconfiguration possible.

All tests are @pytest.mark.unit — no DB, Redis, or network required.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

# ── Shared fixture: required env vars (all fields without defaults) ────────────

_REQUIRED = {
    "SUPABASE_URL": "http://test.supabase.co",
    "SUPABASE_ANON_KEY": "anon",
    "SUPABASE_SERVICE_ROLE_KEY": "service",
    "SUPABASE_JWT_SECRET": "jwt_secret",
    "OPENAI_API_KEY": "sk-test",
    "SARVAM_API_KEY": "sarvam_test",
    "HEYGEN_API_KEY": "heygen_test",
    "LANGFUSE_PUBLIC_KEY": "lf_pub",
    "LANGFUSE_SECRET_KEY": "lf_sec",
}


def _make_settings(monkeypatch, **overrides: str) -> Settings:
    """Create a Settings instance with required env vars set via monkeypatch."""
    for key, val in _REQUIRED.items():
        monkeypatch.setenv(key, val)
    for key, val in overrides.items():
        monkeypatch.setenv(key.upper(), val)
    return Settings()


# ── CES weight validator tests ────────────────────────────────────────────────


@pytest.mark.unit
def test_ces_weights_default_values_sum_to_one(monkeypatch) -> None:
    """PRD §11 defaults (0.35+0.25+0.20+0.12+0.08) must sum to exactly 1.0."""
    s = _make_settings(monkeypatch)
    total = (
        s.ces_weight_quiz
        + s.ces_weight_teachback
        + s.ces_weight_behavioral
        + s.ces_weight_head_pose
        + s.ces_weight_blink
    )
    assert abs(total - 1.0) < 0.001, f"Default CES weights sum to {total:.6f}, expected 1.0"


@pytest.mark.unit
def test_ces_weight_validator_raises_when_quiz_weight_too_high(monkeypatch) -> None:
    """Weights summing to 1.64 (quiz=0.99 + defaults) must be rejected."""
    with pytest.raises(ValidationError, match="CES weights must sum to 1.0"):
        _make_settings(monkeypatch, CES_WEIGHT_QUIZ="0.99")


@pytest.mark.unit
def test_ces_weight_validator_raises_when_all_weights_doubled(monkeypatch) -> None:
    """Doubling all 5 weights (sum=2.0) must be rejected."""
    with pytest.raises(ValidationError, match="CES weights must sum to 1.0"):
        _make_settings(
            monkeypatch,
            CES_WEIGHT_QUIZ="0.70",
            CES_WEIGHT_TEACHBACK="0.50",
            CES_WEIGHT_BEHAVIORAL="0.40",
            CES_WEIGHT_HEAD_POSE="0.24",
            CES_WEIGHT_BLINK="0.16",
        )


@pytest.mark.unit
def test_ces_weight_validator_accepts_custom_weights_that_sum_to_one(monkeypatch) -> None:
    """Operator-tuned weights summing to 1.0 must pass validation."""
    s = _make_settings(
        monkeypatch,
        CES_WEIGHT_QUIZ="0.40",
        CES_WEIGHT_TEACHBACK="0.20",
        CES_WEIGHT_BEHAVIORAL="0.20",
        CES_WEIGHT_HEAD_POSE="0.10",
        CES_WEIGHT_BLINK="0.10",
    )
    total = (
        s.ces_weight_quiz
        + s.ces_weight_teachback
        + s.ces_weight_behavioral
        + s.ces_weight_head_pose
        + s.ces_weight_blink
    )
    assert abs(total - 1.0) < 0.001, f"Custom weights sum to {total:.6f}"


@pytest.mark.unit
def test_ces_weight_validator_tolerates_floating_point_rounding(monkeypatch) -> None:
    """Weights with small floating-point imprecision within 0.001 must pass."""
    s = _make_settings(
        monkeypatch,
        CES_WEIGHT_QUIZ="0.3500",
        CES_WEIGHT_TEACHBACK="0.2500",
        CES_WEIGHT_BEHAVIORAL="0.2000",
        CES_WEIGHT_HEAD_POSE="0.1200",
        CES_WEIGHT_BLINK="0.0800",
    )
    total = (
        s.ces_weight_quiz
        + s.ces_weight_teachback
        + s.ces_weight_behavioral
        + s.ces_weight_head_pose
        + s.ces_weight_blink
    )
    assert abs(total - 1.0) < 0.001


@pytest.mark.unit
def test_llm_mini_default_is_gpt4o_mini(monkeypatch) -> None:
    """llm_mini must default to gpt-4o-mini — all Dev 3 scoring calls use this."""
    s = _make_settings(monkeypatch)
    assert s.llm_mini == "gpt-4o-mini"


@pytest.mark.unit
def test_max_lesson_cost_default_is_three_dollars(monkeypatch) -> None:
    """Cost ceiling must default to $3.00 per PRD §14."""
    s = _make_settings(monkeypatch)
    assert s.max_lesson_cost_usd == 3.00


@pytest.mark.unit
def test_intervention_cooldown_default_is_two_minutes(monkeypatch) -> None:
    """Intervention cooldown must default to 120s (2 min) per PRD §10."""
    s = _make_settings(monkeypatch)
    assert s.intervention_cooldown_seconds == 120
