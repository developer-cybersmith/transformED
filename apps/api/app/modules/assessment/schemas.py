"""
Assessment module Pydantic schemas.

Shared between router.py (request/response binding) and service.py (business logic).
Neither imports the other — both import from here to avoid circular imports.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "QuizAnswer",
    "QuizSubmission",
    "QuizResult",
    "TeachbackSubmission",
    "TeachbackResult",
    "OnboardingAnswer",
    "OnboardingDiagnosticSubmission",
    "OnboardingResult",
    "ConsentCreate",
    "ConsentRecord",
]


# ── Session lifecycle schemas (Story 2-35 / D18) ───────────────────────────────
#
# `sessions` had ZERO writers anywhere in the codebase, so quiz and teach-back
# 404'd for every student. The schema shows server-side minting was always the
# intent:
#
#     session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid()
#     user_id     uuid NOT NULL REFERENCES public.users(id)
#     lesson_id   uuid NOT NULL REFERENCES public.lessons(lesson_id)
#     started_at  timestamptz NOT NULL DEFAULT now()
#
# A client-chosen UUID cannot satisfy those foreign keys or make `started_at`
# mean anything.


class SessionCreate(BaseModel):
    """Request body for `POST /sessions`.

    `lesson_id` ONLY. `user_id` comes from the verified JWT and `session_id` /
    `started_at` are database-generated. Pydantic ignores unknown fields by
    default, so a client sending any of those three is silently ignored rather
    than trusted — asserted by
    `test_user_id_comes_from_the_jwt_and_is_never_accepted_from_the_client`.
    D97 (was D79): min_length=1 ensures empty string returns 422 rather than reaching the DB
    with a cast-to-UUID error that would produce 500.
    """

    lesson_id: str = Field(min_length=1)

    @field_validator("lesson_id", mode="before")
    @classmethod
    def lesson_id_must_be_uuid(cls, v: object) -> str:
        """D104 (was D94): reject non-UUID strings before the Postgres cast.

        Without this, a typo like "x" passes Pydantic validation and causes a
        500 from the DB with no actionable message for the caller.
        """
        try:
            return str(uuid.UUID(str(v)))  # normalises to lowercase RFC 4122
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"lesson_id must be a valid UUID "
                f"(e.g. '123e4567-e89b-12d3-a456-426614174000'), got: {v!r}"
            ) from exc


class SessionCreated(BaseModel):
    """Response body for `POST /sessions` — all three values come from the DB."""

    session_id: str
    lesson_id: str
    started_at: str | None = None


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
    response_text: str = Field(
        min_length=1, max_length=4000, description="Student's typed teach-back response"
    )

    @field_validator("response_text")
    @classmethod
    def response_text_not_blank(cls, v: str) -> str:
        # D98 (was D80): min_length=1 counts characters, not content — a single space passes.
        # Strip first so "   " is treated as empty and returned as 422, not forwarded
        # to grade_teachback as substantively empty content that silently burns tokens.
        if not v.strip():
            raise ValueError("response_text must not be blank or whitespace-only")
        return v


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


# ── DPDP consent schemas (Story 3-32 / D29 fix) ───────────────────────────────
# user_consents table: INSERT-only, immutable audit trail.
# consent_type CHECK constraint in DB: ('attention_tracking', 'learner_dna').
# users.attention_consent is set by the DB trigger — NEVER by this endpoint.


class ConsentCreate(BaseModel):
    """Request body for POST /api/assessment/consent.

    user_id is never accepted here — it comes exclusively from current_user["sub"].
    Extra fields are silently ignored (Pydantic default).
    """

    consent_type: Literal["attention_tracking", "learner_dna"]
    policy_version: str = Field(min_length=1, max_length=50)


class ConsentRecord(BaseModel):
    """Response for POST /api/assessment/consent — mirrors the user_consents row."""

    id: str
    user_id: str
    consent_type: str
    policy_version: str
    consented_at: str | None = None
