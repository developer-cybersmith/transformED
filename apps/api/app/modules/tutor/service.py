"""
Tutor service — CES signal processing.

Boundary mapper, weighted CES computation (PRD §11, 0–100 scale), and Redis
window/history management.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_CES_WINDOW_TTL = 86_400  # 24 h
_CES_HISTORY_MAX = 10


# ── Domain types ──────────────────────────────────────────────────────────────


@dataclass
class NormalizedSignal:
    """Internal representation of an attention signal after boundary mapping."""

    session_id: str
    quiz_accuracy: float | None       # None when quiz not yet attempted
    teachback_score: float | None     # None when teach-back skipped
    behavioral_score: float
    head_pose_score: float
    blink_rate: float


@dataclass
class CesResult:
    """Result of processing one attention signal window."""

    session_id: str
    ces: float
    intervention_dispatched: bool


# ── Boundary mapper ───────────────────────────────────────────────────────────


def _parse_signal(payload: dict[str, Any]) -> NormalizedSignal:
    """Map a WebSocket message dict into a validated NormalizedSignal.

    Accepts both the full WsMessage envelope (``{"type": ..., "payload": {...}}``)
    and a flat dict.  Handles quiz_accuracy=None and teachback_score=None.
    """
    # Unwrap WsMessage envelope if present
    data: dict[str, Any] = payload.get("payload") or payload  # type: ignore[assignment]

    session_id = data.get("session_id")
    if not session_id:
        raise ValueError("attention_signal missing required field: session_id")

    def _require_float(key: str) -> float:
        v = data.get(key)
        if v is None:
            raise ValueError(f"attention_signal missing required field: {key}")
        try:
            f = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attention_signal field {key!r} must be numeric") from exc
        # Reject NaN/±inf: float("nan") would propagate through compute_ces and clamp to a
        # misleading value (NaN→100 = maximally engaged), silently suppressing interventions.
        if not math.isfinite(f):
            raise ValueError(f"attention_signal field {key!r} must be a finite number")
        return f

    def _optional_float(key: str) -> float | None:
        v = data.get(key)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attention_signal field {key!r} must be numeric or null") from exc
        if not math.isfinite(f):
            raise ValueError(f"attention_signal field {key!r} must be a finite number or null")
        return f

    return NormalizedSignal(
        session_id=str(session_id),
        quiz_accuracy=_optional_float("quiz_accuracy"),
        teachback_score=_optional_float("teachback_score"),
        behavioral_score=_require_float("behavioral_score"),
        head_pose_score=_require_float("head_pose_score"),
        blink_rate=_require_float("blink_rate"),
    )


# ── CES computation ───────────────────────────────────────────────────────────


def compute_ces(signal: NormalizedSignal) -> float:
    """Weighted Cognitive Engagement Score on the 0–100 scale (PRD §11).

    ``CES = (Σ signalᵢ × weightᵢ) × 100`` using the frozen ``settings.ces_weight_*`` weights, matching
    Dev 3's ``ces_contribution`` scale contract (assessment/service.py) so ``ces_threshold = 50`` is
    correct.

    Signals are 0–1 fractions; ``quiz_accuracy`` / ``teachback_score`` may be ``None`` (not yet attempted
    / skipped). The weight of any ``None`` signal is redistributed proportionally across the present
    signals (each present weight ÷ sum-of-present-weights). This generalises the §11 teachback-``None``
    rule — when only teachback is ``None`` the present weights sum to 0.75, so each is divided by 0.75,
    reproducing the §11 numbers exactly. Result is clamped to ``[0, 100]``.
    """
    from app.config import get_settings

    s = get_settings()
    # (value, weight) for every signal, dropping the None ones.
    pairs = [
        (signal.quiz_accuracy, s.ces_weight_quiz),
        (signal.teachback_score, s.ces_weight_teachback),
        (signal.behavioral_score, s.ces_weight_behavioral),
        (signal.head_pose_score, s.ces_weight_head_pose),
        (signal.blink_rate, s.ces_weight_blink),
    ]
    present = [(v, w) for (v, w) in pairs if v is not None]
    weight_sum = sum(w for _, w in present)
    if weight_sum <= 0:
        return 0.0
    ces = sum(v * (w / weight_sum) for v, w in present) * 100.0
    return max(0.0, min(100.0, ces))


# ── Learner Mode helpers ──────────────────────────────────────────────────────


def qa_phase_seconds(tier: str | None) -> int:
    """Map a learner tier string to Q&A phase duration in seconds.

    T1 (beginner) → longest Q&A window (default 600 s / 10 min)
    T2 (intermediate) → standard window (default 300 s / 5 min)
    T3 (advanced) → shortest window (default 150 s / 2.5 min)
    Unknown / None → T2 default (300 s)

    All durations are env-var tunable via ``settings.learner_tier_*_qa_seconds``.
    """
    from app.config import get_settings

    s = get_settings()
    return {
        "T1": s.learner_tier_t1_qa_seconds,
        "T2": s.learner_tier_t2_qa_seconds,
        "T3": s.learner_tier_t3_qa_seconds,
    }.get(tier or "", s.learner_tier_default_qa_seconds)


# ── Public API ────────────────────────────────────────────────────────────────


async def start_session(session_id: str) -> None:
    """Drive the IDLE → TEACHING transition for a newly started session.

    Thin service-layer entry point over the tutor state machine so callers (the
    WebSocket handler) go through the service, mirroring ``process_attention_signal``.
    """
    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(session_id, "session_start")


# Lifecycle events a CLIENT may drive via WebSocket. distraction_detected / fatigue_detected are
# excluded on purpose — those come from the server-side CES engine, not the client; session_reset is
# admin-only; session_start has its own handler.
_CLIENT_DRIVABLE_EVENTS = frozenset(
    {
        "segment_complete",
        "checkin_complete",
        "low_checkin_score",
        "quiz_trigger",
        "quiz_complete",
        "quiz_failed",
        "teachback_complete",
        "teachback_failed",
        "lesson_complete",
    }
)


async def advance_tutor_state(session_id: str, event: str) -> None:
    """Dispatch a client-driven lifecycle *event* into the tutor FSM.

    Allow-listed: rejects any event a client must not be able to drive (server/engine/admin events).
    """
    if event not in _CLIENT_DRIVABLE_EVENTS:
        raise ValueError(f"event not client-drivable: {event!r}")

    # Completing a segment advances the student's position (used to pick the right segment's
    # pre-generated intervention messages). 24h TTL, matching the other session keys.
    if event == "segment_complete":
        from app.core.redis import get_redis

        redis = get_redis()
        await redis.incr(f"session:{session_id}:segment_index")
        await redis.expire(f"session:{session_id}:segment_index", 86_400)

    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(session_id, event)


async def _segment_intervention_messages(session_id: str, redis: Any) -> dict[str, Any]:
    """Return the current segment's ``intervention_messages`` from the cached LessonPackage.

    Returns ``{}`` on any miss (no cache / parse error / no segments / bad index). Performs ONLY
    Redis reads — never a Supabase/DB round-trip — so the intervention hot path stays < 50 ms.
    """
    try:
        raw = await redis.get(f"lesson_package:{session_id}")
        if not raw:
            return {}
        pkg = json.loads(raw)
        segments = pkg.get("segments") or []
        if not segments:
            return {}
        idx_raw = await redis.get(f"session:{session_id}:segment_index")
        idx = int(idx_raw) if idx_raw else 0
        idx = max(0, min(idx, len(segments) - 1))
        # Frozen LessonPackage schema: Segment.interventions = {distraction|confusion|fatigue: [3]}.
        return segments[idx].get("interventions") or {}
    except Exception:  # noqa: BLE001 — degrade gracefully, never block the hot path
        logger.warning("intervention message lookup failed for %s", session_id, exc_info=True)
        return {}


async def process_attention_signal(
    session_id: str,
    signal: dict[str, Any],
) -> CesResult:
    """Process one attention signal window for *session_id*.

    Steps
    -----
    1. Parse and validate the payload → NormalizedSignal.
    2. Compute the weighted CES (PRD §11, 0–100 scale).
    3. Persist latest CES to ``session:{session_id}:ces_window`` and
       ``tutor_ces:{session_id}`` (24 h TTL).
    4. Prepend CES to ``session:{session_id}:ces_history`` (keep last 10).
    5. Read history; if the two most-recent values are both below
       ``settings.ces_threshold`` and tutor cooldown is absent, dispatch
       ``distraction_detected`` to the tutor state machine.
    6. Return CesResult.
    """
    from app.config import get_settings
    from app.core.redis import get_redis
    from app.modules.tutor.state_machine.graph import dispatch_event

    settings = get_settings()
    redis = get_redis()

    normalized = _parse_signal(signal)
    ces = compute_ces(normalized)

    window_key = f"session:{session_id}:ces_window"
    history_key = f"session:{session_id}:ces_history"

    # Latest window
    await redis.set(window_key, ces, ex=_CES_WINDOW_TTL)
    await redis.set(f"tutor_ces:{session_id}", ces, ex=_CES_WINDOW_TTL)  # ces_computation (s3-3)

    # Prepend to history and trim to keep only the last _CES_HISTORY_MAX values
    await redis.lpush(history_key, ces)
    await redis.ltrim(history_key, 0, _CES_HISTORY_MAX - 1)
    await redis.expire(history_key, _CES_WINDOW_TTL)

    # Read history to evaluate the intervention trigger
    history_raw: list[str] = await redis.lrange(history_key, 0, _CES_HISTORY_MAX - 1)

    intervention_dispatched = False

    if len(history_raw) >= 2:
        # Index 0 is most recent (LPUSH prepends)
        recent = [float(v) for v in history_raw[:2]]
        cooldown_key = f"tutor_cooldown:{session_id}"
        in_cooldown = await redis.exists(cooldown_key)

        if all(v < settings.ces_threshold for v in recent) and not in_cooldown:
            logger.info(
                "[tutor:%s] CES below threshold (%.3f, %.3f) — dispatching distraction_detected",
                session_id,
                recent[0],
                recent[1],
            )
            # Pass the current segment's pre-generated messages so the FSM can select one
            # (Redis reads only — no DB/LLM on this hot path).
            seg_msgs = await _segment_intervention_messages(session_id, redis)
            result = await dispatch_event(
                session_id, "distraction_detected", payload={"intervention_messages": seg_msgs}
            )
            intervention_dispatched = True

            # Deliver the selected message to the client (in-process WS hub). Best-effort: a
            # delivery failure must never break signal processing.
            msg = result.get("intervention_message")
            if result.get("current_state") == "INTERVENING" and msg:
                try:
                    from app.core.websocket import manager

                    await manager.send(
                        session_id,
                        {
                            "type": "tutor_intervene",
                            "payload": {
                                "session_id": session_id,
                                "type": result.get("intervention_type") or "distraction",
                                "message": msg,
                            },
                        },
                    )
                except Exception:
                    logger.exception("tutor_intervene delivery failed for %s", session_id)

    logger.debug(
        "[tutor:%s] ces=%.4f intervention_dispatched=%s",
        session_id,
        ces,
        intervention_dispatched,
    )

    return CesResult(
        session_id=session_id,
        ces=ces,
        intervention_dispatched=intervention_dispatched,
    )
