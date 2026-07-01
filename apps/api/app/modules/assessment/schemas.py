"""
Assessment module Pydantic schemas.

Shared between router.py (request/response binding) and service.py (business logic).
Neither imports the other — both import from here to avoid circular imports.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["QuizAnswer", "QuizSubmission", "QuizResult", "TeachbackSubmission", "TeachbackResult"]


class QuizAnswer(BaseModel):
    question_id: str
    response_index: int = Field(ge=0)
    response_time_ms: int = Field(default=0, ge=0)


class QuizSubmission(BaseModel):
    session_id: str
    lesson_id: str
    segment_id: str
    answers: list[QuizAnswer]


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
    response_text: str = Field(description="Student's typed teach-back response")


class TeachbackResult(BaseModel):
    session_id: str
    rubric_scores: dict[str, float]  # {"accuracy": float, "completeness": float, "clarity": float}
    overall_score: float
    ces_contribution: float
    feedback: str  # praise only (score >= 90) or praise + "\n\n" + correction (score < 90)
