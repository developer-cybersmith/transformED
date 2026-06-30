"""
Tutor service — CES signal processing.

Boundary mapper, CES computation stub, and Redis window/history management.
Dev 3 will replace compute_ces() with the real formula (PRD §11).
"""

from __future__ import annotations

import logging
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
            return float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attention_signal field {key!r} must be numeric") from exc

    def _optional_float(key: str) -> float | None:
        v = data.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attention_signal field {key!r} must be numeric or null") from exc

    return NormalizedSignal(
        session_id=str(session_id),
        quiz_accuracy=_optional_float("quiz_accuracy"),
        teachback_score=_optional_float("teachback_score"),
        behavioral_score=_require_float("behavioral_score"),
        head_pose_score=_require_float("head_pose_score"),
        blink_rate=_require_float("blink_rate"),
    )


# ── CES computation ───────────────────────────────────────────────────────────


def compute_ces(signal: NormalizedSignal) -> float:  # noqa: ARG001
    """Compute the Cognitive Engagement Score.

    Temporary stub — Dev 3 replaces with the weighted formula from PRD §11.
    """
    return 0.5


# ── Public API ────────────────────────────────────────────────────────────────


async def start_session(session_id: str) -> None:
    """Drive the IDLE → TEACHING transition for a newly started session.

    Thin service-layer entry point over the tutor state machine so callers (the
    WebSocket handler) go through the service, mirroring ``process_attention_signal``.
    """
    from app.modules.tutor.state_machine.graph import dispatch_event

    await dispatch_event(session_id, "session_start")


async def process_attention_signal(
    session_id: str,
    signal: dict[str, Any],
) -> CesResult:
    """Process one attention signal window for *session_id*.

    Steps
    -----
    1. Parse and validate the payload → NormalizedSignal.
    2. Compute CES (stub: 0.5).
    3. Persist latest CES to ``session:{session_id}:ces_window`` (24 h TTL).
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
            await dispatch_event(session_id, "distraction_detected")
            intervention_dispatched = True

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
