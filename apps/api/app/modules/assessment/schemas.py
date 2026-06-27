"""
Assessment module Pydantic schemas.

Shared between router.py (request/response binding) and service.py (business logic).
Neither imports the other — both import from here to avoid circular imports.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class QuizAnswer(BaseModel):
    question_id: str
    response_index: int
    response_time_ms: int = 0


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
