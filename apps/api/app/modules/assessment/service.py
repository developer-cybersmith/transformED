"""
Assessment service layer — quiz grading, teach-back scoring, and session report business logic.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from app.config import get_settings
from app.modules.assessment.prompts import score_teachback
from app.modules.assessment.schemas import QuizAnswer, QuizResult, TeachbackResult
from app.providers.llm.openai import OpenAILLMProvider

logger = logging.getLogger(__name__)


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


async def grade_quiz(
    *,
    session_id: str,
    lesson_id: str,
    segment_id: str,
    answers: list[QuizAnswer],
    user_id: str,
    supabase: Any,
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
        HTTPException 403: Session belongs to a different user, or session.lesson_id != lesson_id (IDOR guard).
        HTTPException 409: Duplicate quiz attempt detected (unique constraint).
        HTTPException 422: answers is empty, or a submitted question_id is not in the segment quiz.
        HTTPException 500: quiz_attempts insert fails for a non-duplicate reason.
    """
    # Step 1 — Validate session ownership
    session_resp = await asyncio.to_thread(
        lambda: supabase.table("sessions")
        .select("session_id, user_id, lesson_id")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    if session_resp.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found.",
        )
    if str(session_resp.data["user_id"]) != str(user_id):
        # SEC-006: Return 404 to prevent session enumeration oracle.
        # Attacker must not distinguish "belongs to someone else" from "doesn't exist".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied.",
        )
    # IDOR guard — session must belong to the requested lesson
    if str(session_resp.data.get("lesson_id", "")) != str(lesson_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this lesson.",
        )

    # Step 2 — Load lesson JSONB
    lesson_resp = await asyncio.to_thread(
        lambda: supabase.table("lessons")
        .select("content")
        .eq("lesson_id", lesson_id)
        .maybe_single()
        .execute()
    )
    if lesson_resp.data is None or lesson_resp.data.get("content") is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lesson {lesson_id!r} not found or has no generated content.",
        )

    content: dict[str, Any] = lesson_resp.data["content"]
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
        lambda: supabase.table("quiz_attempts")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .eq("segment_id", segment_id)
        .execute()
    )
    attempt_number: int = (count_resp.count or 0) + 1

    # Step 7 — Grade each answer
    graded: list[dict[str, Any]] = []
    for ans in answers:
        question = question_map.get(ans.question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"question_id {ans.question_id!r} not found in segment "
                    f"{segment_id!r}."
                ),
            )
        # SEC-008: Validate response_index is within valid option range
        options = question.get("options", [])
        if not (0 <= ans.response_index < len(options)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"response_index {ans.response_index} is out of range for question {ans.question_id!r}.",
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
        safe_err = str(insert_error).replace('\n', ' ').replace('\r', ' ')
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
    supabase: Any,
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
        lambda: supabase.table("sessions")
        .select("session_id, user_id, lesson_id")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    if session_resp.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found.",
        )
    if str(session_resp.data["user_id"]) != str(user_id):
        # SEC-006: Return 404 to prevent session enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or access denied.",
        )
    # IDOR guard — session must belong to the requested lesson
    if str(session_resp.data.get("lesson_id", "")) != str(lesson_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this lesson.",
        )

    # Step 2 — Load lesson JSONB
    lesson_resp = await asyncio.to_thread(
        lambda: supabase.table("lessons")
        .select("content")
        .eq("lesson_id", lesson_id)
        .maybe_single()
        .execute()
    )
    if lesson_resp.data is None or lesson_resp.data.get("content") is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lesson {lesson_id!r} not found or has no generated content.",
        )

    content: dict[str, Any] = lesson_resp.data["content"]
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
        lambda: supabase.table("teachback_attempts")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .eq("segment_id", segment_id)
        .execute()
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
        )
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
        result.praise
        if not result.correction
        else f"{result.praise}\n\n{result.correction}"
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
        safe_err = str(insert_error).replace('\n', ' ').replace('\r', ' ')
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


async def get_session_report(
    *,
    session_id: str,
    user_id: str,
    supabase: Any,
) -> Any:
    """Aggregate a completed session's assessment data into a SessionReport.

    Reads from sessions, quiz_attempts, teachback_attempts, and session_events.
    No LLM calls — pure DB aggregation and arithmetic.

    Args:
        session_id: UUID of the session to report on.
        user_id: User UUID from decoded JWT (for ownership check).
        supabase: Synchronous Supabase client from app.core.db.get_supabase().

    Returns:
        SessionReport with ces_score, ces_breakdown, quiz_score, teachback_score,
        interventions_count, duration_minutes, completed_at.

    Raises:
        HTTPException 404: Session not found.
        HTTPException 404: Session belongs to a different user (SEC-006 — no 403 to prevent enumeration).
    """
    from app.modules.assessment.router import SessionReport  # lazy — avoids circular import

    # Step 1 — Validate session ownership and fetch all needed columns in one query
    session_resp = await asyncio.to_thread(
        lambda: supabase.table("sessions")
        .select("session_id, user_id, lesson_id, ces_final, started_at, ended_at")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    if session_resp.data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )
    db_user_id = session_resp.data.get("user_id")
    if str(db_user_id) != str(user_id):
        # SEC-006: Return 404 (not 403) — identical message prevents enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    row = session_resp.data

    # Step 2 — Quiz stats from quiz_attempts
    quiz_resp = await asyncio.to_thread(
        lambda: supabase.table("quiz_attempts")
        .select("is_correct")
        .eq("session_id", session_id)
        .execute()
    )
    quiz_rows: list[dict[str, Any]] = quiz_resp.data or []
    total_quiz = len(quiz_rows)
    correct_count = sum(1 for r in quiz_rows if r.get("is_correct") is True)
    quiz_score: float | None = round((correct_count / total_quiz) * 100, 2) if total_quiz > 0 else None
    quiz_accuracy: float = (correct_count / total_quiz) if total_quiz > 0 else 0.0

    # Step 3 — Teachback stats from teachback_attempts
    tb_resp = await asyncio.to_thread(
        lambda: supabase.table("teachback_attempts")
        .select("score")
        .eq("session_id", session_id)
        .execute()
    )
    tb_rows: list[dict[str, Any]] = tb_resp.data or []
    teachback_count = len(tb_rows)
    if teachback_count > 0:
        sum_scores = sum(r.get("score", 0) or 0 for r in tb_rows)
        avg_teachback: float = sum_scores / teachback_count
        teachback_score: float | None = round(avg_teachback, 2)
    else:
        avg_teachback = 0.0
        teachback_score = None

    # Step 4 — Interventions count from session_events
    events_resp = await asyncio.to_thread(
        lambda: supabase.table("session_events")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .eq("event_type", "intervention_triggered")
        .execute()
    )
    interventions_count: int = events_resp.count or 0

    # Step 5 — CES breakdown arithmetic
    settings = get_settings()
    quiz_contribution = round(quiz_accuracy * settings.ces_weight_quiz * 100, 4)
    teachback_contribution = round((avg_teachback / 100.0) * settings.ces_weight_teachback * 100, 4)
    ces_breakdown: dict[str, float] = {
        "quiz": quiz_contribution,
        "teachback": teachback_contribution,
        # Sprint 2: behavioral/head_pose/blink contributions deferred to Phase 3
        "behavioral": 0.0,
        "head_pose": 0.0,
        "blink": 0.0,
    }

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

    # Step 7 — ces_score from sessions.ces_final (Dev 4 owns this write)
    ces_final = row.get("ces_final")
    ces_score: float = float(ces_final) if ces_final is not None else 0.0

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
    )
