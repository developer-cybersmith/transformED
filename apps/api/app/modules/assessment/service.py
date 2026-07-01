"""
Assessment service layer — quiz grading and teach-back scoring business logic.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException, status

from app.config import get_settings
from app.modules.assessment.prompts import score_teachback
from app.modules.assessment.schemas import QuizAnswer, QuizResult, TeachbackResult
from app.providers.llm.openai import OpenAILLMProvider

logger = logging.getLogger(__name__)


async def grade_quiz(
    *,
    session_id: str,
    lesson_id: str,
    segment_id: str,
    answers: list[QuizAnswer],
    attempt_number: int = 1,
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
        attempt_number: 1 for first attempt, 2 for retry. Defaults to 1.
        user_id: User UUID from the decoded JWT (for ownership check).
        supabase: Synchronous Supabase client from app.core.db.get_supabase().

    Returns:
        QuizResult with score, ces_contribution, and per-question feedback.

    Raises:
        HTTPException 404: Session not found, lesson not found, segment not found,
            or ownership check failed (SEC-006: enumeration oracle fix).
        HTTPException 403: session.lesson_id != lesson_id (IDOR guard).
        HTTPException 422: answers is empty, or a submitted question_id is not in the segment quiz.
        HTTPException 500: quiz_attempts insert returns a truthy error.
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

    # Step 6 — Grade each answer
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
        graded.append(
            {
                "question": question,
                "is_correct": ans.response_index == question["correct_index"],
                "selected_index": ans.response_index,
                "response_time_ms": ans.response_time_ms,
            }
        )

    # Step 7 — Bulk insert to quiz_attempts
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
    if getattr(insert_resp, "error", None):
        logger.error(
            "quiz_attempts insert failed: session=%s error=%s",
            session_id,
            insert_resp.error,
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

    # Step 8 — Compute aggregate metrics
    correct_count = sum(1 for g in graded if g["is_correct"])
    total_count = len(graded)
    quiz_accuracy: float = correct_count / total_count if total_count > 0 else 0.0

    settings = get_settings()
    ces_contribution: float = round(quiz_accuracy * settings.ces_weight_quiz * 100, 4)

    # Step 9 — Build per-question feedback
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
        HTTPException 403: Session belongs to a different user or to a different lesson (IDOR).
        HTTPException 500: DB insert failed.
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this user.",
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
    result = await score_teachback(
        topic=topic,
        key_concepts=key_concepts,
        response_text=response_text,
        provider=provider,
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
    if getattr(insert_resp, "error", None):
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
            "accuracy": float(result.accuracy_score),
            "completeness": float(result.completeness_score),
            "clarity": float(result.clarity_score),
        },
        overall_score=float(result.score),
        ces_contribution=ces_contribution,
        feedback=feedback,
    )
