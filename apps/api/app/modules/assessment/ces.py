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

Review patches applied (6-agent review, 2026-08-11):
    P-A — ValueError raised for non-finite (NaN/±inf) signal values.
    P-B — logger.warning emitted for out-of-range values before clamping.
    P1  — weight_sum guard uses ``not (weight_sum > 0.0)`` (NaN-safe).
    P2  — ``max(0.0, ...)`` lower-bound guard restored on output.
"""

from __future__ import annotations

import logging
import math

from app.config import Settings

__all__ = ["compute_ces"]

logger = logging.getLogger(__name__)

_SIGNAL_NAMES = ("quiz_accuracy", "teachback_score", "behavioral", "head_pose", "blink")


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

    All present values must be normalised to [0, 1] by the caller. Values outside
    [0, 1] are clamped after emitting a logger.warning. Non-finite values (NaN,
    ±inf) are a contract violation and raise ValueError — NaN means "signal
    arrived but is numerically corrupt", distinct from None which means "signal
    not yet available / measurement not taken".

    Returns a float on the 0-100 POINT scale, rounded to 4 decimal places.
    Returns 0.0 when all five signals are None or weight_sum ≤ 0.

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

    Raises:
        ValueError: If any present signal value is non-finite (NaN or ±inf).
    """
    raw_values = (quiz_accuracy, teachback_score, behavioral, head_pose, blink)

    # P-A: Reject non-finite values — NaN ≠ None (corrupt signal ≠ absent signal).
    # The WebSocket boundary (_parse_signal) validates this for the production path;
    # this check is a defence-in-depth backstop for direct API callers.
    for name, v in zip(_SIGNAL_NAMES, raw_values):
        if v is not None and not math.isfinite(v):
            raise ValueError(
                f"CES signal {name!r} must be finite or None; got {v!r}. "
                "Validate at the caller boundary — _parse_signal rejects non-finite values."
            )

    # Build (value, weight) pairs for all signals.
    raw_pairs: list[tuple[float | None, float]] = [
        (quiz_accuracy, settings.ces_weight_quiz),
        (teachback_score, settings.ces_weight_teachback),
        (behavioral, settings.ces_weight_behavioral),
        (head_pose, settings.ces_weight_head_pose),
        (blink, settings.ces_weight_blink),
    ]

    # P-B: Warn on out-of-range values before clamping — indicates miscalibrated
    # upstream source (bad MediaPipe calibration, scoring bug). Clamping is still
    # applied silently per AC 5, but the warning makes the anomaly visible in logs.
    for name, (v, _) in zip(_SIGNAL_NAMES, raw_pairs):
        if v is not None and not (0.0 <= v <= 1.0):
            logger.warning(
                "CES signal %r is out of range [0, 1]: %.4f — clamping. "
                "Check upstream calibration (MediaPipe, quiz scorer, teach-back scorer).",
                name,
                v,
            )

    # Keep only present (non-None) signals; clamp values to [0, 1].
    present: list[tuple[float, float]] = [
        (min(1.0, max(0.0, v)), w) for (v, w) in raw_pairs if v is not None
    ]

    # P1: Use `not (weight_sum > 0.0)` rather than `weight_sum <= 0.0` so that a
    # NaN weight_sum (from degenerate settings carrying NaN weights) also triggers
    # this guard — NaN <= 0.0 is False in IEEE 754, which would otherwise proceed
    # to division producing NaN and ultimately return 100.0 spuriously.
    weight_sum = sum(w for _, w in present)
    if not (weight_sum > 0.0):
        # All signals None, or degenerate config where present weights sum to ≤ 0.
        return 0.0

    ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
    # P2: Restore max(0.0, ...) lower-bound guard alongside the upper-bound clamp.
    # Negative CES is mathematically impossible with valid non-negative settings,
    # but this guards against degenerate configs with negative weight values.
    return max(0.0, min(100.0, round(ces, 4)))
