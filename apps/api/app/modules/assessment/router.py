"""
Assessment module router.

Handles quiz submission, teach-back evaluation, session reports,
learner DNA retrieval, and onboarding diagnostic submission.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUser

router = APIRouter(tags=["assessment"])


# ── Request / Response models ─────────────────────────────────────────────────


class QuizSubmission(BaseModel):
    session_id: str
    lesson_id: str
    answers: list[dict[str, Any]] = Field(
        description="List of {question_id, selected_option} objects"
    )


class QuizResult(BaseModel):
    session_id: str
    score: float
    correct_count: int
    total_count: int
    ces_contribution: float
    feedback: list[dict[str, Any]]


class TeachbackSubmission(BaseModel):
    session_id: str
    lesson_id: str
    transcript: str = Field(description="STT transcript of the student's teach-back")
    duration_seconds: float


class TeachbackResult(BaseModel):
    session_id: str
    rubric_scores: dict[str, float]
    overall_score: float
    ces_contribution: float
    feedback: str


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
    strengths: list[str]
    growth_areas: list[str]
    preferred_learning_style: str | None
    avg_ces_score: float | None
    sessions_completed: int
    last_updated: str | None


class OnboardingDiagnosticSubmission(BaseModel):
    answers: list[dict[str, Any]] = Field(
        description="Onboarding diagnostic question answers"
    )
    subject: str
    grade_level: str


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
    """Grade a quiz submission and update the session's CES score.

    TODO (Sprint 2): Delegate to assessment service.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


@router.post(
    "/teachback",
    response_model=TeachbackResult,
    summary="Submit a teach-back transcript for LLM evaluation",
)
async def submit_teachback(
    body: TeachbackSubmission,
    current_user: CurrentUser,
) -> TeachbackResult:
    """Evaluate a teach-back transcript using the LLM rubric.

    TODO (Sprint 2): Delegate to assessment service.
    """
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented yet")


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
