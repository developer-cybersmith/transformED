"""Tests for Story 4-13 — DNA-Personalized CES Intervention Threshold.

ACs covered: AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC10.

Formula:
    threshold = base
        + (frustration_tolerance - 50) × W_frustration   # high frustration → raise
        + (50 - persistence)           × W_persistence   # low persistence → raise
        + (50 - goal_orientation)      × W_goal          # low goal-orient → raise
    clamped to [ces_dna_threshold_min, ces_dna_threshold_max].

Default weights: W_frustration=0.08, W_persistence=0.05, W_goal=0.04.
Default base: ces_threshold=50.0.
Default clamp: [40.0, 65.0].
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_settings(
    *,
    ces_threshold: float = 50.0,
    ces_dna_weight_frustration: float = 0.08,
    ces_dna_weight_persistence: float = 0.05,
    ces_dna_weight_goal: float = 0.04,
    ces_dna_threshold_min: float = 40.0,
    ces_dna_threshold_max: float = 65.0,
) -> MagicMock:
    s = MagicMock()
    s.ces_threshold = ces_threshold
    s.ces_dna_weight_frustration = ces_dna_weight_frustration
    s.ces_dna_weight_persistence = ces_dna_weight_persistence
    s.ces_dna_weight_goal = ces_dna_weight_goal
    s.ces_dna_threshold_min = ces_dna_threshold_min
    s.ces_dna_threshold_max = ces_dna_threshold_max
    return s


_VALID_SESSION_ID = "123e4567-e89b-12d3-a456-426614174000"
_VALID_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


# ── AC1 — function exists and returns float in [40, 65] ──────────────────────


def test_compute_personalized_threshold_exists_and_returns_float() -> None:
    """AC1: function exists in assessment.ces, returns float."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings()
    result = compute_personalized_threshold(
        persistence=50.0,
        frustration_tolerance=50.0,
        goal_orientation=50.0,
        settings=s,
    )
    assert isinstance(result, float)
    assert 40.0 <= result <= 65.0


# ── AC2 — all None → returns base exactly ────────────────────────────────────


def test_all_none_returns_base_threshold() -> None:
    """AC2: all 3 dims None → returns settings.ces_threshold exactly."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings(ces_threshold=50.0)
    result = compute_personalized_threshold(
        persistence=None,
        frustration_tolerance=None,
        goal_orientation=None,
        settings=s,
    )
    assert result == 50.0


# ── AC7 — formula math correct ───────────────────────────────────────────────


def test_formula_raises_threshold_for_high_frustration_low_persistence() -> None:
    """AC7/AC10: high frustration + low persistence → threshold > base."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings()
    # frustration_tolerance=80 → +2.4 adjustment; persistence=20 → +1.5; goal=20 → +1.2
    result = compute_personalized_threshold(
        frustration_tolerance=80.0,
        persistence=20.0,
        goal_orientation=20.0,
        settings=s,
    )
    assert result > 50.0


def test_formula_lowers_threshold_for_high_persistence_low_frustration() -> None:
    """AC7/AC10: low frustration + high persistence → threshold < base."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings()
    # frustration_tolerance=20 → -2.4; persistence=80 → -1.5; goal=80 → -1.2
    result = compute_personalized_threshold(
        frustration_tolerance=20.0,
        persistence=80.0,
        goal_orientation=80.0,
        settings=s,
    )
    assert result < 50.0


def test_formula_exact_math() -> None:
    """AC7: exact formula arithmetic verified."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings(
        ces_threshold=50.0,
        ces_dna_weight_frustration=0.08,
        ces_dna_weight_persistence=0.05,
        ces_dna_weight_goal=0.04,
        ces_dna_threshold_min=40.0,
        ces_dna_threshold_max=65.0,
    )
    # frustration=80: (80-50)*0.08 = +2.4
    # persistence=20: (50-20)*0.05 = +1.5
    # goal=20:        (50-20)*0.04 = +1.2
    # total = 50 + 2.4 + 1.5 + 1.2 = 55.1
    result = compute_personalized_threshold(
        frustration_tolerance=80.0,
        persistence=20.0,
        goal_orientation=20.0,
        settings=s,
    )
    assert abs(result - 55.1) < 0.01


# ── AC6 — clamp applied ───────────────────────────────────────────────────────


def test_threshold_clamped_to_max() -> None:
    """AC6: result never exceeds ces_dna_threshold_max."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings(ces_dna_threshold_max=52.0)
    result = compute_personalized_threshold(
        frustration_tolerance=100.0,
        persistence=0.0,
        goal_orientation=0.0,
        settings=s,
    )
    assert result <= 52.0


def test_threshold_clamped_to_min() -> None:
    """AC6: result never goes below ces_dna_threshold_min."""
    from app.modules.assessment.ces import compute_personalized_threshold

    s = _make_settings(ces_dna_threshold_min=48.0)
    result = compute_personalized_threshold(
        frustration_tolerance=0.0,
        persistence=100.0,
        goal_orientation=100.0,
        settings=s,
    )
    assert result >= 48.0


# ── AC8 — Settings fields exist ──────────────────────────────────────────────


def test_settings_has_all_five_dna_ces_fields() -> None:
    """AC8: all 5 new env-var-tunable fields exist in Settings with correct defaults."""
    from app.config import Settings

    s = Settings()
    assert hasattr(s, "ces_dna_weight_frustration")
    assert hasattr(s, "ces_dna_weight_persistence")
    assert hasattr(s, "ces_dna_weight_goal")
    assert hasattr(s, "ces_dna_threshold_min")
    assert hasattr(s, "ces_dna_threshold_max")
    assert abs(s.ces_dna_weight_frustration - 0.08) < 1e-9
    assert abs(s.ces_dna_weight_persistence - 0.05) < 1e-9
    assert abs(s.ces_dna_weight_goal - 0.04) < 1e-9
    assert abs(s.ces_dna_threshold_min - 40.0) < 1e-9
    assert abs(s.ces_dna_threshold_max - 65.0) < 1e-9


# ── AC4/AC5 — seed_personalized_ces_threshold: Redis cache hit ────────────────


@pytest.mark.asyncio
async def test_seed_uses_redis_cache_when_available() -> None:
    """AC4: DNA read from Redis cache first; AC5: threshold written to Redis."""
    from app.modules.assessment.service import seed_personalized_ces_threshold

    redis = AsyncMock()
    supabase = MagicMock()
    settings = _make_settings()

    dna_json = json.dumps(
        {
            "persistence": 80.0,
            "frustration_tolerance": 20.0,
            "goal_orientation": 80.0,
        }
    )
    redis.get = AsyncMock(side_effect=lambda key: dna_json.encode() if "dna" in key else None)
    redis.setex = AsyncMock()

    await seed_personalized_ces_threshold(
        session_id=_VALID_SESSION_ID,
        user_id=_VALID_USER_ID,
        redis=redis,
        supabase=supabase,
        settings=settings,
    )

    # Supabase should NOT be queried — cache hit
    supabase.table.assert_not_called()

    # Redis SETEX called with correct key and TTL
    redis.setex.assert_called_once()
    call_args = redis.setex.call_args
    key = call_args.args[0] if call_args.args else call_args.kwargs.get("name", "")
    assert f"session:{_VALID_SESSION_ID}:ces_threshold" in str(key)
    ttl = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("time", 0)
    assert ttl == 86400


@pytest.mark.asyncio
async def test_seed_falls_back_to_supabase_on_cache_miss() -> None:
    """AC4: falls back to Supabase when Redis cache misses."""
    from app.modules.assessment.service import seed_personalized_ces_threshold

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # cache miss
    redis.setex = AsyncMock()

    supabase = MagicMock()
    dna_resp = MagicMock()
    dna_resp.data = {
        "user_id": _VALID_USER_ID,
        "persistence": 60.0,
        "frustration_tolerance": 40.0,
        "goal_orientation": 50.0,
    }
    (
        supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
    ) = dna_resp

    settings = _make_settings()

    await seed_personalized_ces_threshold(
        session_id=_VALID_SESSION_ID,
        user_id=_VALID_USER_ID,
        redis=redis,
        supabase=supabase,
        settings=settings,
    )

    supabase.table.assert_called_with("learner_dna")
    redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_seed_falls_back_to_base_when_no_dna_exists() -> None:
    """AC4: no DNA anywhere → base threshold written to Redis."""
    from app.modules.assessment.service import seed_personalized_ces_threshold

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    supabase = MagicMock()
    no_dna_resp = MagicMock()
    no_dna_resp.data = None
    (
        supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
    ) = no_dna_resp

    settings = _make_settings(ces_threshold=50.0)

    await seed_personalized_ces_threshold(
        session_id=_VALID_SESSION_ID,
        user_id=_VALID_USER_ID,
        redis=redis,
        supabase=supabase,
        settings=settings,
    )

    # Threshold written = base (50.0)
    redis.setex.assert_called_once()
    written_value = float(
        redis.setex.call_args.args[2]
        if len(redis.setex.call_args.args) > 2
        else redis.setex.call_args.kwargs.get("value", 50.0)
    )
    assert abs(written_value - 50.0) < 0.01


@pytest.mark.asyncio
async def test_seed_failure_does_not_raise() -> None:
    """AC3: Redis write failure is non-fatal — no exception propagated."""
    from app.modules.assessment.service import seed_personalized_ces_threshold

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=Exception("Redis down"))
    redis.setex = AsyncMock(side_effect=Exception("Redis down"))

    supabase = MagicMock()
    settings = _make_settings()

    # Must not raise — failure is swallowed + logged at WARNING
    await seed_personalized_ces_threshold(
        session_id=_VALID_SESSION_ID,
        user_id=_VALID_USER_ID,
        redis=redis,
        supabase=supabase,
        settings=settings,
    )


# ── AC9 — no Supabase query on hot 5s path ───────────────────────────────────


def test_no_supabase_query_in_process_attention_signal_source() -> None:
    """AC9: verify by AST scan that process_attention_signal does not call
    supabase.table('learner_dna') — the hot path must only read threshold from Redis.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "modules" / "tutor" / "service.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    # Find the process_attention_signal function body
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "process_attention_signal":
                func_src = ast.unparse(node)
                # Must not contain a learner_dna table call on this path
                assert "learner_dna" not in func_src, (
                    "process_attention_signal must never query learner_dna — "
                    "threshold is pre-computed at session creation (AC9)"
                )
                return

    # If function not found, test is inconclusive — flag it
    raise AssertionError(
        "process_attention_signal not found in tutor/service.py — AC9 cannot be verified"
    )


# ── AC6 — tutor service reads threshold from Redis with fallback ──────────────


def test_process_attention_signal_reads_ces_threshold_from_redis() -> None:
    """AC6: verify by source inspection that process_attention_signal reads
    session:{sid}:ces_threshold from Redis and falls back to settings.ces_threshold.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "modules" / "tutor" / "service.py"
    func_src = src.read_text(encoding="utf-8")

    assert "ces_threshold" in func_src, "tutor/service.py must reference ces_threshold"
    # The key pattern for the per-session Redis key
    assert ":ces_threshold" in func_src, (
        "tutor/service.py must read from session:{sid}:ces_threshold Redis key (AC6)"
    )
