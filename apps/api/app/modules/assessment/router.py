"""
Assessment module router.

Handles quiz submission, teach-back evaluation, session reports,
learner DNA retrieval, and onboarding diagnostic submission.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.dependencies import CurrentUser

# All request/response models live in schemas.py so service.py can import them
# without creating a circular import (service ← router ← service).
from app.modules.assessment.schemas import (
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


class OnboardingAnswer(BaseModel):
    question_id: str
    dimension: str
    selected_index: int
    selected_text: str


class OnboardingDiagnosticSubmission(BaseModel):
    responses: list[OnboardingAnswer]


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
async def get_session_report(
    session_id: str,
    current_user: CurrentUser,
) -> SessionReport:
    """Return the final CES breakdown and scores for a completed session.

    TODO (Sprint 2): Query session_reports table.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.get(
    "/user/dna",
    response_model=LearnerDNA,
    summary="Get the learner DNA profile for the current user",
)
async def get_learner_dna(
    current_user: CurrentUser,
) -> LearnerDNA:
    """Return aggregated learning patterns for the authenticated user.

    TODO (Sprint 2): Aggregate from session_reports.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post(
    "/onboarding/submit",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit onboarding diagnostic answers",
)
async def submit_onboarding_diagnostic(
    body: OnboardingDiagnosticSubmission,
    current_user: CurrentUser,
) -> dict[str, str]:
    """Process onboarding diagnostic and generate initial learner DNA.

    TODO (Sprint 1): Delegate to assessment service.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")
