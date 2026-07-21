"""Per-session Learner DNA fusion using Exponential Moving Average (EMA).

After a session ends, Dev 4 calls compute_and_store_ces_baseline() to refresh
the per-user CES baseline, then calls fuse_learner_dna() to blend the session's
behavioural signals into the learner's 9-dimension profile.

EMA formula (applied per dimension):
    new_value = round(retain * old + (1 - retain) * signal, 4)
where:
    retain  = settings.dna_ema_retain  (default 0.7, env var DNA_EMA_RETAIN)
    old     = current DB value; None → treated as _NEUTRAL (50.0, first session)
    signal  = 0-100 score derived from this session's quiz/teachback/event data

Nine dimensions (exact learner_dna column names):
    pattern_recognition, logical_deduction, processing_speed,
    frustration_tolerance, persistence, help_seeking,
    goal_orientation, curiosity_index, study_independence

No LLM calls in this module. Profile text generation is a separate story (Task 4).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supabase import Client

    from app.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["fuse_learner_dna"]

# ── Signal computation constants (Sprint 4 can move these to Settings) ────────

_JARGON_CAP = 5  # jargon_hover events → curiosity_index signal 100
_HELP_CAP = 4  # help_seeking events → max help_seeking/study_independence signal
_SKIP_CAP = 4  # skip_segment events → goal_orientation signal 0
_INTERVENTION_CAP = 3  # intervention_triggered events → frustration_tolerance signal 0
_FAST_RESPONSE_MS = 15_000  # avg response_time_ms ≤ this → processing_speed = 100
_SLOW_RESPONSE_MS = 60_000  # avg response_time_ms ≥ this → processing_speed = 0
_TEACHBACK_LOW_SCORE = 60  # teachback score below this triggers persistence retry check
_NEUTRAL = 50.0  # default signal / old value when no data

# After every _REASSESSMENT_INTERVAL sessions the flag user:{uid}:reassessment_due is set
# in Redis, signalling the frontend to prompt for a fresh 20-question diagnostic.
_REASSESSMENT_INTERVAL: int = 10

_NINE_DIMENSIONS = (
    "pattern_recognition",
    "logical_deduction",
    "processing_speed",
    "frustration_tolerance",
    "persistence",
    "help_seeking",
    "goal_orientation",
    "curiosity_index",
    "study_independence",
)


def _apply_ema(old: float | None, signal: float, retain: float) -> float:
    """Apply EMA: round(retain * old + (1 - retain) * signal, 4), clamped [0, 100].

    When old is None (no prior DB value), treat as _NEUTRAL (50.0).
    """
    base = _NEUTRAL if old is None else float(old)
    raw = retain * base + (1.0 - retain) * signal
    return min(100.0, max(0.0, round(raw, 4)))


def _compute_signals(
    *,
    quiz_rows: list[dict[str, Any]],
    tb_rows: list[dict[str, Any]],
    event_counts: dict[str, int],
) -> dict[str, float]:
    """Map raw session data to a 0-100 signal for each of the 9 dimensions.

    All parameters are plain Python structures — no DB calls, no async.

    Args:
        quiz_rows:    List of {is_correct: bool, response_time_ms: int | None}.
        tb_rows:      List of {score: int, attempt_number: int, segment_id: str}.
        event_counts: Dict of {event_type: count} for the session.
    """
    sigs: dict[str, float] = {}

    # ── Cognitive: pattern_recognition + logical_deduction ────────────────────
    if quiz_rows:
        correct = sum(1 for r in quiz_rows if r.get("is_correct"))
        accuracy = correct / len(quiz_rows)
    else:
        accuracy = None

    if accuracy is None:
        # No quiz rows → signal is 0.0 (AC 6: "0 if no quiz attempts")
        # processing_speed uses _NEUTRAL (AC 7) — pattern/logical do not.
        sigs["pattern_recognition"] = 0.0
        sigs["logical_deduction"] = 0.0
    else:
        sigs["pattern_recognition"] = min(100.0, max(0.0, accuracy * 100.0))
        sigs["logical_deduction"] = sigs["pattern_recognition"]

    # ── Cognitive: processing_speed (inverse avg response time) ───────────────
    times = [r["response_time_ms"] for r in quiz_rows if r.get("response_time_ms") is not None]
    if not times:
        sigs["processing_speed"] = _NEUTRAL
    else:
        avg_ms = sum(times) / len(times)
        speed_range = float(_SLOW_RESPONSE_MS - _FAST_RESPONSE_MS)
        raw_speed = 100.0 - (avg_ms - _FAST_RESPONSE_MS) / speed_range * 100.0
        sigs["processing_speed"] = min(100.0, max(0.0, raw_speed))

    # ── Emotional: frustration_tolerance (inverse of intervention count) ───────
    interventions = event_counts.get("intervention_triggered", 0)
    sigs["frustration_tolerance"] = min(
        100.0, max(0.0, 100.0 - (interventions / _INTERVENTION_CAP) * 100.0)
    )

    # ── Self-direction: persistence (retry after low teachback score) ──────────
    if not tb_rows:
        sigs["persistence"] = _NEUTRAL
    else:
        # Group by segment_id to detect retry pattern per segment
        seg_attempts: dict[str, list[dict]] = defaultdict(list)
        for row in tb_rows:
            seg_attempts[row["segment_id"]].append(row)

        had_low_score = False
        had_retry_after_low = False

        for attempts in seg_attempts.values():
            scores_by_attempt = {a["attempt_number"]: (a.get("score") or 0) for a in attempts}
            first_score = scores_by_attempt.get(1, _TEACHBACK_LOW_SCORE)
            max_attempt = max(a["attempt_number"] for a in attempts)

            if first_score < _TEACHBACK_LOW_SCORE:
                had_low_score = True
                if max_attempt > 1:
                    had_retry_after_low = True

        if had_retry_after_low:
            sigs["persistence"] = 100.0
        elif had_low_score:
            sigs["persistence"] = 25.0  # gave up after low score
        else:
            sigs["persistence"] = 75.0  # completed with no low-score issue

    # ── Self-direction: help_seeking + study_independence (inverse pair) ───────
    help_events = event_counts.get("help_seeking", 0)
    help_signal = min(100.0, max(0.0, (help_events / _HELP_CAP) * 100.0))
    sigs["help_seeking"] = help_signal
    sigs["study_independence"] = min(100.0, max(0.0, 100.0 - help_signal))

    # ── Self-direction: goal_orientation (inverse of skip events) ─────────────
    skip_events = event_counts.get("skip_segment", 0)
    sigs["goal_orientation"] = min(100.0, max(0.0, 100.0 - (skip_events / _SKIP_CAP) * 100.0))

    # ── Self-direction: curiosity_index (jargon hover events) ─────────────────
    jargon_events = event_counts.get("jargon_hover", 0)
    sigs["curiosity_index"] = min(100.0, max(0.0, (jargon_events / _JARGON_CAP) * 100.0))

    return sigs


async def fuse_learner_dna(
    *,
    user_id: str,
    session_id: str,
    supabase: Client,
    settings: Settings,
    redis: Any = None,
) -> dict[str, float] | None:
    """Blend this session's behavioural signals into the user's Learner DNA profile.

    Reads the session's quiz attempts, teach-back attempts, and session events
    from Supabase, computes a 0-100 signal for each of the 9 Learner DNA
    dimensions, applies EMA blending against the stored profile, and upserts
    the updated values together with an incremented session_count.

    Call this AFTER writing ces_final and ended_at to the sessions table.
    The guard `ended_at is None → return None` enforces ordering silently.

    Args:
        user_id:    UUID of the learner (from JWT-decoded subject).
        session_id: UUID of the just-ended session.
        supabase:   Synchronous supabase-py v2 client (service-role key, RLS bypassed).
        settings:   App settings (carries dna_ema_retain).
        redis:      Optional async Redis client. When provided and session_count reaches
                    a multiple of _REASSESSMENT_INTERVAL, sets the reassessment flag key
                    user:{user_id}:reassessment_due. Non-fatal: Redis failures log WARNING
                    and do not prevent the function from returning new_dims.

    Returns:
        Dict of {dimension: new_value} for all 9 dimensions, or None if the
        session has no ended_at (incomplete session — safe no-op).

    Raises:
        HTTPException 404: Session not found or user_id mismatch.
        HTTPException 503: DB read/write failure on sessions or learner_dna.
    """
    # SECURITY NOTE: user_id must come from the JWT-decoded subject (router level).
    # Service-role client bypasses RLS; .eq("user_id", user_id) filters are the access gate.
    from fastapi import HTTPException, status  # local import avoids circular dependency

    # ── Step 1: Read session row ───────────────────────────────────────────────
    try:
        session_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("sessions")
                .select("session_id, user_id, ended_at")
                .eq("session_id", session_id)
                .maybe_single()
                .execute()
            )
        )
    except Exception as exc:
        logger.error(
            "DNA fusion: session read failed session=%s: %s", session_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not read session data.",
        ) from exc

    if session_resp.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    session_row = session_resp.data

    # Guard: IDOR check
    if str(session_row.get("user_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    # Guard: session not yet ended
    if session_row.get("ended_at") is None:
        logger.warning(
            "DNA fusion: session %s has no ended_at — skipping update for user=%s",
            session_id,
            user_id,
        )
        return None

    # ── Step 2: Read session data (non-fatal failures → neutral signals) ───────
    quiz_rows: list[dict[str, Any]] = []
    tb_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []

    try:
        quiz_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("quiz_attempts")
                .select("is_correct, response_time_ms, segment_id")
                .eq("session_id", session_id)
                .execute()
            )
        )
        quiz_rows = quiz_resp.data or []
    except Exception as exc:
        logger.warning("DNA fusion: quiz read failed session=%s: %s", session_id, exc)

    try:
        tb_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("teachback_attempts")
                .select("score, attempt_number, segment_id")
                .eq("session_id", session_id)
                .execute()
            )
        )
        tb_rows = tb_resp.data or []
    except Exception as exc:
        logger.warning("DNA fusion: teachback read failed session=%s: %s", session_id, exc)

    try:
        events_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("session_events")
                .select("event_type")
                .eq("session_id", session_id)
                .execute()
            )
        )
        event_rows = events_resp.data or []
    except Exception as exc:
        logger.warning("DNA fusion: events read failed session=%s: %s", session_id, exc)

    # Count event types
    event_counts: dict[str, int] = {}
    for r in event_rows:
        t = r.get("event_type", "")
        if t:
            event_counts[t] = event_counts.get(t, 0) + 1

    # ── Step 3: Read existing learner_dna row ────────────────────────────────
    old_row: dict[str, Any] = {}
    old_session_count = 0
    try:
        dna_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("learner_dna")
                .select(", ".join(_NINE_DIMENSIONS) + ", session_count")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        )
        if dna_resp.data is not None:
            old_row = dna_resp.data
            old_session_count = int(old_row.get("session_count") or 0)
    except Exception as exc:
        logger.warning("DNA fusion: learner_dna read failed user=%s: %s", user_id, exc)
        # Neutral old values — still proceed with update

    # ── Step 4: Compute signals and apply EMA ────────────────────────────────
    signals = _compute_signals(
        quiz_rows=quiz_rows,
        tb_rows=tb_rows,
        event_counts=event_counts,
    )
    retain = settings.dna_ema_retain
    new_dims: dict[str, float] = {}
    for dim in _NINE_DIMENSIONS:
        old_val = old_row.get(dim)
        old_float = float(old_val) if old_val is not None else None
        new_dims[dim] = _apply_ema(old_float, signals[dim], retain)

    # ── Step 5: Upsert learner_dna (dimensions + session_count only) ─────────
    upsert_payload: dict[str, Any] = {
        "user_id": user_id,
        "session_count": old_session_count + 1,
        **new_dims,
    }
    try:
        upsert_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("learner_dna")
                .upsert(upsert_payload, on_conflict="user_id")
                .execute()
            )
        )
        upsert_error = getattr(upsert_resp, "error", None)
        if upsert_error:
            safe_err = str(upsert_error).replace("\n", " ")
            logger.error(
                "DNA fusion: learner_dna upsert failed user=%s: %s",
                user_id,
                safe_err,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not update learner profile.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("DNA fusion: upsert exception user=%s: %s", user_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not update learner profile.",
        ) from exc

    # ── Step 6: Write growth tracking events (non-fatal) ──────────────────────
    from app.modules.assessment.dna_growth import record_dna_growth  # local import

    old_dims_for_growth: dict[str, float | None] = {
        dim: (float(old_row[dim]) if old_row.get(dim) is not None else None)
        for dim in _NINE_DIMENSIONS
    }
    _safe_sid_growth = str(session_id).replace("\n", " ").replace("\r", " ")
    try:
        await record_dna_growth(
            session_id=session_id,
            old_dims=old_dims_for_growth,
            new_dims=new_dims,
            supabase=supabase,
        )
    except Exception as exc:
        logger.warning("DNA fusion: growth tracking failed session=%s: %s", _safe_sid_growth, exc)

    # ── Step 7: Set re-assessment flag in Redis (non-fatal) ──────────────────
    new_count = old_session_count + 1
    if new_count % _REASSESSMENT_INTERVAL == 0 and redis is not None:
        _safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")
        try:
            await redis.set(f"user:{user_id}:reassessment_due", "1")
            logger.info(
                "DNA fusion: reassessment flag set for user=%s at count=%d",
                _safe_uid,
                new_count,
            )
        except Exception as exc:
            logger.warning(
                "DNA fusion: reassessment flag set failed user=%s: %s",
                _safe_uid,
                exc,
            )

    logger.info(
        "DNA fusion: updated user=%s session=%s session_count=%d",
        user_id,
        session_id,
        old_session_count + 1,
    )
    return new_dims
