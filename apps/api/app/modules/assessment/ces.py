"""CES canonical formula — Cognitive Engagement Score computation (Story 3-34).

CANONICAL IMPLEMENTATION — this is the single source of truth for CES arithmetic.
``tutor/service.py:compute_ces`` delegates here. No other module defines formula
logic (see guard test ``test_ces_formula_defined_in_one_place``).

Generalised redistribution (PRD §11, D1/D61):
    Any signal whose value is ``None`` is excluded from the weighted sum. Its
    weight is redistributed proportionally across the *present* signals:
        effective_weight_i = w_i / sum(w_j for all present j)
    This generalises the §11 teachback-None rule to quiz_accuracy and MediaPipe
    signals uniformly.

Defects fixed:
    D61 -- quiz_accuracy=None was treated as 0.0; now redistributed.
    D62 -- tutor/service.py had a duplicate CES implementation; now delegates here.

Scale contract: returns a float on the 0-100 POINT scale.
"""

from __future__ import annotations

import logging
import math

from app.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["compute_ces", "compute_personalized_threshold"]

# Signal names in canonical order, parallel to the raw_pairs tuple.
_SIGNAL_NAMES: tuple[str, ...] = (
    "quiz_accuracy",
    "teachback_score",
    "behavioral",
    "head_pose",
    "blink",
)


def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float | None,
    head_pose: float | None,
    blink: float | None,
    settings: Settings,
) -> float:
    """Compute the Cognitive Engagement Score (CES) from up to 5 normalised signals.

    Present values must be normalised to [0, 1] by the caller.  Out-of-range
    values emit a ``logger.warning`` and are clamped.  ``NaN`` or ``+/-inf``
    raise ``ValueError`` (they indicate corrupt signals, not absent ones).
    Returns a float on the 0-100 POINT scale, rounded to 4 decimal places.

    **Generalised redistribution rule (PRD §11, D1/D61):** When any signal is
    ``None``, its weight is redistributed proportionally across the remaining
    non-None signals so that a fully-engaged student can always achieve CES = 100.
      - ``teachback_score=None`` — student skipped teach-back (original §11 rule)
      - ``quiz_accuracy=None`` — no quiz submitted yet this window (D61)
      - MediaPipe signals (behavioral / head_pose / blink) — frame dropped / unavailable

    Edge cases:
      - All five signals None → weight_sum = 0 → returns 0.0.
      - Weights may sum to up to 1.001 (±0.001 tolerance) → result clamped to [0.0, 100.0].

    Args:
        quiz_accuracy:   Fraction correct [0-1], or None if no quiz submitted yet.
        teachback_score: Normalised teach-back score [0-1], or None if skipped.
        behavioral:      Normalised on-screen behavioural engagement [0-1], or None.
        head_pose:       Normalised head-pose attention score [0-1], or None.
        blink:           Normalised blink-rate score [0-1; higher = more alert], or None.
        settings:        App settings carrying CES_WEIGHT_* env vars.

    Returns:
        CES as a float in [0.0, 100.0] on the POINT scale, rounded to 4 d.p.
        Returns 0.0 when all five signals are None or all present weights are 0.

    Raises:
        ValueError: If any present (non-None) signal value is NaN or +/-inf.
    """
    # Build (value, weight) pairs for all signals.
    raw_pairs: tuple[tuple[float | None, float], ...] = (
        (quiz_accuracy, settings.ces_weight_quiz),
        (teachback_score, settings.ces_weight_teachback),
        (behavioral, settings.ces_weight_behavioral),
        (head_pose, settings.ces_weight_head_pose),
        (blink, settings.ces_weight_blink),
    )

    # Validate, warn, and clamp each present signal.
    present: list[tuple[float, float]] = []
    for (v, w), name in zip(raw_pairs, _SIGNAL_NAMES, strict=True):
        if v is None:
            continue  # absent signals are redistributed; None is valid
        if not math.isfinite(v):
            # AC 6: NaN / +/-inf indicates a corrupt signal -- raise immediately.
            raise ValueError(
                f"signal {name!r} has a non-finite value {v!r}; "
                "expected a float in [0.0, 1.0] or None"
            )
        if v < 0.0 or v > 1.0:
            # AC 5: warn before clamping so calibration bugs surface in logs.
            logger.warning(
                "signal %r=%r is outside [0.0, 1.0]; clamping to valid range",
                name,
                v,
            )
            v = min(1.0, max(0.0, v))
        present.append((v, w))

    # AC 8: NaN-safe guard.
    # `weight_sum <= 0.0` evaluates to False when weight_sum is NaN (IEEE 754),
    # which would skip the guard and produce a NaN result.  The `not (... > 0.0)`
    # form treats NaN as "not positive", returning 0.0 instead.
    weight_sum: float = sum(w for _, w in present)
    if not (weight_sum > 0.0):
        # All signals None, or degenerate config where present weights sum to 0.
        return 0.0

    ces: float = sum(v * (w / weight_sum) for v, w in present) * 100.0
    # AC 7: symmetric clamp -- max(0.0, ...) guards against negative-weight configs.
    return max(0.0, min(100.0, round(ces, 4)))


def compute_personalized_threshold(
    *,
    persistence: float | None,
    frustration_tolerance: float | None,
    goal_orientation: float | None,
    settings: Settings,
) -> float:
    """Compute a per-student CES intervention threshold adjusted by Learner DNA.

    Formula (Story 4-13, AC7):
        threshold = settings.ces_threshold
            + (frustration_tolerance - 50) × W_frustration  # high frustration → raise
            + (50 - persistence)           × W_persistence  # low persistence → raise
            + (50 - goal_orientation)      × W_goal         # low goal-orient → raise
        clamped to [ces_dna_threshold_min, ces_dna_threshold_max].

    A None dimension contributes 0 (no adjustment).
    All three None → returns settings.ces_threshold exactly (AC2).

    Returns:
        float in [settings.ces_dna_threshold_min, settings.ces_dna_threshold_max],
        rounded to 2 decimal places.
    """
    if persistence is None and frustration_tolerance is None and goal_orientation is None:
        return settings.ces_threshold

    frustration_adj = (
        (frustration_tolerance - 50.0) * settings.ces_dna_weight_frustration
        if frustration_tolerance is not None
        else 0.0
    )
    persistence_adj = (
        (50.0 - persistence) * settings.ces_dna_weight_persistence
        if persistence is not None
        else 0.0
    )
    goal_adj = (
        (50.0 - goal_orientation) * settings.ces_dna_weight_goal
        if goal_orientation is not None
        else 0.0
    )
    raw = settings.ces_threshold + frustration_adj + persistence_adj + goal_adj
    clamped = max(
        settings.ces_dna_threshold_min,
        min(settings.ces_dna_threshold_max, round(raw, 2)),
    )
    if clamped != round(raw, 2):
        logger.debug("personalized CES threshold clamped: raw=%.2f → %.2f", raw, clamped)
    return clamped
