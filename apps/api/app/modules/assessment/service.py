"""
Assessment service layer — quiz grading business logic.

Sprint 1: grade_quiz() only. Teach-back scoring is added in the next story.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException, status

from app.config import get_settings
from app.modules.assessment.router import QuizAnswer, QuizResult

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
        HTTPException 404: Session not found, lesson not found, or segment not found.
        HTTPException 403: Session belongs to a different user.
        HTTPException 422: A submitted question_id is not in the segment quiz.
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
    if session_resp.data["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session does not belong to this user.",
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

    # Step 5 — Grade each answer
    graded: list[dict[str, Any]] = []
    for ans in answers:
        question = question_map.get(ans.question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"question_id {ans.question_id!r} not found in segment "
                    f"{segment_id!r}. Valid IDs: {list(question_map.keys())}."
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

    # Step 6 — Bulk insert to quiz_attempts
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
    await asyncio.to_thread(
        lambda: supabase.table("quiz_attempts").insert(rows_to_insert).execute()
    )
    logger.info(
        "quiz_attempts inserted: session=%s segment=%s count=%d",
        session_id,
        segment_id,
        len(rows_to_insert),
    )

    # Step 7 — Compute aggregate metrics
    correct_count = sum(1 for g in graded if g["is_correct"])
    total_count = len(graded)
    quiz_accuracy: float = correct_count / total_count if total_count > 0 else 0.0

    settings = get_settings()
    ces_contribution: float = quiz_accuracy * settings.ces_weight_quiz

    # Step 8 — Build per-question feedback
    feedback: list[dict[str, Any]] = [
        {
            "question_id": g["question"]["question_id"],
            "question": g["question"]["question"],
            "is_correct": g["is_correct"],
            "correct_index": g["question"]["correct_index"],
            "correct_option": g["question"]["options"][g["question"]["correct_index"]],
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
