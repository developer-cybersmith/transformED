"""
Assessment module Pydantic schemas.

Shared between router.py (request/response binding) and service.py (business logic).
Neither imports the other — both import from here to avoid circular imports.
"""
from __future__ import annotations

from typing import Any

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "QuizAnswer", "QuizSubmission", "QuizResult",
    "TeachbackSubmission", "TeachbackResult",
    "OnboardingAnswer", "OnboardingDiagnosticSubmission", "OnboardingResult",
]


class QuizAnswer(BaseModel):
    question_id: str
    response_index: int = Field(ge=0)
    response_time_ms: int = Field(default=0, ge=0)


class QuizSubmission(BaseModel):
    session_id: str
    lesson_id: str
    segment_id: str
    answers: list[QuizAnswer] = Field(min_length=1, max_length=50)


class QuizResult(BaseModel):
    session_id: str
    score: float
    correct_count: int
    total_count: int
    ces_contribution: float
    feedback: list[dict[str, Any]]


# ── Teachback schemas ──────────────────────────────────────────────────────────
# Frozen contract (Sprint 1) — shape changes require 4-dev PR review.
# NO transcript field (STT banned). NO duration_seconds field (implies timer).

class TeachbackSubmission(BaseModel):
    session_id: str
    lesson_id: str
    segment_id: str
    response_text: str = Field(min_length=1, max_length=4000, description="Student's typed teach-back response")


class TeachbackResult(BaseModel):
    session_id: str
    # B5 (Story 3-14): Changed from dict[str, float] to dict[str, str] — descriptive labels only.
    # Raw numeric sub-scores are never returned to students (CLAUDE.md Learner DNA display rules).
    # Authorised breaking-change exception: documented in Story 3-14 5-agent review.
    rubric_scores: dict[str, str]  # {"accuracy": label, "completeness": label, "clarity": label}
    overall_score: float
    ces_contribution: float
    feedback: str  # praise only (score >= 90) or praise + "\n\n" + correction (score < 90)


# ── Onboarding schemas ─────────────────────────────────────────────────────────
# Frozen contract (Sprint 2, Story 3-18) — shape changes require 4-dev PR review.
# No raw numeric dimension scores in OnboardingResult (CLAUDE.md Learner DNA rules).

class OnboardingAnswer(BaseModel):
    question_id: str
    dimension: Literal["cognitive", "emotional", "self_direction"]
    selected_index: int = Field(ge=0, le=3)
    selected_text: str
    response_time_ms: int | None = Field(default=None, ge=0)


class OnboardingDiagnosticSubmission(BaseModel):
    responses: list[OnboardingAnswer] = Field(min_length=20, max_length=20)


class OnboardingResult(BaseModel):
    badge_labels: list[str]
    profile_text: str
    session_count: int
