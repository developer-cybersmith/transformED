"""CES v2 — Canonical Cognitive Engagement Score computation (Story 3-34).

Single authoritative implementation. ``tutor/service.py::compute_ces`` delegates
to this function. No other module in the codebase computes a CES independently.

Generalized redistribution (AC 2, Story 3-34):
    Any signal whose value is ``None`` is excluded from the weighted sum. Its
    weight is redistributed proportionally across the *present* signals:
        effective_weight_i = w_i / Σ(w_j for all present j)

    This generalises the §11 teachback-``None`` rule uniformly: when only
    teachback is ``None`` the present weights sum to 0.75, so each is divided by
    0.75, reproducing the §11 numbers exactly.

Defects fixed in this story:
    D61 — ``quiz_accuracy=None`` was treated as 0.0 (weight retained), not
          redistributed. Now handled identically to teachback=None.
    D62 — ``tutor/service.py::compute_ces`` was a duplicate implementation with
          no unit tests. Now it delegates here.
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
    """Compute the Cognitive Engagement Score (CES) from up to 5 normalised signals.

    All present values must be normalised to [0, 1] by the caller; out-of-range
    values are clamped silently. Returns a float on the 0-100 POINT scale,
    rounded to 4 decimal places.

    Any signal whose value is ``None`` is excluded from the weighted sum and its
    weight is redistributed proportionally across the remaining non-``None``
    signals so that a fully-engaged student can always achieve CES = 100.

    Args:
        quiz_accuracy:   Fraction correct [0-1], or None if no quiz submitted yet.
        teachback_score: Normalised teach-back score [0-1], or None if skipped.
        behavioral:      Normalised on-screen behavioural engagement [0-1], or
                         None when MediaPipe tracking unavailable (Story S3-40).
        head_pose:       Normalised head-pose attention score [0-1], or None when
                         MediaPipe face detector is limited (Story S3-40).
        blink:           Normalised blink-rate score [0-1], or None when MediaPipe
                         face detector is limited (Story S3-40).
        settings:        App settings carrying CES_WEIGHT_* env vars.

    Returns:
        CES as a float in [0.0, 100.0] on the POINT scale, rounded to 4 d.p.
        Returns 0.0 when all five signals are None.
    """
    # Build (value, weight) pairs for all signals; drop None entries.
    raw_pairs: list[tuple[float | None, float]] = [
        (quiz_accuracy, settings.ces_weight_quiz),
        (teachback_score, settings.ces_weight_teachback),
        (behavioral, settings.ces_weight_behavioral),
        (head_pose, settings.ces_weight_head_pose),
        (blink, settings.ces_weight_blink),
    ]

    # Keep only present (non-None) signals; clamp values to [0, 1].
    present: list[tuple[float, float]] = [
        (min(1.0, max(0.0, v)), w) for (v, w) in raw_pairs if v is not None
    ]

    weight_sum = sum(w for _, w in present)
    if weight_sum <= 0.0:
        # All signals None, or degenerate config where present weights sum to 0.
        return 0.0

    ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
    return min(100.0, round(ces, 4))
