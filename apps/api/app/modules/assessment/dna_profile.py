"""Per-session Learner DNA profile text generation.

After fuse_learner_dna() returns the updated dimension dict, Dev 4 calls
refresh_dna_profile() to generate a natural-language profile_text via
GPT-4o-mini and upsert it to learner_dna.profile_text.

Separation of concerns:
  - dna_fusion.py — computes EMA-updated 9 dimensions, no LLM calls
  - dna_profile.py — generates profile_text from updated dims, LLM call here

No openai imports allowed here. All LLM calls go through OpenAILLMProvider.
No hardcoded model strings — always settings.llm_mini.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings

from app.providers.llm.openai import OpenAILLMProvider  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = ["refresh_dna_profile"]


async def refresh_dna_profile(
    *,
    user_id: str,
    dims: dict[str, float],
    session_count: int,
    supabase: Any,  # noqa: ANN401
    settings: Settings,
) -> str | None:
    """Generate a new profile_text and upsert it to learner_dna.

    Reads badge_labels from the DB, generates a 2-3 sentence natural-language
    profile via GPT-4o-mini (settings.llm_mini), appends the DPDP Act 2023
    disclaimer, and upserts profile_text only (never touches badge_labels,
    dimension columns, or session_count).

    Call this AFTER fuse_learner_dna() returns the updated dimension dict.

    Args:
        user_id:       UUID of the learner (from JWT-decoded subject).
        dims:          Updated 9-dimension dict from fuse_learner_dna().
        session_count: New session_count after the fusion increment.
        supabase:      Synchronous Supabase client (service-role key, RLS bypassed).
        settings:      App settings (carries llm_mini, openai_api_key).

    Returns:
        The generated profile_text string on success, None if LLM call fails.

    Raises:
        HTTPException 503: DB upsert failure.
    """
    from fastapi import HTTPException, status

    from app.modules.assessment.prompts import generate_dna_profile_text

    # Sanitize user_id for log calls — prevents log-injection via newlines (SEC-005)
    _safe_uid = str(user_id).replace("\n", " ").replace("\r", " ")

    # ── Step 1: Read badge_labels from learner_dna (non-fatal on failure) ───────
    badge_labels: list[str] = []
    try:
        dna_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("learner_dna")
                .select("badge_labels")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        )
        if dna_resp.data is not None:
            badge_labels = dna_resp.data.get("badge_labels") or []
    except Exception as exc:
        logger.warning(
            "DNA profile: badge_labels read failed user=%s: %s",
            _safe_uid,
            exc,
        )

    # ── Step 2: Generate profile_text via LLM (non-fatal on failure) ────────────
    # OpenAILLMProvider instantiation is inside try so constructor failures are
    # also non-fatal — consistent with AC 10's "on any exception → return None".
    try:
        provider = OpenAILLMProvider(lesson_id=f"dna-profile:{user_id}")
        profile_text = await generate_dna_profile_text(
            dims=dims,
            session_count=session_count,
            badge_labels=badge_labels,
            provider=provider,
            settings=settings,
        )
    except Exception as exc:
        logger.warning(
            "DNA profile: LLM call failed user=%s: %s",
            _safe_uid,
            exc,
        )
        return None

    # ── Step 3: Upsert profile_text to learner_dna (profile_text column ONLY) ───
    try:
        upsert_resp = await asyncio.to_thread(
            lambda: (
                supabase.table("learner_dna")
                .upsert({"user_id": user_id, "profile_text": profile_text}, on_conflict="user_id")
                .execute()
            )
        )
        upsert_error = getattr(upsert_resp, "error", None)
        if upsert_error:
            safe_err = str(upsert_error).replace("\n", " ").replace("\r", " ")
            logger.error(
                "DNA profile: upsert failed user=%s: %s",
                _safe_uid,
                safe_err,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not update learner profile text.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "DNA profile: upsert exception user=%s: %s",
            _safe_uid,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not update learner profile text.",
        ) from exc

    logger.info(
        "DNA profile: updated user=%s session_count=%d",
        _safe_uid,
        session_count,
    )
    return profile_text
