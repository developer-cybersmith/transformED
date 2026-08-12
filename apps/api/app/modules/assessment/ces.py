"""CES canonical formula — Cognitive Engagement Score computation.

CANONICAL IMPLEMENTATION — this is the single source of truth for CES arithmetic.

``tutor/service.py:compute_ces`` is a thin NormalizedSignal wrapper that delegates
here. No other module should define formula logic (see guard test
``test_ces_formula_defined_in_one_place`` in ``test_s3_53_ces_production_closure.py``).

Scale contract: returns a float on the 0-100 POINT scale.
"""

from __future__ import annotations

from app.config import Settings

__all__ = ["compute_ces"]


def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float | None,
    head_pose: float | None,
    blink: float | None,
    settings: Settings,
) -> float:
    """Compute the Cognitive Engagement Score (CES) from 5 normalised signals.

    All inputs must be normalised to [0, 1] by the caller; out-of-range values
    are clamped silently. Returns a float on the 0-100 POINT scale.

    **Generalised redistribution rule (PRD §11, D1/D2):** When any signal is
    ``None``, its weight is redistributed proportionally across the remaining
    non-None signals. This generalises the §11 teachback-None rule to cover:
      - ``teachback_score=None`` — student skipped teach-back (original rule)
      - ``quiz_accuracy=None`` — no quiz submitted yet this window
      - MediaPipe signals (behavioral / head_pose / blink) — frame dropped

    Edge cases:
      - All five signals None → weight_sum = 0 → returns 0.0.
      - Weights may sum to up to 1.001 (±0.001 model_validator tolerance) so
        the result is clamped to [0.0, 100.0] before return.

    Args:
        quiz_accuracy:   Fraction of quiz questions answered correctly (0-1), or None.
        teachback_score: Normalised teach-back score (0-1), or None if skipped.
        behavioral:      Normalised on-screen behavioural engagement (0-1), or None.
        head_pose:       Normalised head-pose attention score (0-1), or None.
        blink:           Normalised blink-rate score (0-1; higher = more alert), or None.
        settings:        App settings carrying CES_WEIGHT_* env vars.

    Returns:
        CES as a float in [0.0, 100.0] on the POINT scale, rounded to 4 d.p.
    """
    pairs = [
        (quiz_accuracy, settings.ces_weight_quiz),
        (teachback_score, settings.ces_weight_teachback),
        (behavioral, settings.ces_weight_behavioral),
        (head_pose, settings.ces_weight_head_pose),
        (blink, settings.ces_weight_blink),
    ]
    # Drop None signals; clamp present values to [0, 1].
    clamped = [(min(1.0, max(0.0, v)), w) for v, w in pairs if v is not None]
    weight_sum = sum(w for _, w in clamped)
    if weight_sum <= 0.0:
        return 0.0
    raw = sum(v * (w / weight_sum) for v, w in clamped)
    return min(100.0, round(raw * 100.0, 4))
