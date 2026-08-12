"""
Assessment module router.

Handles quiz submission, teach-back evaluation, session reports,
learner DNA retrieval, and onboarding diagnostic submission.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel  # SessionReport, LearnerDNA still use BaseModel directly

from app.core.posthog_client import capture_event
from app.dependencies import ApprovedUser, CurrentUser

# All request/response models live in schemas.py so service.py can import them
# without creating a circular import (service ← router ← service).
from app.modules.assessment.schemas import (
    ConsentCreate,
    ConsentRecord,
    OnboardingDiagnosticSubmission,
    OnboardingResult,
    QuizAnswer,
    QuizResult,
    QuizSubmission,
    SessionCreate,
    SessionCreated,
    TeachbackResult,
    TeachbackSubmission,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assessment"])

# Re-export for backward compatibility — tests and other modules import from here.
__all__ = ["QuizAnswer", "QuizSubmission", "QuizResult", "TeachbackSubmission", "TeachbackResult"]


class SessionReport(BaseModel):
    session_id: str
    user_id: str
    lesson_id: str
    ces_score: float | None = None  # None when session ended before finalization
    ces_breakdown: dict[str, float]
    interventions_count: int
    quiz_score: float | None
    teachback_score: float | None
    duration_minutes: float
    completed_at: str | None
    # Story 3-29 — tier context fields (additive; existing fields unchanged)
    tier: str
    tier_label: str
    quiz_total_questions: int
    quiz_correct_count: int
    quiz_accuracy_label: str | None
    # Story 3-30 — Learner DNA snapshot (descriptive labels + growth direction)
    learner_dna_snapshot: dict[str, Any] | None = None
    # S3-47 (D17) — CES formula disclosure: which variant was applied + how many signals
    formula_applied: Literal["full_5_signal", "teachback_redistributed_4_signal"]
    signal_coverage: int
    # S3-50 (D18) — CES history summary: compact engagement trend (min/max/mean/window_count)
    ces_history_summary: dict[str, Any] | None = None
    # S3-51 (D19) — Intervention trigger count for this session.
    # SEMANTIC NOTE (S3-53): counts `intervention_triggered` events in the `session_events`
    # DB table — measures trigger events, NOT WebSocket delivery confirmations.
    # A WS delivery failure that still runs intervening_node creates a DB event but sends
    # nothing to the client. Rename to intervention_events_count in a future non-frozen-
    # contract release (requires 4-dev PR review per CLAUDE.md §16).
    intervention_messages_used: int = 0


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
    "/sessions",
    response_model=SessionCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Start a lesson attempt — mints the session row",
)
async def create_session_endpoint(
    body: SessionCreate,
    current_user: CurrentUser,
) -> SessionCreated:
    """Create the `sessions` row for this lesson attempt and return its id.

    Story 2-35 / D18. Call this ONCE when a lesson starts, not per segment —
    every call is a new attempt, which is intentional (re-learning must produce a
    new session for CES history).

    `user_id` is taken from the verified JWT and is never read from the body.
    """
    from app.core.db import get_supabase  # lazy — prevents circular import at module load
    from app.modules.assessment.service import create_session

    created = await create_session(
        lesson_id=body.lesson_id,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )
    return SessionCreated(**created)


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
    current_user: ApprovedUser,
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
    from app.core.redis import get_redis  # noqa: PLC0415 — S3-42 (D9): per-signal histories
    from app.modules.assessment.service import get_analytics_consent, get_session_report

    supabase = get_supabase()
    result = await get_session_report(
        session_id=session_id,
        user_id=current_user["sub"],
        supabase=supabase,
        redis=get_redis(),  # S3-42 (D9): enables real per-signal breakdown averages
    )
    consent = await get_analytics_consent(user_id=current_user["sub"], supabase=supabase)
    capture_event(
        distinct_id=current_user["sub"],
        event="assessment_session_report_viewed",
        properties={"session_id": session_id},
        analytics_consent=consent,
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
    from app.core.redis import get_redis  # lazy — prevents circular import at module load
    from app.modules.assessment.service import get_analytics_consent, get_learner_dna_data

    user_id: str = current_user["sub"]
    supabase = get_supabase()
    redis_client = None
    try:
        redis_client = get_redis()
    except Exception as exc:
        logger.debug("Redis unavailable for reassessment_due check: %s", exc)
    body = await get_learner_dna_data(user_id=user_id, supabase=supabase, redis=redis_client)
    consent = await get_analytics_consent(user_id=user_id, supabase=supabase)
    capture_event(
        distinct_id=user_id,
        event="assessment_dna_viewed",
        properties={"session_count": body.get("session_count", 0)},
        analytics_consent=consent,
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
    current_user: ApprovedUser,
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
    reassessment_key = f"user:{user_id}:reassessment_due"

    # Atomic SET NX eliminates the TOCTOU race between a read-check and a later write.
    # Returns True if key was newly set; None/False if key already existed.
    redis = get_redis()

    # Re-assessment bypass: if the re-assessment flag is set, the user is allowed to
    # resubmit the onboarding form. Delete the idempotency key so SET NX succeeds below.
    try:
        if await redis.get(reassessment_key) is not None:
            await redis.delete(onboarding_key)
    except Exception as exc:
        logger.debug("Re-assessment bypass check failed (non-fatal): %s", exc)

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

    # Clear re-assessment flag — the fresh onboarding resets the cycle (non-fatal).
    _safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")
    try:
        await redis.delete(reassessment_key)
    except Exception as exc:
        logger.warning("onboarding: reassessment flag clear failed user=%s: %s", _safe_uid, exc)

    return result


@router.post(
    "/consent",
    response_model=ConsentRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Record user consent (DPDP Act 2023 compliance — D29 fix)",
)
async def record_consent_endpoint(
    body: ConsentCreate,
    current_user: CurrentUser,
    response: Response,
) -> ConsentRecord:
    """Record a DPDP consent event in the user_consents audit table.

    Story 3-32 / D29. This endpoint is the ONLY writer to user_consents.
    A real row here is required before AttentionMonitor (S3-02) can legally
    initialize — the migration's dual-condition RLS on attention_events checks
    both users.attention_consent (boolean) AND a user_consents row.

    Returns 201 on first consent for this user+type+version.
    Returns 200 if an identical consent record already exists (idempotent).

    user_id is always sourced from the verified JWT — never from the request body.
    users.attention_consent is updated by the DB trigger, never by this function.
    """
    from app.core.db import get_supabase  # lazy — prevents circular import at module load
    from app.modules.assessment.service import record_consent

    record, is_new = await record_consent(
        user_id=current_user["sub"],
        consent_type=body.consent_type,
        policy_version=body.policy_version,
        supabase=get_supabase(),
    )
    if not is_new:
        response.status_code = status.HTTP_200_OK
    return ConsentRecord(**record)
