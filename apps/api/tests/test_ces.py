"""Unit tests for CES v1 formula (Story 3-23).

Test count: 20
Coverage:
- AC 1:  ces.py importable (implicit — import failure cascades to all tests)
- AC 2:  __all__ contains only "compute_ces"
- AC 3:  keyword-only signature (positional args raise TypeError)
- AC 4:  no hardcoded weight literals in ces.py
- AC 5:  all 5 inputs clamped to [0,1], silent (quiz, teachback, behavioral, head_pose, blink)
- AC 6:  full 5-signal weighted sum formula; output clamped to [0.0, 100.0]
- AC 7:  teachback_score=None redistributes weights proportionally (per-weight verified)
- AC 8:  quiz_accuracy=None treated as 0.0, weight retained; teachback=0.0 uses full formula
- AC 9:  division-by-zero guard returns 0.0
- AC 10: all-zeros → 0.0
- AC 11: all-ones → 100.0 (full formula)
- AC 12: all-ones → 100.0 (teachback None)
- AC 13: mid-values (all 0.5) → 50.0
- AC 14: partial values with teachback None → ≈73.33
- AC 15: out-of-range inputs clamped, not rejected (all 5 signals covered)
- AC 16: custom non-default weights produce correct result
- AC 17: no forbidden imports in ces.py

All tests are @pytest.mark.unit — no DB, no LLM, no network.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.config import Settings

# ── Settings factory ─────────────────────────────────────────────────────────


def _settings(
    quiz: float = 0.35,
    tb: float = 0.25,
    beh: float = 0.20,
    hp: float = 0.12,
    blink: float = 0.08,
) -> Settings:
    """Build a Settings instance with known CES weights for deterministic tests."""
    return Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
        langfuse_public_key="x",
        langfuse_secret_key="x",
        ces_weight_quiz=quiz,
        ces_weight_teachback=tb,
        ces_weight_behavioral=beh,
        ces_weight_head_pose=hp,
        ces_weight_blink=blink,
    )


# Lazy import so tests fail clearly if ces.py doesn't exist yet
def _import_compute_ces():
    from app.modules.assessment.ces import compute_ces  # noqa: PLC0415

    return compute_ces


# ── AC 2: __all__ contains only "compute_ces" ─────────────────────────────


@pytest.mark.unit
def test_dunder_all_contains_only_compute_ces():
    """AC 2 (updated Story 4-13): ces.py __all__ contains exactly the two canonical
    CES formula functions. compute_personalized_threshold was added deliberately in
    Story 4-13 — it is CES arithmetic (computes the threshold that drives CES
    interventions) and belongs in this canonical module. Any further addition to __all__
    must update this list explicitly, not silently.
    """
    import app.modules.assessment.ces as ces_module

    assert hasattr(ces_module, "__all__"), "__all__ must be defined in ces.py"
    assert list(ces_module.__all__) == ["compute_ces", "compute_personalized_threshold"], (
        f"__all__ must contain exactly the two canonical CES formula functions, "
        f"got {ces_module.__all__!r}. Adding to ces.py __all__ requires updating this guard."
    )


# ── AC 3: keyword-only signature ─────────────────────────────────────────────


@pytest.mark.unit
def test_positional_args_raise_type_error():
    """AC 3: All parameters are keyword-only and the function is synchronous (not async)."""
    import inspect  # noqa: PLC0415

    compute_ces = _import_compute_ces()
    s = _settings()
    with pytest.raises(TypeError):
        compute_ces(1.0, 1.0, 1.0, 1.0, 1.0, s)  # type: ignore[call-arg]
    assert not inspect.iscoroutinefunction(compute_ces), (
        "compute_ces must be synchronous — Dev 4 calls it on the hot WebSocket path"
    )


# ── AC 4: no hardcoded weight literals ───────────────────────────────────────


@pytest.mark.unit
def test_no_hardcoded_weight_literals_in_ces_py():
    """AC 4: ces.py must not contain hardcoded numeric weight literals.

    Uses an allowlist — only {0.0, 1.0, 100.0} are permitted float literals.
    This is structurally complete: any weight literal (however named) that isn't
    0.0, 1.0, or 100.0 will be caught, including redistribution products.
    """
    ces_path = Path(__file__).parent.parent / "app" / "modules" / "assessment" / "ces.py"
    source = ces_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = {0.0, 1.0, 100.0}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            if node.value not in allowed:
                found.append(node.value)
    assert not found, f"Unexpected float literals in ces.py (only 0.0/1.0/100.0 allowed): {found}"


# ── AC 10: all-zeros → 0.0 ───────────────────────────────────────────────────


@pytest.mark.unit
def test_all_zeros_returns_zero():
    """AC 10: All signals = 0 → CES = 0.0."""
    compute_ces = _import_compute_ces()
    result = compute_ces(
        quiz_accuracy=0.0,
        teachback_score=0.0,
        behavioral=0.0,
        head_pose=0.0,
        blink=0.0,
        settings=_settings(),
    )
    assert result == pytest.approx(0.0, abs=1e-6)


# ── AC 11: all-ones → 100.0 (full formula) ───────────────────────────────────


@pytest.mark.unit
def test_all_ones_full_formula_returns_100():
    """AC 11: All signals = 1.0 with teachback present → CES = 100.0."""
    compute_ces = _import_compute_ces()
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=1.0,
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=_settings(),
    )
    assert result == pytest.approx(100.0, abs=0.001)


# ── AC 12: all-ones → 100.0 (teachback None) ─────────────────────────────────


@pytest.mark.unit
def test_all_ones_teachback_none_returns_100():
    """AC 12: Redistributed weights still sum to 1.0 → all-ones → 100.0."""
    compute_ces = _import_compute_ces()
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=None,
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=_settings(),
    )
    assert result == pytest.approx(100.0, abs=0.001)


# ── AC 13: mid-values 0.5 → 50.0 ─────────────────────────────────────────────


@pytest.mark.unit
def test_mid_values_all_half_returns_50():
    """AC 13: All signals = 0.5 → CES = 0.5 × sum(weights) × 100 = 50.0."""
    compute_ces = _import_compute_ces()
    result = compute_ces(
        quiz_accuracy=0.5,
        teachback_score=0.5,
        behavioral=0.5,
        head_pose=0.5,
        blink=0.5,
        settings=_settings(),
    )
    assert result == pytest.approx(50.0, abs=0.001)


# ── AC 14: partial values with teachback None → ≈73.33 ───────────────────────


@pytest.mark.unit
def test_partial_values_teachback_none_correct_weighted_sum():
    """AC 14: quiz=1.0, beh=0.5, hp=0.5, blink=0.5, teachback=None → ≈73.33."""
    compute_ces = _import_compute_ces()
    # remaining = 0.75
    # CES = (1.0×0.35/0.75 + 0.5×0.20/0.75 + 0.5×0.12/0.75 + 0.5×0.08/0.75) × 100
    #     = (0.4667 + 0.1333 + 0.0800 + 0.0533) × 100 ≈ 73.33
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=None,
        behavioral=0.5,
        head_pose=0.5,
        blink=0.5,
        settings=_settings(),
    )
    assert result == pytest.approx(73.33, abs=0.1)


# ── AC 7: redistribution weights are proportional (per-weight) ───────────────


@pytest.mark.unit
def test_redistribution_weights_are_proportional():
    """AC 7: Each redistributed weight equals original_weight / remaining.

    Uses asymmetric signals (only quiz=1.0, all others=0.0) so any weight-swap
    bug produces a distinctly wrong result — not just a wrong sum.
    """
    compute_ces = _import_compute_ces()
    s = _settings()  # quiz=0.35, tb=0.25, beh=0.20, hp=0.12, blink=0.08
    # remaining = 1.0 - 0.25 = 0.75
    # Only quiz=1.0, so: CES = 1.0 × (0.35 / 0.75) × 100 ≈ 46.67
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=None,
        behavioral=0.0,
        head_pose=0.0,
        blink=0.0,
        settings=s,
    )
    remaining = 1.0 - s.ces_weight_teachback
    expected = (1.0 * (s.ces_weight_quiz / remaining)) * 100
    assert result == pytest.approx(expected, abs=0.01)


# ── AC 8b (S3-53): quiz_accuracy=None AND teachback_score=None ───────────────


@pytest.mark.unit
def test_both_none_quiz_and_teachback_redistributed():
    """AC 8+7 (updated S3-53): quiz=None + teachback=None → both dropped, remaining 3 normalize.

    Old behaviour (D61/D62): quiz treated as 0 inside redistribution → CES≈53.3.
    Correct behaviour  : both dropped; remaining signals (0.40 total weight) normalize.
    With behavioral=head_pose=blink=1.0 → CES = 100.0.
    """
    compute_ces = _import_compute_ces()
    s = _settings()
    # quiz and teachback both dropped
    # remaining: behavioral=1.0 (w=0.20), head_pose=1.0 (w=0.12), blink=1.0 (w=0.08)
    # weight_sum = 0.40; CES = (0.40/0.40) * 100 = 100.0
    result = compute_ces(
        quiz_accuracy=None,
        teachback_score=None,
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


# ── AC 9: division-by-zero guard ─────────────────────────────────────────────


@pytest.mark.unit
def test_division_by_zero_guard_returns_zero():
    """AC 9: ces_weight_teachback=1.0 → remaining=0.0 → returns 0.0 without raising."""
    compute_ces = _import_compute_ces()
    # ces_weight_teachback=1.0 forces all other weights to 0.0 to satisfy sum=1.0
    s = _settings(quiz=0.0, tb=1.0, beh=0.0, hp=0.0, blink=0.0)
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=None,  # triggers redistribution path → remaining = 0.0
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(0.0, abs=1e-6)


# ── AC 15: out-of-range inputs clamped ───────────────────────────────────────


@pytest.mark.unit
def test_out_of_range_inputs_are_clamped_not_rejected():
    """AC 15: Values outside [0,1] are clamped silently — no exception raised."""
    compute_ces = _import_compute_ces()
    s = _settings()
    # quiz=1.5 → clamped to 1.0; teachback=-0.3 → clamped to 0.0; behavioral=2.0 → 1.0
    result = compute_ces(
        quiz_accuracy=1.5,
        teachback_score=-0.3,
        behavioral=2.0,
        head_pose=0.5,
        blink=0.5,
        settings=s,
    )
    # Equivalent to: quiz=1.0, teachback=0.0, behavioral=1.0, head_pose=0.5, blink=0.5
    expected = (1.0 * 0.35 + 0.0 * 0.25 + 1.0 * 0.20 + 0.5 * 0.12 + 0.5 * 0.08) * 100
    assert result == pytest.approx(expected, abs=0.001)


# ── AC 16: custom non-default weights ────────────────────────────────────────


@pytest.mark.unit
def test_custom_weights_produce_correct_result():
    """AC 16: Non-default weights (quiz=0.6, tb=0.0, beh=0.2, hp=0.1, blink=0.1)."""
    compute_ces = _import_compute_ces()
    s = _settings(quiz=0.6, tb=0.0, beh=0.2, hp=0.1, blink=0.1)
    # All signals = 1.0, teachback present → CES = 1.0 × sum(weights) × 100 = 100.0
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=1.0,
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_custom_weights_partial_values():
    """AC 16b: Specific weighted sum with custom weights and partial signals."""
    compute_ces = _import_compute_ces()
    s = _settings(quiz=0.6, tb=0.0, beh=0.2, hp=0.1, blink=0.1)
    # quiz=0.8, tb=0.5, beh=0.4, hp=0.3, blink=0.2
    result = compute_ces(
        quiz_accuracy=0.8,
        teachback_score=0.5,
        behavioral=0.4,
        head_pose=0.3,
        blink=0.2,
        settings=s,
    )
    expected = (0.8 * 0.6 + 0.5 * 0.0 + 0.4 * 0.2 + 0.3 * 0.1 + 0.2 * 0.1) * 100
    assert result == pytest.approx(expected, abs=0.001)


# ── AC 6: specific non-trivial weighted sum ───────────────────────────────────


@pytest.mark.unit
def test_full_formula_specific_non_trivial_values():
    """AC 6: Non-trivial partial values produce exactly the correct weighted sum."""
    compute_ces = _import_compute_ces()
    s = _settings()
    # quiz=0.8, tb=0.6, beh=0.7, hp=0.9, blink=0.3
    # CES = (0.8×0.35 + 0.6×0.25 + 0.7×0.20 + 0.9×0.12 + 0.3×0.08) × 100
    #     = (0.280 + 0.150 + 0.140 + 0.108 + 0.024) × 100 = 70.2
    result = compute_ces(
        quiz_accuracy=0.8,
        teachback_score=0.6,
        behavioral=0.7,
        head_pose=0.9,
        blink=0.3,
        settings=s,
    )
    expected = (0.8 * 0.35 + 0.6 * 0.25 + 0.7 * 0.20 + 0.9 * 0.12 + 0.3 * 0.08) * 100
    assert result == pytest.approx(expected, abs=0.001)


# ── AC 17: no forbidden imports ──────────────────────────────────────────────


@pytest.mark.unit
def test_ces_py_has_no_forbidden_imports():
    """AC 17: ces.py must not import supabase, openai, posthog, httpx, requests, asyncio."""
    ces_path = Path(__file__).parent.parent / "app" / "modules" / "assessment" / "ces.py"
    source = ces_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_modules = {"supabase", "openai", "posthog", "httpx", "requests", "asyncio", "aiohttp"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden_modules:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in forbidden_modules:
                found.append(node.module)
    assert not found, f"Forbidden imports found in ces.py: {found}"


# ── AC 5 (extended): head_pose and blink clamped ─────────────────────────────


@pytest.mark.unit
def test_head_pose_and_blink_clamped_when_out_of_range():
    """AC 5: head_pose > 1 and blink < 0 are clamped silently — no exception raised."""
    compute_ces = _import_compute_ces()
    s = _settings()
    result = compute_ces(
        quiz_accuracy=0.5,
        teachback_score=0.5,
        behavioral=0.5,
        head_pose=2.0,  # > 1.0 — clamped to 1.0
        blink=-1.0,  # < 0.0 — clamped to 0.0
        settings=s,
    )
    # Equivalent: quiz=0.5, tb=0.5, beh=0.5, hp=1.0, blink=0.0
    expected = (0.5 * 0.35 + 0.5 * 0.25 + 0.5 * 0.20 + 1.0 * 0.12 + 0.0 * 0.08) * 100
    assert result == pytest.approx(expected, abs=0.001)


# ── AC 8 (extended): teachback=0.0 uses full formula, not redistribution ─────


@pytest.mark.unit
def test_teachback_zero_uses_full_formula_not_redistribution():
    """AC 8: teachback_score=0.0 must route through the FULL formula.

    A bug using 'if not teachback_score:' (Python falsy) would route 0.0
    into the redistribution branch, inflating CES by dropping the teachback
    weight. This test proves 0.0 and None produce different results.
    """
    compute_ces = _import_compute_ces()
    s = _settings()
    # teachback=0.0 → full formula:
    # CES = (0.5×0.35 + 0.0×0.25 + 0.5×0.20 + 0.5×0.12 + 0.5×0.08) × 100 = 37.5
    result_zero = compute_ces(
        quiz_accuracy=0.5,
        teachback_score=0.0,
        behavioral=0.5,
        head_pose=0.5,
        blink=0.5,
        settings=s,
    )
    # teachback=None → redistribution (remaining=0.75):
    # CES = 0.5 × (0.35+0.20+0.12+0.08)/0.75 × 100 = 0.5 × 1.0 × 100 = 50.0
    result_none = compute_ces(
        quiz_accuracy=0.5,
        teachback_score=None,
        behavioral=0.5,
        head_pose=0.5,
        blink=0.5,
        settings=s,
    )
    assert result_zero == pytest.approx(37.5, abs=0.001), (
        f"teachback=0.0 should give 37.5 (full formula), got {result_zero}"
    )
    assert result_none == pytest.approx(50.0, abs=0.001), (
        f"teachback=None should give 50.0 (redistribution), got {result_none}"
    )
    assert result_zero != result_none, (
        "teachback=0.0 and teachback=None must give different CES values"
    )


# ── Output clamp: CES never exceeds 100.0 ────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# Story 3-34 RED TESTS — describe CORRECT behavior (fail with current ces.py)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_quiz_accuracy_none_redistributes_weight():
    """Story 3-34 AC 2+3: quiz_accuracy=None redistributes its weight proportionally.

    # BREAKING-CHANGE: D61
    Old behavior (bug): quiz=None treated as 0.0, weight retained → CES = 65.0
    New behavior (correct): quiz weight redistributed across present signals → CES = 100.0
    """
    compute_ces = _import_compute_ces()
    s = _settings()  # quiz=0.35, tb=0.25, beh=0.20, hp=0.12, blink=0.08
    # quiz=None: weight 0.35 redistributed over tb+beh+hp+blink (weight_sum=0.65)
    # All 4 present signals = 1.0 → effective weight = 1.0 → CES = 100.0
    result = compute_ces(
        quiz_accuracy=None,
        teachback_score=1.0,
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_both_academic_signals_none_redistributes_behavioral():
    """Story 3-34 AC 2+3: quiz=None AND teachback=None both redistribute.

    # BREAKING-CHANGE: D61
    Old behavior: quiz=None→0.0 in teachback redistribution → ~53.33
    New behavior: both redistribute, only beh+hp+blink present → CES = 100.0
    """
    compute_ces = _import_compute_ces()
    s = _settings()
    # Only beh=1.0, hp=1.0, blink=1.0 present → weight_sum=0.40
    # CES = 1.0 × (0.40/0.40) × 100 = 100.0
    result = compute_ces(
        quiz_accuracy=None,
        teachback_score=None,
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_behavioral_none_redistributes():
    """Story 3-34 AC 2: behavioral=None redistributes weight across other present signals."""
    compute_ces = _import_compute_ces()
    s = _settings()  # beh weight=0.20
    # Only quiz=1.0, teachback=1.0, hp=1.0, blink=1.0 present → weight_sum=0.80
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=1.0,
        behavioral=None,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_head_pose_none_redistributes():
    """Story 3-34 AC 2: head_pose=None redistributes weight. All others=1.0 → 100.0."""
    compute_ces = _import_compute_ces()
    s = _settings()
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=1.0,
        behavioral=1.0,
        head_pose=None,
        blink=1.0,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_blink_none_redistributes():
    """Story 3-34 AC 2: blink=None redistributes weight. All others=1.0 → 100.0."""
    compute_ces = _import_compute_ces()
    s = _settings()
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=1.0,
        behavioral=1.0,
        head_pose=1.0,
        blink=None,
        settings=s,
    )
    assert result == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_all_five_none_returns_zero():
    """Story 3-34 AC 4: all five signals=None → weight_sum=0 → returns 0.0 without raising."""
    compute_ces = _import_compute_ces()
    s = _settings()
    result = compute_ces(
        quiz_accuracy=None,
        teachback_score=None,
        behavioral=None,
        head_pose=None,
        blink=None,
        settings=s,
    )
    assert result == pytest.approx(0.0, abs=1e-6)


@pytest.mark.unit
def test_single_signal_present_returns_its_value_scaled():
    """Story 3-34 AC 2: only quiz=0.6 present → effective weight = 1.0 → CES = 60.0."""
    compute_ces = _import_compute_ces()
    s = _settings()
    result = compute_ces(
        quiz_accuracy=0.6,
        teachback_score=None,
        behavioral=None,
        head_pose=None,
        blink=None,
        settings=s,
    )
    assert result == pytest.approx(60.0, abs=0.001)


@pytest.mark.unit
def test_output_clamped_to_100_when_weights_sum_exceeds_one():
    """AC 6 (output clamp): CES never exceeds 100.0 even when weights sum to 1.001.

    Settings @model_validator allows abs(sum - 1.0) <= 0.001. In the redistribution
    branch, (sum - w_teachback) / remaining can be slightly > 1.0, pushing raw > 1.
    compute_ces must clamp the output via min(100.0, ...) as specified in AC 6.
    """
    compute_ces = _import_compute_ces()
    # Sum = 0.3503 + 0.001 + 0.20 + 0.12 + 0.3296 = 1.0009 (within ±0.001 tolerance)
    s = _settings(quiz=0.3503, tb=0.001, beh=0.20, hp=0.12, blink=0.3296)
    result = compute_ces(
        quiz_accuracy=1.0,
        teachback_score=None,  # triggers redistribution; raw ≈ 1.0009
        behavioral=1.0,
        head_pose=1.0,
        blink=1.0,
        settings=s,
    )
    assert result <= 100.0, f"CES exceeded 100.0: {result}"
    assert result == pytest.approx(100.0, abs=0.001)
