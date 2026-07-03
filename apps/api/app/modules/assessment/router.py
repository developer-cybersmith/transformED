"""
Assessment module router.

Handles quiz submission, teach-back evaluation, session reports,
learner DNA retrieval, and onboarding diagnostic submission.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel  # SessionReport, LearnerDNA still use BaseModel directly

from app.dependencies import CurrentUser

# All request/response models live in schemas.py so service.py can import them
# without creating a circular import (service ← router ← service).
from app.modules.assessment.schemas import (
    OnboardingDiagnosticSubmission,
    OnboardingResult,
    QuizAnswer,
    QuizResult,
    QuizSubmission,
    TeachbackResult,
    TeachbackSubmission,
)

router = APIRouter(tags=["assessment"])

# Re-export for backward compatibility — tests and other modules import from here.
__all__ = ["QuizAnswer", "QuizSubmission", "QuizResult", "TeachbackSubmission", "TeachbackResult"]


class SessionReport(BaseModel):
    session_id: str
    user_id: str
    lesson_id: str
    ces_score: float
    ces_breakdown: dict[str, float]
    interventions_count: int
    quiz_score: float | None
    teachback_score: float | None
    duration_minutes: float
    completed_at: str | None


class LearnerDNA(BaseModel):
    user_id: str
    badge_labels: list[str]
    # DPDP Act 2023 (Sprint 2): profile_text MUST end with the statutory disclaimer
    # before this field is returned to the client. Never truncate or omit the disclaimer.
    # See CLAUDE.md §dev-rules and prompts.py when implementing get_learner_dna().
    profile_text: str | None
    session_count: int
    reassessment_due: bool = False
    last_updated: str | None


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/quiz",
    response_model=QuizResult,
    summary="Submit quiz answers for a session",
)
async def submit_quiz(
    body: QuizSubmission,
    current_user: CurrentUser,
) -> QuizResult:
    """Grade a quiz submission and update the session's CES score."""
    from app.core.db import get_supabase  # lazy — prevents circular import at module load
    from app.modules.assessment.service import grade_quiz
    return await grade_quiz(
        session_id=body.session_id,
        lesson_id=body.lesson_id,
        segment_id=body.segment_id,
        answers=body.answers,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )


@router.post(
    "/teachback",
    response_model=TeachbackResult,
    summary="Submit a typed teach-back response for LLM evaluation",
)
async def submit_teachback(
    body: TeachbackSubmission,
    current_user: CurrentUser,
) -> TeachbackResult:
    """Evaluate a student's typed teach-back response using the GPT-4o-mini rubric."""
    from app.core.db import get_supabase  # lazy — prevents circular import at module load
    from app.modules.assessment.service import grade_teachback
    return await grade_teachback(
        session_id=body.session_id,
        lesson_id=body.lesson_id,
        segment_id=body.segment_id,
        response_text=body.response_text,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )


@router.get(
    "/session/{session_id}/report",
    response_model=SessionReport,
    summary="Get the complete assessment report for a session",
)
async def get_session_report_endpoint(
    session_id: str,
    current_user: CurrentUser,
) -> SessionReport:
    """Return the final CES breakdown and scores for a completed session."""
    from app.core.db import get_supabase  # lazy — prevents circular import at module load
    from app.core.posthog_client import capture_event
    from app.modules.assessment.service import get_session_report

    result = await get_session_report(
        session_id=session_id,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )
    capture_event(
        distinct_id=current_user["sub"],
        event="assessment_session_report_viewed",
        properties={"session_id": session_id},
    )
    return result


@router.get(
    "/user/dna",
    response_model=LearnerDNA,
    summary="Get the learner DNA profile for the current user",
)
async def get_learner_dna(
    current_user: CurrentUser,
) -> LearnerDNA:
    """Return the learner DNA profile for the authenticated user."""
    from app.core.db import get_supabase  # lazy — prevents circular import at module load
    from app.core.posthog_client import capture_event
    from app.modules.assessment.service import get_learner_dna_data

    user_id: str = current_user["sub"]
    body = await get_learner_dna_data(user_id=user_id, supabase=get_supabase())
    capture_event(
        distinct_id=user_id,
        event="assessment_dna_viewed",
        properties={"session_count": body.get("session_count", 0)},
    )
    return LearnerDNA(**body)


@router.post(
    "/onboarding/submit",
    response_model=OnboardingResult,
    status_code=status.HTTP_201_CREATED,
    summary="Submit onboarding diagnostic answers and generate learner DNA",
)
async def submit_onboarding_diagnostic(
    body: OnboardingDiagnosticSubmission,
    current_user: CurrentUser,
) -> OnboardingResult:
    """Process 20 onboarding diagnostic answers and generate initial learner DNA profile.

    Idempotency: returns 409 if the Redis key user:{id}:onboarding_done is already set.
    On success, sets the Redis key and returns OnboardingResult with badge_labels,
    profile_text (with DPDP Act 2023 disclaimer), and session_count=0.
    """
    from app.core.db import get_supabase
    from app.core.redis import get_redis
    from app.modules.assessment.service import process_onboarding

    user_id: str = current_user["sub"]
    onboarding_key = f"user:{user_id}:onboarding_done"

    # Atomic SET NX eliminates the TOCTOU race between a read-check and a later write.
    # Returns True if key was newly set; None/False if key already existed.
    redis = get_redis()
    was_set = await redis.set(onboarding_key, "1", nx=True)
    if not was_set:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding diagnostic has already been submitted for this account.",
        )

    try:
        result = await process_onboarding(
            responses=body.responses,
            user_id=user_id,
            supabase=get_supabase(),
        )
    except HTTPException:
        # Release the lock so the user can retry after a transient failure.
        await redis.delete(onboarding_key)
        raise
    return result
