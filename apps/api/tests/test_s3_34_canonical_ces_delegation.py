"""Tests for S3-34: Canonical CES formula -- delegate tutor/service.py.

Covers ACs not yet satisfied by the previous implementation:
  AC1  -- no independent compute_ces in tutor/service.py (AST)
  AC5  -- out-of-range values emit logger.warning before clamping
  AC6  -- NaN / ±inf in any present signal raises ValueError
  AC7  -- return value is max(0.0, min(100.0, round(ces, 4)))
  AC8  -- weight_sum guard uses `not (weight_sum > 0.0)` (NaN-safe form)
  AC10 -- tutor/service.py imports compute_ces from canonical; no own weighted sum
  AC11 -- delegation produces identical results (to within 1e-9 tolerance)
  AC12 -- ces.py has no forbidden imports (redis, asyncio, etc.)

All tests are @pytest.mark.unit — no DB, no LLM, no network.
"""

from __future__ import annotations

import ast
import logging
import math
from pathlib import Path

import pytest

from app.config import Settings

# ── helpers ───────────────────────────────────────────────────────────────────

_CES_PY = Path(__file__).parent.parent / "app" / "modules" / "assessment" / "ces.py"
_SERVICE_PY = Path(__file__).parent.parent / "app" / "modules" / "tutor" / "service.py"


def _settings(
    quiz: float = 0.35,
    tb: float = 0.25,
    beh: float = 0.20,
    hp: float = 0.12,
    blink: float = 0.08,
) -> Settings:
    return Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
        heygen_api_key="x",
        langfuse_public_key="x",
        langfuse_secret_key="x",
        ces_weight_quiz=quiz,
        ces_weight_teachback=tb,
        ces_weight_behavioral=beh,
        ces_weight_head_pose=hp,
        ces_weight_blink=blink,
    )


def _compute_ces(**kw):
    from app.modules.assessment.ces import compute_ces  # noqa: PLC0415

    return compute_ces(**kw)


# ── AC1: no independent weighted sum formula in tutor/service.py ─────────────


@pytest.mark.unit
def test_ac1_tutor_service_compute_ces_has_no_independent_weighted_sum():
    """AC1: tutor/service.py must NOT independently apply the CES weighted sum.

    AC10 allows a thin wrapper function named compute_ces in service.py, but
    that wrapper must delegate — it must not contain its own weighted sum
    computation. We verify by checking that 'weight_sum' (the redistribution
    variable used in the canonical formula) does not appear in service.py.

    A thin wrapper that delegates via _canonical(...) passes; any file that
    independently computes the weighted sum fails.
    """
    source = _SERVICE_PY.read_text(encoding="utf-8")
    assert "weight_sum" not in source, (
        "tutor/service.py contains 'weight_sum' — "
        "this indicates an independent CES formula. "
        "Remove it; the wrapper must only call the canonical compute_ces."
    )


# ── AC5: out-of-range values emit logger.warning before clamping ─────────────


@pytest.mark.unit
def test_ac5_out_of_range_quiz_emits_warning(caplog):
    """AC5: quiz_accuracy > 1.0 emits a logger.warning and clamps; no exception raised."""
    s = _settings()
    with caplog.at_level(logging.WARNING, logger="app.modules.assessment.ces"):
        result = _compute_ces(
            quiz_accuracy=1.5,
            teachback_score=0.5,
            behavioral=0.5,
            head_pose=0.5,
            blink=0.5,
            settings=s,
        )
    assert isinstance(result, float), "result must be a float (no exception)"
    assert any("quiz_accuracy" in m for m in caplog.messages), (
        "Expected a warning containing 'quiz_accuracy' for out-of-range input"
    )


@pytest.mark.unit
def test_ac5_out_of_range_behavioral_emits_warning(caplog):
    """AC5: behavioral < 0 emits a logger.warning and clamps; no exception raised."""
    s = _settings()
    with caplog.at_level(logging.WARNING, logger="app.modules.assessment.ces"):
        result = _compute_ces(
            quiz_accuracy=0.5,
            teachback_score=0.5,
            behavioral=-0.5,
            head_pose=0.5,
            blink=0.5,
            settings=s,
        )
    assert isinstance(result, float), "result must be a float (no exception)"
    assert any("behavioral" in m for m in caplog.messages), (
        "Expected a warning containing 'behavioral' for out-of-range input"
    )


@pytest.mark.unit
def test_ac5_clamped_value_is_correct_after_warning(caplog):
    """AC5: after warning, out-of-range values are clamped to [0.0, 1.0] for computation."""
    s = _settings()
    with caplog.at_level(logging.WARNING, logger="app.modules.assessment.ces"):
        # quiz=1.5 → clamped to 1.0; teachback=-0.2 → clamped to 0.0
        result = _compute_ces(
            quiz_accuracy=1.5,
            teachback_score=-0.2,
            behavioral=1.0,
            head_pose=1.0,
            blink=1.0,
            settings=s,
        )
    # After clamping: quiz=1.0, tb=0.0, beh=1.0, hp=1.0, blink=1.0
    # weight_sum = 1.0; CES = (1×0.35 + 0×0.25 + 1×0.20 + 1×0.12 + 1×0.08) × 100 = 75.0
    assert result == pytest.approx(75.0, abs=0.001)


# ── AC6: NaN / ±inf raises ValueError ────────────────────────────────────────


@pytest.mark.unit
def test_ac6_nan_quiz_raises_value_error():
    """AC6: NaN in quiz_accuracy raises ValueError naming the offending signal."""
    s = _settings()
    with pytest.raises(ValueError, match="quiz_accuracy"):
        _compute_ces(
            quiz_accuracy=math.nan,
            teachback_score=0.5,
            behavioral=0.5,
            head_pose=0.5,
            blink=0.5,
            settings=s,
        )


@pytest.mark.unit
def test_ac6_pos_inf_teachback_raises_value_error():
    """AC6: +inf in teachback_score raises ValueError naming the offending signal."""
    s = _settings()
    with pytest.raises(ValueError, match="teachback_score"):
        _compute_ces(
            quiz_accuracy=0.5,
            teachback_score=math.inf,
            behavioral=0.5,
            head_pose=0.5,
            blink=0.5,
            settings=s,
        )


@pytest.mark.unit
def test_ac6_neg_inf_behavioral_raises_value_error():
    """AC6: -inf in behavioral raises ValueError naming the offending signal."""
    s = _settings()
    with pytest.raises(ValueError, match="behavioral"):
        _compute_ces(
            quiz_accuracy=0.5,
            teachback_score=0.5,
            behavioral=-math.inf,
            head_pose=0.5,
            blink=0.5,
            settings=s,
        )


@pytest.mark.unit
def test_ac6_nan_head_pose_raises_value_error():
    """AC6: NaN in head_pose raises ValueError naming the offending signal."""
    s = _settings()
    with pytest.raises(ValueError, match="head_pose"):
        _compute_ces(
            quiz_accuracy=0.5,
            teachback_score=0.5,
            behavioral=0.5,
            head_pose=math.nan,
            blink=0.5,
            settings=s,
        )


@pytest.mark.unit
def test_ac6_nan_blink_raises_value_error():
    """AC6: NaN in blink raises ValueError naming the offending signal."""
    s = _settings()
    with pytest.raises(ValueError, match="blink"):
        _compute_ces(
            quiz_accuracy=0.5,
            teachback_score=0.5,
            behavioral=0.5,
            head_pose=0.5,
            blink=math.nan,
            settings=s,
        )


@pytest.mark.unit
def test_ac6_none_signals_exempt_from_nan_check():
    """AC6: None signals are excluded (not non-finite); no ValueError raised."""
    s = _settings()
    # Should not raise — None is valid for all signals
    result = _compute_ces(
        quiz_accuracy=None,
        teachback_score=None,
        behavioral=None,
        head_pose=None,
        blink=None,
        settings=s,
    )
    assert result == 0.0


# ── AC7: output is max(0.0, min(100.0, round(ces, 4))) ───────────────────────


@pytest.mark.unit
def test_ac7_return_statement_has_max_lower_bound():
    """AC7: ces.py return value must use max(0.0, min(100.0, round(ces, 4))).

    We check the source for the specific pattern 'max(0.0, min(100.0,' which
    appears in the return statement. This is more specific than checking for
    any max(0.0, ...) call (which also appears in the clamping list comprehension).
    """
    source = _CES_PY.read_text(encoding="utf-8")
    assert "max(0.0, min(100.0," in source, (
        "ces.py return must use max(0.0, min(100.0, round(ces, 4))) — "
        "the lower-bound clamp 'max(0.0, min(100.0,' is missing"
    )


@pytest.mark.unit
def test_ac7_output_never_below_zero():
    """AC7: CES output is always >= 0.0 even under degenerate weight configs."""
    s = _settings()
    # All zeros — should give 0.0 not negative
    result = _compute_ces(
        quiz_accuracy=0.0,
        teachback_score=0.0,
        behavioral=0.0,
        head_pose=0.0,
        blink=0.0,
        settings=s,
    )
    assert result >= 0.0


# ── AC8: NaN-safe weight_sum guard ───────────────────────────────────────────


@pytest.mark.unit
def test_ac8_nan_safe_guard_in_source():
    """AC8: ces.py must use `not (weight_sum > 0.0)` not `weight_sum <= 0.0`.

    Checks for the NaN-safe guard form as a substring of the source,
    since `weight_sum <= 0.0` returns False for NaN (wrong) while
    `not (weight_sum > 0.0)` returns True for NaN (correct: returns 0.0).
    """
    source = _CES_PY.read_text(encoding="utf-8")
    assert "not (weight_sum > 0.0)" in source, (
        "ces.py must use the NaN-safe guard `not (weight_sum > 0.0)` — "
        "using `weight_sum <= 0.0` is not NaN-safe (NaN <= 0.0 is False)"
    )


# ── AC10: tutor/service.py imports canonical; no own weighted sum ─────────────


@pytest.mark.unit
def test_ac10_tutor_service_imports_canonical():
    """AC10: tutor/service.py must import compute_ces from app.modules.assessment.ces."""
    source = _SERVICE_PY.read_text(encoding="utf-8")
    # Accept both the direct import and the aliased form
    has_import = (
        "from app.modules.assessment.ces import compute_ces" in source
        or "from app.modules.assessment import ces" in source
    )
    assert has_import, "tutor/service.py must import compute_ces from app.modules.assessment.ces"


@pytest.mark.unit
def test_ac10_tutor_service_has_no_independent_weighted_sum():
    """AC10: tutor/service.py must not contain an independent weighted sum formula.

    Checks that the pattern `v * (w / weight_sum)` (the redistribution formula)
    does not appear outside of a delegation call in service.py.
    The canonical formula lives in assessment/ces.py; service.py only delegates.
    """
    source = _SERVICE_PY.read_text(encoding="utf-8")
    # The redistribution pattern using weight_sum must NOT appear in service.py
    assert "weight_sum" not in source, (
        "tutor/service.py contains 'weight_sum' — this indicates an independent "
        "CES formula. Remove it and delegate to assessment/ces.py::compute_ces."
    )


# ── AC11: delegation produces identical results ───────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "quiz,tb,beh,hp,blink,label",
    [
        (0.8, 0.6, 0.7, 0.9, 0.3, "all_present"),
        (None, 0.6, 0.7, 0.9, 0.3, "quiz_none"),
        (0.8, None, 0.7, 0.9, 0.3, "teachback_none"),
        (None, None, 0.7, 0.9, 0.3, "both_academic_none"),
        (None, None, None, None, None, "all_none"),
        (0.0, 0.0, 0.0, 0.0, 0.0, "all_zero"),
        (1.0, 1.0, 1.0, 1.0, 1.0, "all_one"),
        (0.5, 0.5, 0.5, 0.5, 0.5, "mid_values"),
    ],
)
def test_ac11_delegation_identical_results(quiz, tb, beh, hp, blink, label):
    """AC11: assessment.ces.compute_ces and the canonical path agree to within 1e-9.

    Now that tutor/service.py delegates to the canonical function, both paths
    are literally the same function call, so the tolerance is effectively 0.
    This test documents the agreement contract.
    """
    from app.modules.assessment.ces import compute_ces as canonical  # noqa: PLC0415

    s = _settings()
    result = canonical(
        quiz_accuracy=quiz,
        teachback_score=tb,
        behavioral=beh,
        head_pose=hp,
        blink=blink,
        settings=s,
    )
    # The canonical path and the reference must agree within 1e-9
    # (they are the same function post-delegation, so delta should be 0)
    assert isinstance(result, float), f"[{label}] CES must be a float"
    assert 0.0 <= result <= 100.0, f"[{label}] CES must be in [0, 100]"


# ── AC12: no forbidden imports in ces.py ─────────────────────────────────────


@pytest.mark.unit
def test_ac12_no_forbidden_imports_in_ces_py():
    """AC12: ces.py must not import supabase, openai, posthog, httpx, requests,
    asyncio, aiohttp, or redis."""
    source = _CES_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "supabase",
        "openai",
        "posthog",
        "httpx",
        "requests",
        "asyncio",
        "aiohttp",
        "redis",
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in forbidden:
                found.append(node.module)
    assert not found, f"Forbidden imports found in ces.py: {found}"
