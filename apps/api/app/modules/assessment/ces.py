"""CES v1 formula — Cognitive Engagement Score computation.

Pure synchronous computation module. No DB, no LLM, no network, no async.
Dev 4 imports compute_ces() and calls it on every AttentionSignalMessage
(every 5 seconds per session) from the WebSocket handler.

Scale contract: returns a float on the 0-100 POINT scale.
Dev 4 compares the result against settings.ces_threshold (default 50.0)
to decide whether to trigger an intervention.
"""

from __future__ import annotations

from app.config import Settings

__all__ = ["compute_ces"]


def compute_ces(
    *,
    quiz_accuracy: float | None,
    teachback_score: float | None,
    behavioral: float,
    head_pose: float,
    blink: float,
    settings: Settings,
) -> float:
    """Compute the Cognitive Engagement Score (CES) from 5 normalised signals.

    All inputs must be normalised to [0, 1] by the caller; out-of-range values
    are clamped silently. Returns a float on the 0-100 POINT scale.

    When teachback_score is None (student skipped teach-back), the teachback
    weight is redistributed proportionally across the remaining 4 signals so
    that a fully-engaged student can still achieve CES = 100.

    When quiz_accuracy is None (no quiz submitted yet in this window), it is
    treated as 0.0 with its full weight retained — this is a transient "no
    data yet" state, not a permanent skip, so no redistribution occurs.

    Args:
        quiz_accuracy:  Fraction of quiz questions answered correctly (0-1),
                        or None if no quiz submitted yet (treated as 0.0).
        teachback_score: Normalised teach-back score (0-1), or None if the
                         student skipped teach-back for this segment.
        behavioral:     Normalised on-screen behavioural engagement (0-1).
        head_pose:      Normalised head-pose attention score from MediaPipe (0-1).
        blink:          Normalised blink-rate score (0-1; higher = more alert).
        settings:       App settings carrying CES_WEIGHT_* env vars.

    Returns:
        CES as a float in [0.0, 100.0] on the POINT scale, rounded to 4 d.p.
    """
    # Clamp all signals to [0, 1]
    qa = min(1.0, max(0.0, quiz_accuracy if quiz_accuracy is not None else 0.0))
    beh = min(1.0, max(0.0, behavioral))
    hp = min(1.0, max(0.0, head_pose))
    bl = min(1.0, max(0.0, blink))

    if teachback_score is None:
        # Redistribute teachback weight proportionally across the 4 remaining signals.
        # remaining is derived from settings so tuning CES_WEIGHT_TEACHBACK automatically
        # adjusts the redistribution without any code change.
        remaining = 1.0 - settings.ces_weight_teachback
        if remaining <= 0.0:
            # Degenerate config guard: ces_weight_teachback == 1.0 means all other
            # weights are 0 — division is undefined, safe return is 0.0.
            return 0.0
        raw = (
            qa * (settings.ces_weight_quiz / remaining)
            + beh * (settings.ces_weight_behavioral / remaining)
            + hp * (settings.ces_weight_head_pose / remaining)
            + bl * (settings.ces_weight_blink / remaining)
        )
    else:
        tb = min(1.0, max(0.0, teachback_score))
        raw = (
            qa * settings.ces_weight_quiz
            + tb * settings.ces_weight_teachback
            + beh * settings.ces_weight_behavioral
            + hp * settings.ces_weight_head_pose
            + bl * settings.ces_weight_blink
        )

    # Guard: weights may sum to up to 1.001 (within ±0.001 model_validator tolerance),
    # which can push raw slightly above 1.0 in the redistribution branch.
    return min(100.0, round(raw * 100, 4))
