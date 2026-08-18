"""
Assessment service layer — quiz grading, teach-back scoring, and session report business logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import statistics
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import HTTPException, status
from supabase import Client

from app.config import Settings, get_settings
from app.core.db import rows, single_row
from app.core.posthog_client import capture_event
from app.modules.assessment.onboarding_questions import (
    ALL_NINE_DIMENSIONS,
    BADGE_THRESHOLD,
    BADGE_THRESHOLDS,
    QUESTION_SUBDIMENSION_MAP,
)
from app.modules.assessment.prompts import generate_onboarding_profile, score_teachback
from app.modules.assessment.schemas import (
    OnboardingAnswer,
    OnboardingResult,
    QuizAnswer,
    QuizResult,
    TeachbackResult,
)
from app.providers.llm.openai import OpenAILLMProvider

if TYPE_CHECKING:
    from app.modules.assessment.router import SessionReport, TeachbackDetail

logger = logging.getLogger(__name__)


async def get_analytics_consent(user_id: str, supabase: Client) -> bool:
    """Return True if the user has granted analytics consent (DPDP Act 2023).

    Checks the users.analytics_consent column added by migration
    20260703010000_add_analytics_consent.sql.  Returns False on any DB error
    or if the column does not exist yet (safe default — no events sent).

    Args:
        user_id: User UUID from the decoded JWT.
        supabase: Synchronous Supabase client.
    """
    try:
        resp = await asyncio.to_thread(
            lambda: (
                supabase.table("users")
                .select("analytics_consent")
                .eq("id", user_id)
                .maybe_single()
                .execute()
            )
        )
        row = single_row(resp)
        if row is None:
            return False
        return bool(row.get("analytics_consent", False))
    except Exception as exc:
        logger.warning("PostHog consent check failed user=%s: %s", user_id, exc)
        return False  # fail-safe: suppress events when consent check fails


def _score_to_label(score: float) -> str:
    """Convert a numeric rubric sub-score (0-100) to a descriptive label.

    Never returns raw floats to students (CLAUDE.md Learner DNA display rules).
    Thresholds: Exceptional ≥90, Proficient ≥75, Developing ≥60, Emerging ≥40, Beginning <40.
    """
    if score >= 90:
        return "Exceptional"
    if score >= 75:
        return "Proficient"
    if score >= 60:
        return "Developing"
    if score >= 40:
        return "Emerging"
    return "Beginning"


# Story 3-29 — tier-context constants and helpers

_TIER_LABELS: dict[str, str] = {
    "T1": "Full-Depth",
    "T2": "Standard",
    "T3": "Refresher",
}


def _quiz_accuracy_label(accuracy: float, total: int) -> str | None:
    """Map quiz accuracy to a descriptive label (no raw floats to students).

    Returns None when total == 0 — cannot evaluate accuracy with zero questions.
    Thresholds: Strong ≥80%, Developing ≥60%, Needs Review <60%.
    """
    if total == 0:
        return None
    if accuracy >= 0.8:
        return "Strong"
    if accuracy >= 0.6:
        return "Developing"
    return "Needs Review"


# Story 3-30 — Learner DNA growth-label constants and helper

_DNA_GROWTH_IMPROVING_THRESHOLD: float = 2.0
_DNA_GROWTH_DECLINING_THRESHOLD: float = -2.0


def _delta_to_growth_label(delta: float | None) -> str | None:
    if delta is None:
        return None
    if delta > _DNA_GROWTH_IMPROVING_THRESHOLD:
        return "Improving"
    if delta < _DNA_GROWTH_DECLINING_THRESHOLD:
        return "Needs Attention"
    return "Stable"


async def create_session(
    *,
    lesson_id: str,
    user_id: str,
    supabase: Client,
) -> dict[str, Any]:
    """Mint a `sessions` row for *user_id* on *lesson_id* (Story 2-35 / D18).

    **This is the only INSERTER of `sessions` in the codebase** (`complete_session`
    below is the only UPDATER, of `ended_at` alone). Before this, all 7
    `table("sessions")` references were `.select(...)`, `apps/web` never inserted
    one either, and the frontend invented `crypto.randomUUID()`. So the ownership
    check in `grade_quiz` correctly rejected an id that had never existed, and
    quiz and teach-back 404'd for every student.

    `session_id` and `started_at` are deliberately NOT sent — they are
    `DEFAULT gen_random_uuid()` and `DEFAULT now()`. A client-chosen id would
    reintroduce D18; a client-chosen `started_at` would make session duration and
    Dev 3's CES-final logic meaningless.

    Called once per lesson attempt. Re-learning the same lesson creates a NEW
    session on purpose — sessions are attempt-scoped, and `analytics` and the CES
    history depend on that. Do not add a unique constraint on
    `(user_id, lesson_id)` or a reuse-if-exists shortcut.

    Raises:
        HTTPException 404: the lesson does not exist **or** belongs to someone
            else. Deliberately the SAME response for both — a distinct 403 would
            turn this endpoint into an existence oracle for lesson ids. Matches
            `content/router.py:get_lesson` and `media/router.py:get_signed_url`.
        HTTPException 500: the insert returned no row.
    """
    lesson_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("lessons")
            .select("lesson_id, user_id")
            .eq("lesson_id", lesson_id)
            .maybe_single()
            .execute()
        )
    )
    lesson_row = single_row(lesson_resp)
    if lesson_row is None or str(lesson_row.get("user_id", "")) != str(user_id):
        # ONE response for both cases — see the docstring. Do not split this into
        # a 404 and a 403 "for clarity"; the difference is the leak.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        )

    insert_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .insert({"user_id": str(user_id), "lesson_id": str(lesson_id)})
            .execute()
        )
    )
    created = rows(insert_resp)
    if not created:
        logger.error(
            "create_session: sessions insert returned no row for lesson=%s",
            lesson_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create session.",
        )

    row = created[0]
    started_at = row.get("started_at")
    return {
        "session_id": str(row["session_id"]),
        "lesson_id": str(row.get("lesson_id") or lesson_id),
        "started_at": str(started_at) if started_at is not None else None,
    }


async def complete_session(
    *,
    session_id: str,
    user_id: str,
    supabase: Client,
) -> dict[str, Any]:
    """Mark *session_id* as ended, writing `sessions.ended_at`.

    **This is the only writer of `sessions.ended_at` in the codebase.** Before
    this, nothing ever wrote it -- confirmed by grepping the whole API for
    `ended_at` -- so `get_session_report`'s `duration_minutes`/`completed_at`
    fields silently returned 0.0/None for every session ever, including one a
    student had genuinely finished start to end. The frontend must call this
    exactly once, when the player reaches its terminal ENDED status.

    Idempotent by construction: the UPDATE's `.is_("ended_at", "null")` filter
    means only the FIRST call actually writes a row -- a double-fire (retry,
    a second tab, StrictMode) affects 0 rows on every call after the first,
    so a later, in-flight duplicate can never clobber the real completion
    timestamp with a later one (Scale & Load Q6 -- concurrent check-then-act).

    Raises:
        HTTPException 404: the session does not exist **or** belongs to
            someone else (SEC-006 — same response for both, matching
            `create_session` above).
    """
    session_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .select("session_id, user_id, ended_at")
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
    )
    session_row = single_row(session_resp)
    if session_row is None or str(session_row.get("user_id", "")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    existing_ended_at = session_row.get("ended_at")
    if existing_ended_at:
        return {"session_id": session_id, "ended_at": str(existing_ended_at)}

    ended_at = datetime.now(UTC).isoformat()
    await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .update({"ended_at": ended_at})
            .eq("session_id", session_id)
            .is_("ended_at", "null")
            .execute()
        )
    )
    return {"session_id": session_id, "ended_at": ended_at}


async def grade_quiz(
    *,
    session_id: str,
    lesson_id: str,
    segment_id: str,
    answers: list[QuizAnswer],
    user_id: str,
    supabase: Client,
) -> QuizResult:
    """Grade a quiz submission and persist each answer to quiz_attempts.

    Validates session ownership, loads quiz questions from the lesson JSONB,
    scores each answer by comparing response_index to correct_index,
    bulk-inserts to quiz_attempts, and returns a QuizResult with per-question
    feedback.

    The supabase client is synchronous (supabase-py v2 sync Client); all DB
    calls are wrapped in asyncio.to_thread to avoid blocking the event loop.

    Args:
        session_id: UUID of the live session.
        lesson_id: UUID of the lesson whose JSONB content contains the quiz.
        segment_id: ID of the segment (string, not UUID) within the lesson.
        answers: Student answers — one QuizAnswer per submitted question.
        user_id: User UUID from the decoded JWT (for ownership check).
        supabase: Synchronous Supabase client from app.core.db.get_supabase().

    Returns:
        QuizResult with score, ces_contribution, and per-question feedback.

    Raises:
        HTTPException 404: Session not found, lesson not found, or segment not found.
        HTTPException 403: Session belongs to a different user, or session.lesson_id
            != lesson_id (IDOR guard).
        HTTPException 409: Duplicate quiz attempt detected (unique constraint).
        HTTPException 422: answers is empty, or a submitted question_id is not in the segment quiz.
        HTTPException 500: quiz_attempts insert fails for a non-duplicate reason.
    """
    # Step 1 — Validate session ownership
    session_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .select("session_id, user_id, lesson_id")
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
    )
    session_row = single_row(session_resp)
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found.",
        )
    if str(session_row["user_id"]) != str(user_id):
        # SEC-006: Return 404 to prevent session enumeration oracle.
        # Attacker must not distinguish "belongs to someone else" from "doesn't exist".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied.",
        )
    # IDOR guard — session must belong to the requested lesson
    if str(session_row.get("lesson_id", "")) != str(lesson_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this lesson.",
        )

    # Step 2 — Load lesson JSONB
    lesson_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("lessons")
            .select("content")
            .eq("lesson_id", lesson_id)
            .maybe_single()
            .execute()
        )
    )
    lesson_row = single_row(lesson_resp)
    if lesson_row is None or lesson_row.get("content") is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lesson {lesson_id!r} not found or has no generated content.",
        )

    content: dict[str, Any] = lesson_row["content"]
    segments: list[dict[str, Any]] = content.get("segments", [])

    # Step 3 — Find the segment
    target_segment: dict[str, Any] | None = next(
        (s for s in segments if s["segment_id"] == segment_id), None
    )
    if target_segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment {segment_id!r} not found in lesson {lesson_id!r}.",
        )

    # Step 4 — Build question lookup {question_id: question_dict}
    question_map: dict[str, dict[str, Any]] = {
        q["question_id"]: q for q in target_segment.get("quiz", [])
    }

    # Step 5 — Guard: reject empty submissions before any grading or DB write
    if not answers:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="answers list must not be empty.",
        )

    # Step 5b — Guard: reject duplicate question_ids in a single submission (TQ-007)
    seen_qids: set[str] = set()
    for ans in answers:
        if ans.question_id in seen_qids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Duplicate question_id {ans.question_id!r} in submission.",
            )
        seen_qids.add(ans.question_id)

    # Step 6 — Query existing attempt count to compute attempt_number
    count_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("quiz_attempts")
            .select("id", count=cast("Any", "exact"))
            .eq("session_id", session_id)
            .eq("segment_id", segment_id)
            .execute()
        )
    )
    attempt_number: int = (count_resp.count or 0) + 1

    # Step 7 — Grade each answer
    graded: list[dict[str, Any]] = []
    for ans in answers:
        question = question_map.get(ans.question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"question_id {ans.question_id!r} not found in segment {segment_id!r}."),
            )
        # SEC-008: Validate response_index is within valid option range
        options = question.get("options", [])
        if not (0 <= ans.response_index < len(options)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"response_index {ans.response_index} is out of range "
                    f"for question {ans.question_id!r}."
                ),
            )
        graded.append(
            {
                "question": question,
                "is_correct": ans.response_index == question["correct_index"],
                "selected_index": ans.response_index,
                "response_time_ms": ans.response_time_ms,
            }
        )

    # Step 8 — Bulk insert to quiz_attempts
    rows_to_insert = [
        {
            "session_id": session_id,
            "segment_id": segment_id,
            "question_id": g["question"]["question_id"],
            "response_index": g["selected_index"],
            "is_correct": g["is_correct"],
            "response_time_ms": g["response_time_ms"],
            "attempt_number": attempt_number,
        }
        for g in graded
    ]
    insert_resp = await asyncio.to_thread(
        lambda: supabase.table("quiz_attempts").insert(rows_to_insert).execute()
    )
    insert_error = getattr(insert_resp, "error", None)
    if insert_error:
        err_str = str(insert_error).lower()
        if "duplicate" in err_str or "unique" in err_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate quiz attempt detected.",
            )
        safe_err = str(insert_error).replace("\n", " ").replace("\r", " ")
        logger.error(
            "quiz_attempts insert failed: session=%s error=%s",
            session_id,
            safe_err,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist quiz attempt.",
        )
    logger.info(
        "quiz_attempts inserted: session=%s segment=%s count=%d",
        session_id,
        segment_id,
        len(rows_to_insert),
    )

    # Step 9 — Compute aggregate metrics
    correct_count = sum(1 for g in graded if g["is_correct"])
    total_count = len(graded)
    quiz_accuracy: float = correct_count / total_count if total_count > 0 else 0.0

    settings = get_settings()
    ces_contribution: float = round(quiz_accuracy * settings.ces_weight_quiz * 100, 4)
    # CES SCALE CONTRACT (communicate to Dev 4):
    # ces_contribution is on the 0-100 POINT scale.
    # ces_weight_quiz (0.35 default) = max 35.0 pts at full accuracy.
    # Dev 4's ces.py must SUM component contributions directly — do NOT multiply by 100 again.

    # Step 10 — Build per-question feedback
    feedback: list[dict[str, Any]] = [
        {
            "question_id": g["question"]["question_id"],
            "question": g["question"]["question"],
            "is_correct": g["is_correct"],
            "correct_index": g["question"]["correct_index"],
            "correct_option": (
                g["question"]["options"][g["question"]["correct_index"]]
                if 0 <= g["question"]["correct_index"] < len(g["question"]["options"])
                else None
            ),
            "selected_option": (
                g["question"]["options"][g["selected_index"]]
                if 0 <= g["selected_index"] < len(g["question"]["options"])
                else None
            ),
            "explanation": g["question"]["explanation"],
        }
        for g in graded
    ]

    consent = await get_analytics_consent(user_id=user_id, supabase=supabase)
    capture_event(
        distinct_id=user_id,
        event="assessment_quiz_submitted",
        properties={
            "session_id": session_id,
            "segment_id": segment_id,
            "ces_contribution": ces_contribution,
            "quiz_accuracy": quiz_accuracy,
            "total_questions": total_count,
            "correct_count": correct_count,
        },
        analytics_consent=consent,
    )

    return QuizResult(
        session_id=session_id,
        score=quiz_accuracy * 100,
        correct_count=correct_count,
        total_count=total_count,
        ces_contribution=ces_contribution,
        feedback=feedback,
    )


async def grade_teachback(
    *,
    session_id: str,
    lesson_id: str,
    segment_id: str,
    response_text: str,
    user_id: str,
    supabase: Client,
) -> TeachbackResult:
    """Score a student's typed teach-back response and persist to teachback_attempts.

    Validates session ownership (user + IDOR lesson guard), loads the lesson segment,
    calls score_teachback() via OpenAILLMProvider, persists to teachback_attempts,
    and returns TeachbackResult with rubric_scores, CES contribution, and feedback.

    Args:
        session_id: UUID of the live session.
        lesson_id: UUID of the lesson whose JSONB content contains the segment.
        segment_id: ID of the segment the student just completed.
        response_text: Student's typed teach-back (no STT, no timer, no duration_seconds).
        user_id: User UUID from the decoded JWT (for ownership check).
        supabase: Synchronous Supabase client from app.core.db.get_supabase().

    Returns:
        TeachbackResult with rubric_scores, overall_score, ces_contribution, feedback.

    Raises:
        HTTPException 404: Session not found, lesson not found, or segment not found.
        HTTPException 404: Session belongs to a different user (SEC-006 enumeration prevention).
        HTTPException 403: session.lesson_id does not match request lesson_id (IDOR guard).
        HTTPException 409: Duplicate teach-back attempt (unique constraint).
        HTTPException 500: DB insert fails for a non-duplicate reason.
    """
    # Step 1 — Validate session ownership
    session_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .select("session_id, user_id, lesson_id")
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
    )
    session_row = single_row(session_resp)
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found.",
        )
    if str(session_row["user_id"]) != str(user_id):
        # SEC-006: Return 404 to prevent session enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied.",
        )
    # IDOR guard — session must belong to the requested lesson
    if str(session_row.get("lesson_id", "")) != str(lesson_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this lesson.",
        )

    # Step 2 — Load lesson JSONB
    lesson_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("lessons")
            .select("content")
            .eq("lesson_id", lesson_id)
            .maybe_single()
            .execute()
        )
    )
    lesson_row = single_row(lesson_resp)
    if lesson_row is None or lesson_row.get("content") is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lesson {lesson_id!r} not found or has no generated content.",
        )

    content: dict[str, Any] = lesson_row["content"]
    segments: list[dict[str, Any]] = content.get("segments", [])

    # Step 3 — Find the segment
    target_segment: dict[str, Any] | None = next(
        (s for s in segments if s["segment_id"] == segment_id), None
    )
    if target_segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment {segment_id!r} not found in lesson {lesson_id!r}.",
        )

    # Step 4 — Extract topic and key concepts from segment
    topic: str = target_segment.get("title", "")
    key_concepts: list[str] = [j["term"] for j in target_segment.get("jargon", [])]

    # Step 5 — Query existing attempt count to compute attempt_number
    count_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("teachback_attempts")
            .select("id", count=cast("Any", "exact"))
            .eq("session_id", session_id)
            .eq("segment_id", segment_id)
            .execute()
        )
    )
    attempt_number: int = (count_resp.count or 0) + 1

    # Step 6 — Score via GPT-4o-mini through OpenAILLMProvider (cost tracked by provider)
    provider = OpenAILLMProvider(lesson_id=lesson_id)
    try:
        result = await score_teachback(
            topic=topic,
            key_concepts=key_concepts,
            response_text=response_text,
            provider=provider,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("score_teachback failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Scoring service unavailable.",
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Scoring service unavailable.",
        )

    # Step 7 — Compute CES contribution
    # CES SCALE CONTRACT (communicate to Dev 4):
    # ces_contribution is on the 0-100 POINT scale where ces_weight_teachback (0.25)
    # represents the MAXIMUM POINT contribution (25 pts).
    # Formula: CES = quiz_contrib + teachback_contrib + behavioral_contrib + ... (each 0-max_pts)
    # Trigger threshold: CES < 50 (checked on the 0-100 summed scale).
    settings = get_settings()
    ces_contribution: float = round((result.score / 100.0) * settings.ces_weight_teachback * 100, 4)

    # Step 8 — Build feedback string (praise only for score >= 90, praise + correction otherwise)
    feedback: str = (
        result.praise if not result.correction else f"{result.praise}\n\n{result.correction}"
    )

    # Step 9 — Persist to teachback_attempts
    row: dict[str, Any] = {
        "session_id": session_id,
        "segment_id": segment_id,
        "response_text": response_text,
        "score": result.score,
        "feedback_praise": result.praise,
        "feedback_correction": result.correction,
        "concepts_hit": result.concepts_hit,
        "concepts_missed": result.concepts_missed,
        "attempt_number": attempt_number,
    }
    insert_resp = await asyncio.to_thread(
        lambda: supabase.table("teachback_attempts").insert(row).execute()
    )
    insert_error = getattr(insert_resp, "error", None)
    if insert_error:
        err_str = str(insert_error).lower()
        if "duplicate" in err_str or "unique" in err_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate teach-back attempt detected.",
            )
        safe_err = str(insert_error).replace("\n", " ").replace("\r", " ")
        logger.error(
            "teachback_attempts insert failed: session=%s error=%s",
            session_id,
            safe_err,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist teach-back attempt.",
        )
    logger.info(
        "teachback_attempts inserted: session=%s segment=%s score=%d attempt=%d",
        session_id,
        segment_id,
        result.score,
        attempt_number,
    )

    consent = await get_analytics_consent(user_id=user_id, supabase=supabase)
    capture_event(
        distinct_id=user_id,
        event="assessment_teachback_submitted",
        properties={
            "session_id": session_id,
            "segment_id": segment_id,
            "score": result.score,
            "attempt_number": attempt_number,
        },
        analytics_consent=consent,
    )

    return TeachbackResult(
        session_id=session_id,
        rubric_scores={
            "accuracy": _score_to_label(result.accuracy_score),
            "completeness": _score_to_label(result.completeness_score),
            "clarity": _score_to_label(result.clarity_score),
        },
        overall_score=float(result.score),
        ces_contribution=ces_contribution,
        feedback=feedback,
    )


async def compute_ces_from_session_aggregates(
    session_id: str,
    redis: Any,  # noqa: ANN401
    settings: Any,  # noqa: ANN401
) -> float | None:
    """Return the mean CES over the stored ces_history windows for *session_id*.

    D4 (S3-49): entries are JSON ``{"v": float, "t": int}``.  Pre-D4 bare-float strings
    are accepted via a backward-compat fallback so existing sessions survive deployment.
    Fully corrupt entries (neither JSON nor float) are skipped silently.

    Returns ``None`` when fewer than 5 valid windows exist (insufficient data).
    BOUNDED: lrange reads at most 10 entries (``ltrim`` cap from S3-34).
    """
    history_key = f"session:{session_id}:ces_history"
    # BOUNDED: explicit read cap matches the ltrim cap enforced at write time.
    # Use _CES_HISTORY_MAX-1 as the stop index so this is self-enforced, not
    # dependent solely on the write-side invariant from tutor/service.py.
    from app.modules.tutor.service import _CES_HISTORY_MAX  # noqa: PLC0415

    raw_entries: list[str] = await redis.lrange(history_key, 0, _CES_HISTORY_MAX - 1)

    windows: list[float] = []
    for entry in raw_entries:
        try:
            parsed = json.loads(entry)
            v = float(parsed["v"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            try:
                v = float(entry)  # backward compat: legacy bare float
            except (ValueError, TypeError):
                continue  # skip fully corrupt entry
        windows.append(v)

    if len(windows) < 5:
        return None
    return round(statistics.mean(windows), 2)


def _build_ces_breakdown(
    *,
    quiz_accuracy: float,
    teachback_normalised: float | None,
    behavioral_avg: float,
    head_pose_avg: float,
    blink_avg: float,
    settings: Settings,
) -> dict[str, float]:
    """Compute the per-signal CES contribution breakdown (D2, S3-46).

    Nominal path (teachback_normalised is not None): each signal multiplied by
    its nominal weight × 100.

    Redistributed path (teachback_normalised is None): the teachback weight is
    spread proportionally across the four remaining signals using
    ``remaining = 1.0 - ces_weight_teachback``.  Each other signal's effective
    weight becomes ``nominal / remaining``.  If ``remaining <= 0`` an all-zeros
    dict is returned to avoid divide-by-zero.

    All values are rounded to 4 decimal places.
    """
    if teachback_normalised is not None:
        return {
            "quiz": round(quiz_accuracy * settings.ces_weight_quiz * 100, 4),
            "teachback": round(teachback_normalised * settings.ces_weight_teachback * 100, 4),
            "behavioral": round(behavioral_avg * settings.ces_weight_behavioral * 100, 4),
            "head_pose": round(head_pose_avg * settings.ces_weight_head_pose * 100, 4),
            "blink": round(blink_avg * settings.ces_weight_blink * 100, 4),
        }

    remaining = 1.0 - settings.ces_weight_teachback
    if remaining <= 0.0:
        return {"quiz": 0.0, "teachback": 0.0, "behavioral": 0.0, "head_pose": 0.0, "blink": 0.0}

    return {
        "quiz": round(quiz_accuracy * (settings.ces_weight_quiz / remaining) * 100, 4),
        "teachback": 0.0,
        "behavioral": round(behavioral_avg * (settings.ces_weight_behavioral / remaining) * 100, 4),
        "head_pose": round(head_pose_avg * (settings.ces_weight_head_pose / remaining) * 100, 4),
        "blink": round(blink_avg * (settings.ces_weight_blink / remaining) * 100, 4),
    }


async def get_session_report(
    *,
    session_id: str,
    user_id: str,
    supabase: Client,
    redis: Any = None,  # noqa: ANN401  — S3-42 (D9): optional; enables per-signal breakdowns
) -> SessionReport:
    """Aggregate a completed session's assessment data into a SessionReport.

    Reads from sessions, lessons (tier), quiz_attempts, teachback_attempts,
    and session_events. No LLM calls — pure DB aggregation and arithmetic.

    Args:
        session_id: UUID of the session to report on.
        user_id: User UUID from decoded JWT (for ownership check).
        supabase: Synchronous Supabase client from app.core.db.get_supabase().

    Returns:
        SessionReport with ces_score, ces_breakdown, quiz_score, teachback_score,
        interventions_count, duration_minutes, completed_at, tier context fields.

    Raises:
        HTTPException 404: Session not found.
        HTTPException 404: Session belongs to a different user (SEC-006 — no 403
            to prevent enumeration).
    """
    # lazy import — avoids circular import between service.py and router.py
    from app.modules.assessment.router import SessionReport, TeachbackDetail

    # Step 1 — Validate session ownership and fetch all needed columns in one query
    session_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("sessions")
            .select("session_id, user_id, lesson_id, ces_final, started_at, ended_at")
            .eq("session_id", session_id)
            .maybe_single()
            .execute()
        )
    )
    session_row = single_row(session_resp)
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    db_user_id = session_row.get("user_id")
    if str(db_user_id) != str(user_id):
        # SEC-006: Return 404 (not 403) — identical message prevents enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    row = session_row

    # Step 1b — Fetch lesson tier for contextualised report (Story 3-29)
    _lesson_id = str(row.get("lesson_id") or "")
    tier = "T2"  # safe default — matches lessons.tier DEFAULT 'T2'
    if _lesson_id:
        _tier_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("lessons")
                .select("tier")
                .eq("lesson_id", _lesson_id)
                .maybe_single()
                .execute()
            )
        )
        _tier_row = single_row(_tier_resp)
        if _tier_row and _tier_row.get("tier") in _TIER_LABELS:
            tier = _tier_row["tier"]
    tier_label = _TIER_LABELS[tier]

    # Step 2 — Quiz stats from quiz_attempts
    # BOUNDED: at most 15 segments × 10 questions × 3 retries = 450 rows per session.
    # .limit(500) is a safety ceiling above the natural bound; no quiz session reaches it.
    quiz_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("quiz_attempts")
            .select("is_correct")
            .eq("session_id", session_id)
            .limit(500)
            .execute()
        )
    )
    quiz_rows: list[dict[str, Any]] = rows(quiz_resp)
    total_quiz = len(quiz_rows)
    correct_count = sum(1 for r in quiz_rows if r.get("is_correct") is True)
    quiz_score: float | None = (
        round((correct_count / total_quiz) * 100, 2) if total_quiz > 0 else None
    )
    quiz_accuracy: float = (correct_count / total_quiz) if total_quiz > 0 else 0.0

    # Step 3 — Teachback stats from teachback_attempts
    # BOUNDED: at most one attempt per segment (teach-back has no retry) → max ~15 rows.
    # .limit(50) is a safety ceiling above the natural bound.
    # Story 2-48: widened select to include detail columns; .order("created_at") for ordering.
    tb_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("teachback_attempts")
            .select(
                "segment_id, score, feedback_praise, feedback_correction,"
                " concepts_hit, concepts_missed, attempt_number"
            )
            .eq("session_id", session_id)
            .order("created_at")
            .limit(50)
            .execute()
        )
    )
    tb_rows: list[dict[str, Any]] = rows(tb_resp)
    teachback_count = len(tb_rows)
    if teachback_count > 0:
        sum_scores = sum(r.get("score", 0) or 0 for r in tb_rows)
        avg_teachback: float = sum_scores / teachback_count
        teachback_score: float | None = round(avg_teachback, 2)
        teachback_details: list[TeachbackDetail] | None = [
            TeachbackDetail(
                segment_id=r.get("segment_id", ""),
                score=r.get("score"),
                feedback_praise=r.get("feedback_praise"),
                feedback_correction=r.get("feedback_correction"),
                concepts_hit=r.get("concepts_hit") or [],
                concepts_missed=r.get("concepts_missed") or [],
                attempt_number=r.get("attempt_number", 1),
            )
            for r in tb_rows
        ]
    else:
        avg_teachback = 0.0
        teachback_score = None
        teachback_details = None

    # D17 (S3-47): formula disclosure — determined by teachback presence
    formula_applied = (
        "teachback_redistributed_4_signal" if teachback_score is None else "full_5_signal"
    )
    signal_coverage = 4 if teachback_score is None else 5

    # Step 4 — Interventions count from session_events
    events_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("session_events")
            .select("id", count=cast("Any", "exact"))
            .eq("session_id", session_id)
            .eq("event_type", "intervention_triggered")
            .execute()
        )
    )
    interventions_count: int = events_resp.count or 0

    # Step 4b — S3-05 (Story 2-46): raw intervention rows for the attention timeline chart's
    # vertical markers. BOUNDED: .limit(20) safety ceiling; natural bound is
    # max_distraction_per_session (default 3) + 1 fatigue + a handful of D64-uncapped confusion
    # events. `.order("created_at", desc=True)` makes "the 20 most recent" actually true --
    # without it PostgREST gives no ordering guarantee, so once the natural bound is exceeded
    # (reachable today via D64's uncapped confusion interventions) `.limit(20)` alone could
    # silently keep an arbitrary subset instead of the most recent ones (review finding).
    # Degrades to an empty list (never raises) on a Supabase failure -- this field is optional
    # display data, not worth failing the whole report over, matching the Redis block below.
    # minute-offset math happens later, once `started_at` is available (Step 6); the DESC order
    # is reversed back to chronological (oldest-first) there, matching ces_timeline's convention.
    try:
        intervention_rows_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("session_events")
                .select("created_at, payload")
                .eq("session_id", session_id)
                .eq("event_type", "intervention_triggered")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
        )
        intervention_rows: list[dict[str, Any]] = rows(intervention_rows_resp)
    except Exception:  # noqa: BLE001
        logger.warning("intervention rows fetch failed for session=%s", session_id, exc_info=True)
        intervention_rows = []

    # Step 5 — CES breakdown via D2 helper (proportional redistribution when teachback absent)
    settings = get_settings()
    teachback_normalised = (avg_teachback / 100.0) if teachback_count > 0 else None

    # S3-42 (D9): read per-signal histories from Redis to populate real averages.
    # Graceful fallback to 0.0 when redis is None, key missing, or history empty.
    async def _signal_avg(key: str) -> float:
        if redis is None:
            return 0.0
        try:
            raw_vals: list[str] = await redis.lrange(key, 0, 9)  # BOUNDED: at most 10 entries
            floats = [float(v) for v in raw_vals if v is not None]
            return round(sum(floats) / len(floats), 4) if floats else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    behavioral_avg = await _signal_avg(f"session:{session_id}:behavioral_history")
    head_pose_avg = await _signal_avg(f"session:{session_id}:head_pose_history")
    blink_avg = await _signal_avg(f"session:{session_id}:blink_history")

    ces_breakdown: dict[str, float] = _build_ces_breakdown(
        quiz_accuracy=quiz_accuracy,
        teachback_normalised=teachback_normalised,
        behavioral_avg=behavioral_avg,
        head_pose_avg=head_pose_avg,
        blink_avg=blink_avg,
        settings=settings,
    )

    # Step 6 — Duration and completion timestamp from session timestamps
    raw_started = row.get("started_at")
    raw_ended = row.get("ended_at")

    started_at: datetime | None = None
    ended_at: datetime | None = None

    if isinstance(raw_started, str):
        started_at = datetime.fromisoformat(raw_started.replace("Z", "+00:00"))
    elif isinstance(raw_started, datetime):
        started_at = raw_started

    if isinstance(raw_ended, str):
        ended_at = datetime.fromisoformat(raw_ended.replace("Z", "+00:00"))
    elif isinstance(raw_ended, datetime):
        ended_at = raw_ended

    if ended_at is not None and started_at is not None:
        duration_minutes: float = round((ended_at - started_at).total_seconds() / 60.0, 2)
        completed_at: str | None = ended_at.isoformat()
    else:
        duration_minutes = 0.0
        completed_at = None

    # Step 7 — ces_score from sessions.ces_final (Dev 4 owns this write).
    # None means the session ended before _finalize_session ran (e.g. WebSocket
    # disconnect before lesson_complete was sent); the frontend renders "Not measured"
    # rather than showing 0.0 as "Room to Grow" for a genuinely unfinished session.
    ces_final = row.get("ces_final")
    ces_score: float | None = float(ces_final) if ces_final is not None else None

    # Step 8 — Learner DNA snapshot (descriptive labels + session growth labels)
    _dna_snapshot: dict[str, Any] | None = None
    _dna_select = ", ".join(ALL_NINE_DIMENSIONS)
    _dna_resp = await asyncio.to_thread(
        lambda: (
            supabase.table("learner_dna")
            .select(_dna_select)
            .eq("user_id", str(row["user_id"]))
            .maybe_single()
            .execute()
        )
    )
    _dna_row = single_row(_dna_resp)
    if _dna_row:
        _dim_labels: dict[str, str] = {
            dim: _score_to_label(float(_dna_row.get(dim) or 0.0)) for dim in ALL_NINE_DIMENSIONS
        }

        # Step 9 — session growth events (dna_update) for delta-based growth labels
        # BOUNDED: one dna_update per segment → at most ~15 rows per session.
        # .limit(20) is a safety ceiling above the natural bound.
        _events_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("session_events")
                .select("payload")
                .eq("session_id", session_id)
                .eq("event_type", "dna_update")
                .limit(20)
                .execute()
            )
        )
        _delta_map: dict[str, float | None] = {}
        for evt in rows(_events_resp):
            payload = evt.get("payload")
            if not isinstance(payload, dict):
                continue
            dim = payload.get("dimension")
            if dim in ALL_NINE_DIMENSIONS:
                _delta_map[dim] = payload.get("delta")

        _growth_labels: dict[str, str | None] = {
            dim: _delta_to_growth_label(_delta_map.get(dim)) for dim in ALL_NINE_DIMENSIONS
        }
        _dna_snapshot = {"dimension_labels": _dim_labels, "growth_labels": _growth_labels}

    # S3-50 (D18): ces_history_summary — compact engagement trend from Redis ces_history.
    # BOUNDED: lrange reads at most 10 entries (ltrim cap at write time).
    #
    # S3-05 (Story 2-46) / D109: ces_timeline reuses this SAME read (no second Redis round
    # trip) to also build a chronological [{"minute","ces"}, ...] series for the attention
    # timeline chart. `ces_history` is LPUSH'd (newest-first), so raw order is reversed to get
    # oldest-first. Legacy bare-float entries (no "t") cannot be time-placed and are excluded
    # from ces_timeline, but still counted in ces_history_summary exactly as before this story
    # (AC-2 non-regression). D109: this can never exceed _CES_HISTORY_MAX=10 entries — the last
    # ~50s of the session at default cadence, regardless of session length. The frontend must
    # present this as a recency window, never as full-session coverage.
    #
    # Review finding: a non-finite `v` (a stray "nan"/"inf" string ever written to
    # session:{id}:ces_history) is accepted by float() without raising, then serialized by
    # FastAPI's default JSONResponse as a literal NaN/Infinity token -- invalid per the JSON
    # spec, which breaks the frontend's JSON.parse for the WHOLE report, not just this field.
    # math.isfinite() rejects it at the same point non-finite floats are already rejected
    # elsewhere in this codebase (tutor/service.py's attention-signal parser).
    ces_history_summary: dict[str, Any] | None = None
    ces_timeline: list[dict[str, float]] | None = None
    if redis is not None:
        try:
            raw_history: list[str] = await redis.lrange(f"session:{session_id}:ces_history", 0, 9)
            ces_vals: list[float] = []
            timeline_points: list[dict[str, float]] = []
            started_at_unix = started_at.timestamp() if started_at is not None else None
            for raw in raw_history:
                try:
                    parsed = json.loads(raw)
                    v = float(parsed["v"])
                    if not math.isfinite(v):
                        raise ValueError("non-finite ces value")  # noqa: TRY301
                    ces_vals.append(v)
                    if started_at_unix is not None and "t" in parsed:
                        minute = round((float(parsed["t"]) - started_at_unix) / 60.0, 2)
                        if math.isfinite(minute):
                            timeline_points.append({"minute": minute, "ces": round(v, 2)})
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    try:
                        v = float(raw)
                        if math.isfinite(v):
                            ces_vals.append(v)
                    except (ValueError, TypeError):
                        pass
            if ces_vals:
                ces_history_summary = {
                    "mean": round(sum(ces_vals) / len(ces_vals), 2),
                    "min": round(min(ces_vals), 2),
                    "max": round(max(ces_vals), 2),
                    "window_count": len(ces_vals),
                }
            if timeline_points:
                ces_timeline = list(reversed(timeline_points))
        except Exception:  # noqa: BLE001
            ces_history_summary = None
            ces_timeline = None

    # S3-05 (Story 2-46): intervention_events — minute + type only, computed from the
    # Step 4b raw rows now that `started_at` (Step 6) is available. AC-5: `ces_at_trigger`
    # (present in the raw payload) is never extracted here — enforced at the contract level,
    # not by frontend discipline alone. A malformed row (no created_at) is skipped, not fatal.
    # Step 4b fetches newest-first (`.order("created_at", desc=True)`, so the cap keeps the
    # true most-recent 20) — reversed back to chronological (oldest-first) here, matching
    # ces_timeline's convention.
    intervention_events: list[dict[str, Any]] | None = None
    if intervention_rows and started_at is not None:
        _started_at_unix = started_at.timestamp()
        _computed_events: list[dict[str, Any]] = []
        for _row in reversed(intervention_rows):
            _raw_created = _row.get("created_at")
            if not _raw_created:
                continue
            try:
                _created_dt = (
                    datetime.fromisoformat(_raw_created.replace("Z", "+00:00"))
                    if isinstance(_raw_created, str)
                    else _raw_created
                )
                _minute = round((_created_dt.timestamp() - _started_at_unix) / 60.0, 2)
            except (ValueError, TypeError):
                continue
            _payload = _row.get("payload") or {}
            _itype = _payload.get("intervention_type") if isinstance(_payload, dict) else None
            _computed_events.append({"minute": _minute, "type": _itype or "unknown"})
        if _computed_events:
            intervention_events = _computed_events

    logger.info(
        "session_report built: session=%s quiz_score=%s teachback_score=%s interventions=%d",
        session_id,
        quiz_score,
        teachback_score,
        interventions_count,
    )

    return SessionReport(
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        lesson_id=str(row["lesson_id"]),
        ces_score=ces_score,
        ces_breakdown=ces_breakdown,
        interventions_count=interventions_count,
        quiz_score=quiz_score,
        teachback_score=teachback_score,
        duration_minutes=duration_minutes,
        completed_at=completed_at,
        # Story 3-29 tier-context fields
        tier=tier,
        tier_label=tier_label,
        quiz_total_questions=total_quiz,
        quiz_correct_count=correct_count,
        quiz_accuracy_label=_quiz_accuracy_label(quiz_accuracy, total_quiz),
        # Story 3-30 Learner DNA snapshot
        learner_dna_snapshot=_dna_snapshot,
        # S3-47 formula disclosure
        formula_applied=formula_applied,
        signal_coverage=signal_coverage,
        # S3-50 CES history summary
        ces_history_summary=ces_history_summary,
        # S3-51 intervention messages delivered count
        intervention_messages_used=interventions_count,
        # S3-05 (Story 2-46) attention timeline chart data
        ces_timeline=ces_timeline,
        intervention_events=intervention_events,
        # Story 2-48 per-attempt teachback detail
        teachback_details=teachback_details,
    )


# ── Onboarding scoring ─────────────────────────────────────────────────────────


def _compute_dimension_scores(responses: list[OnboardingAnswer]) -> dict[str, float]:
    """Compute 9 learner_dna sub-dimension scores from 20 onboarding responses.

    Formula per question: normalized = (selected_index / 3) * 100
    Formula per dimension: dim_score = round(mean(normalized_values), 2)

    Returns dict mapping each of the 9 sub-dimension names to a 0-100 float.
    """
    bucket: dict[str, list[float]] = {dim: [] for dim in ALL_NINE_DIMENSIONS}
    for ans in responses:
        subdim = QUESTION_SUBDIMENSION_MAP.get(ans.question_id)
        if subdim is None:
            continue
        # BOUNDED: denominator=3 matches OnboardingAnswer.selected_index le=3
        normalized = (ans.selected_index / 3) * 100
        bucket[subdim].append(normalized)
    return {dim: round(sum(vals) / len(vals), 2) if vals else 0.0 for dim, vals in bucket.items()}


def _compute_badge_labels(scores: dict[str, float]) -> list[str]:
    """Return plain-English badge labels for sub-dimensions scoring >= BADGE_THRESHOLD.

    No IQ/EQ/SQ language — labels come from BADGE_THRESHOLDS (CLAUDE.md rule).
    """
    return [
        BADGE_THRESHOLDS[dim]
        for dim in ALL_NINE_DIMENSIONS
        if scores.get(dim, 0.0) >= BADGE_THRESHOLD
    ]


async def process_onboarding(
    *,
    responses: list[OnboardingAnswer],
    user_id: str,
    supabase: Client,
) -> OnboardingResult:
    """Process 20 onboarding answers: score, upsert learner_dna, generate profile.

    Steps:
    1. Compute 9 sub-dimension scores.
    2. Compute badge labels (scores >= 70).
    3. Bulk-insert rows to onboarding_responses.
    4. Generate GPT-4o-mini profile_text (DPDP disclaimer appended).
    5. Upsert learner_dna with scores, badges, profile_text, and session_count=0.
    6. Return OnboardingResult (no raw scores to frontend).

    The supabase client is synchronous; all DB calls are wrapped in asyncio.to_thread.

    Args:
        responses: 20 validated OnboardingAnswer objects.
        user_id: User UUID from JWT (for DB writes).
        supabase: Synchronous Supabase client from app.core.db.get_supabase().

    Raises:
        HTTPException 409: onboarding_responses insert hits unique constraint
            (duplicate submission).
        HTTPException 500: Non-duplicate DB insert failure.
    """
    # Step 1 — Compute dimension scores
    scores = _compute_dimension_scores(responses)

    # Step 2 — Compute badge labels
    badge_labels = _compute_badge_labels(scores)

    # Step 3 — Bulk-insert onboarding_responses rows
    rows = [
        {
            "user_id": user_id,
            "question_id": ans.question_id,
            "response_value": ans.selected_index,
            "dimension_tag": ans.dimension,
            "response_time_ms": ans.response_time_ms,
        }
        for ans in responses
    ]
    insert_resp = await asyncio.to_thread(
        lambda: supabase.table("onboarding_responses").insert(rows).execute()
    )
    insert_error = getattr(insert_resp, "error", None)
    if insert_error:
        err_str = str(insert_error).lower()
        if "duplicate" in err_str or "unique" in err_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Onboarding already submitted — duplicate responses detected.",
            )
        safe_err = str(insert_error).replace("\n", " ").replace("\r", " ")
        logger.error(
            "onboarding_responses insert failed: user=%s error=%s",
            user_id,
            safe_err,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist onboarding responses.",
        )

    # Step 4 — Generate profile_text via GPT-4o-mini (must precede upsert so it is persisted)
    # D71: provider.complete() already has @with_retry(max_attempts=3) for transient 429/5xx.
    # If all retries fail the raw exception must be caught here: convert to HTTPException(503)
    # so the router's `except HTTPException` cleanup fires and releases the Redis lock.
    # Before raising we also delete the Step 3 rows so a retry can re-insert cleanly.
    provider = OpenAILLMProvider(lesson_id="onboarding")
    try:
        profile_text = await generate_onboarding_profile(
            badge_labels=badge_labels,
            provider=provider,
        )
    except Exception:  # noqa: BLE001
        logger.exception("onboarding: generate_onboarding_profile failed for user=%s", user_id)
        _question_ids = [r["question_id"] for r in rows]
        if _question_ids:  # supabase-py drops IN([]) filter for empty list in some versions
            try:
                del_resp = await asyncio.to_thread(
                    lambda: (
                        supabase.table("onboarding_responses")
                        .delete()
                        .eq("user_id", user_id)
                        .in_("question_id", _question_ids)
                        .execute()
                    )
                )
                # supabase signals errors via resp.error, not exceptions
                _del_resp_error = getattr(del_resp, "error", None)
                if _del_resp_error:
                    logger.warning(
                        "onboarding: rollback of onboarding_responses failed user=%s error=%s — "
                        "user may need manual cleanup to retry",
                        user_id,
                        str(_del_resp_error).replace("\n", " "),
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "onboarding: rollback of onboarding_responses failed user=%s "
                    "(network/client error) — user may need manual cleanup to retry",
                    user_id,
                )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile generation temporarily unavailable — please retry.",
        ) from None

    # Step 5 — Upsert learner_dna (includes profile_text so the DB row is complete)
    dna_row: dict[str, Any] = {
        "user_id": user_id,
        "badge_labels": badge_labels,
        "session_count": 0,
        "profile_text": profile_text,
        **scores,
    }
    upsert_resp = await asyncio.to_thread(
        lambda: supabase.table("learner_dna").upsert(dna_row, on_conflict="user_id").execute()
    )
    upsert_error = getattr(upsert_resp, "error", None)
    if upsert_error:
        safe_upsert_err = str(upsert_error).replace("\n", " ").replace("\r", " ")
        logger.error(
            "learner_dna upsert failed: user=%s error=%s",
            user_id,
            safe_upsert_err,
        )
        # D71 variant: Step 5 failure also orphans Step 3 rows — roll back so retry can re-insert.
        _question_ids = [r["question_id"] for r in rows]
        if _question_ids:
            try:
                del_resp5 = await asyncio.to_thread(
                    lambda: (
                        supabase.table("onboarding_responses")
                        .delete()
                        .eq("user_id", user_id)
                        .in_("question_id", _question_ids)
                        .execute()
                    )
                )
                _del_resp5_error = getattr(del_resp5, "error", None)
                if _del_resp5_error:
                    logger.warning(
                        "onboarding: step5 rollback of onboarding_responses failed "
                        "user=%s error=%s",
                        user_id,
                        str(_del_resp5_error).replace("\n", " "),
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "onboarding: step5 rollback of onboarding_responses failed "
                    "user=%s (network error)",
                    user_id,
                )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist learner profile.",
        )

    consent = await get_analytics_consent(user_id=user_id, supabase=supabase)
    capture_event(
        distinct_id=user_id,
        event="assessment_onboarding_completed",
        properties={
            "session_count": dna_row["session_count"]
        },  # IMP-004: reads value written to DB
        analytics_consent=consent,
    )

    return OnboardingResult(
        badge_labels=badge_labels,
        profile_text=profile_text,
        session_count=0,
    )


async def record_consent(
    *,
    user_id: str,
    consent_type: str,
    policy_version: str,
    supabase: Client,
) -> tuple[dict[str, Any], bool]:
    """Record a DPDP consent event in the user_consents audit table.

    Returns (record_dict, is_new):
        is_new=True  → a new row was inserted; caller should return HTTP 201.
        is_new=False → an identical row already exists; caller should return HTTP 200.

    NEVER updates users.attention_consent — the DB trigger
    user_consents_sync_attention (migration 20260702000000_dpdp_user_consents.sql)
    sets that boolean AFTER INSERT when consent_type='attention_tracking'.

    TOCTOU safety: INSERT is attempted first. If the UNIQUE constraint added by
    migration 20260805000000_user_consents_unique_constraint.sql fires (PostgreSQL
    error code 23505), we fall back to SELECT. This makes idempotency atomic — a
    SELECT-then-INSERT pattern would allow two concurrent requests to both pass the
    SELECT check and both INSERT, producing duplicate rows.

    Args:
        user_id:        JWT sub — never accepted from request body.
        consent_type:   'attention_tracking' or 'learner_dna'.
        policy_version: Non-empty version string (e.g. 'v1').
        supabase:       Synchronous Supabase client; all calls wrapped in asyncio.to_thread.

    Raises:
        HTTPException 500: INSERT failed with a non-duplicate error, or returned no rows.
    """
    _safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")
    _safe_type = str(consent_type).replace("\n", " ").replace("\r", " ")

    # Step 1 — Attempt INSERT first (atomically correct under UNIQUE constraint).
    # user_id comes from JWT; id/consented_at/created_at are DB-generated.
    # NEVER include users.attention_consent here — the trigger owns that write.
    insert_payload: dict[str, Any] = {
        "user_id": user_id,
        "consent_type": consent_type,
        "policy_version": policy_version,
    }
    insert_resp = await asyncio.to_thread(
        lambda: supabase.table("user_consents").insert(insert_payload).execute()
    )
    insert_error = getattr(insert_resp, "error", None)

    if insert_error:
        err_str = str(insert_error).lower()
        # PostgreSQL unique violation: code 23505, message contains "duplicate key"
        if "duplicate" in err_str or "unique" in err_str or "23505" in err_str:
            # Idempotent path — row exists; fetch and return it.
            existing_resp = await asyncio.to_thread(
                lambda: (
                    supabase.table("user_consents")
                    .select("id, user_id, consent_type, policy_version, consented_at")
                    .eq("user_id", user_id)
                    .eq("consent_type", consent_type)
                    .eq("policy_version", policy_version)
                    .limit(1)
                    .execute()
                )
            )
            existing_rows: list[dict[str, Any]] = getattr(existing_resp, "data", None) or []
            if existing_rows:
                return existing_rows[0], False
            # Unique constraint fired but the row is gone — should not happen.
            logger.error(
                "user_consents unique conflict but row not found: user=%s consent_type=%s",
                _safe_uid,
                _safe_type,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to record consent — conflict but row not found.",
            )

        logger.error(
            "user_consents insert failed: user=%s consent_type=%s error=%s",
            _safe_uid,
            _safe_type,
            str(insert_error).replace("\n", " ").replace("\r", " "),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record consent.",
        )

    created_rows: list[dict[str, Any]] = getattr(insert_resp, "data", None) or []
    if not created_rows:
        logger.error(
            "user_consents insert returned no rows: user=%s consent_type=%s",
            _safe_uid,
            _safe_type,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record consent — empty response from database.",
        )

    return created_rows[0], True


async def get_learner_dna_data(
    *,
    user_id: str,
    supabase: Client,
    redis: Any = None,  # noqa: ANN401
) -> dict[str, Any]:
    """Fetch the learner_dna row for a user and return it as a plain dict.

    Returns a dict compatible with the LearnerDNA response model in router.py.
    Returns a zero-state dict if no learner_dna row exists yet (user not onboarded).

    Args:
        user_id:  User UUID from the decoded JWT.
        supabase: Synchronous Supabase client.
        redis:    Optional async Redis client. When provided, checks
                  user:{user_id}:reassessment_due for the re-assessment flag.
                  Non-fatal: Redis failures return False for reassessment_due.

    Raises:
        HTTPException 404: No learner_dna row found for this user.
    """
    resp = await asyncio.to_thread(
        lambda: (
            supabase.table("learner_dna")
            .select("user_id, badge_labels, profile_text, session_count, last_updated")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    )
    # CROSS-TEAM NOTE (2026-07-13, flagged to Dev 3 — this module's owner): the
    # Supabase client's .maybe_single().execute() returns None directly (not a
    # response object with .data = None) when zero rows match — the original
    # `resp.data is None` check crashed with AttributeError for exactly the
    # expected "not onboarded yet" case, 500ing instead of the intended 404.
    row = single_row(resp)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learner DNA profile not found. Complete the onboarding diagnostic first.",
        )

    # ── Re-assessment flag (non-fatal Redis read) ─────────────────────────────
    reassessment_due: bool = False
    if redis is not None:
        _safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")
        try:
            val = await redis.get(f"user:{user_id}:reassessment_due")
            reassessment_due = val == "1"
        except Exception as exc:
            logger.warning("get_learner_dna_data: redis check failed user=%s: %s", _safe_uid, exc)
            reassessment_due = False

    return {
        "user_id": str(row["user_id"]),
        "badge_labels": row.get("badge_labels") or [],
        "profile_text": row.get("profile_text"),
        "session_count": int(row.get("session_count") or 0),
        "reassessment_due": reassessment_due,
        "last_updated": row.get("last_updated"),
    }


# ── S3-36 (D12) — Intervention event persistence ──────────────────────────────


async def write_intervention_event(
    session_id: str,
    *,
    intervention_type: str,
    window_index: int,
    ces_at_trigger: float,
    message_key: str | None,
    supabase: Any,  # noqa: ANN401
) -> None:
    """Write an intervention_triggered event to session_events (fire-and-forget).

    Called via asyncio.create_task from the tutor intervening_node (D12).
    DB failures are logged at ERROR and captured to Sentry — never re-raised,
    so a DB outage cannot block the intervention dispatch path.
    """
    try:
        row = {
            "session_id": session_id,
            "event_type": "intervention_triggered",
            "payload": {
                "intervention_type": intervention_type,
                "window_index": window_index,
                "ces_at_trigger": ces_at_trigger,
                "message_key": message_key,
            },
        }
        await asyncio.to_thread(lambda: supabase.table("session_events").insert(row).execute())
    except Exception as exc:  # noqa: BLE001
        _safe_sid = str(session_id).replace("\n", " ").replace("\r", " ")
        logger.error(
            "write_intervention_event failed session=%s type=%s: %s",
            _safe_sid,
            intervention_type,
            exc,
        )
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.capture_exception(exc)


# D63 (S3-53): _get_distraction_count was removed — it was dead code.
# frustration_tolerance in dna_fusion.py correctly reads intervention counts
# from event_counts["intervention_triggered"] (session_events DB) at session end.
