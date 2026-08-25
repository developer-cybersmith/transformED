"""
Payments service layer — Stripe webhook processing and lesson-credit RPC
wrappers (Story 5-3/S4-3).

`grant_lesson_credits`/`decrement_lesson_credit` are called from BOTH this
module's own webhook handler AND `content/router.py`'s generation gate —
this is the service-layer boundary CLAUDE.md's "one discipline rule"
requires (modules communicate only through service layer, never via direct
DB access into another module's tables): `content/router.py` never touches
`lesson_access`/`stripe_events` directly, only through these functions.
"""

from __future__ import annotations

import asyncio
import logging

from supabase import Client

from app.providers.payments.base import WebhookEvent

logger = logging.getLogger(__name__)


async def grant_lesson_credits(supabase: Client, user_id: str, credits: int) -> None:
    """Atomic INSERT ... ON CONFLICT DO UPDATE (`grant_lesson_credits` RPC)."""
    await asyncio.to_thread(
        lambda: supabase.rpc(
            "grant_lesson_credits", {"p_user_id": user_id, "p_credits": credits}
        ).execute()
    )


async def decrement_lesson_credit(supabase: Client, user_id: str) -> bool:
    """Atomic conditional UPDATE (`decrement_lesson_credit` RPC).

    Returns whether a credit was actually spent. False means zero credits
    remaining — the caller must not create any row on this path (AC8).
    """
    resp = await asyncio.to_thread(
        lambda: supabase.rpc("decrement_lesson_credit", {"p_user_id": user_id}).execute()
    )
    return bool(resp.data)


async def _record_stripe_event_if_new(
    supabase: Client, *, event_id: str, session_id: str, event_type: str
) -> bool:
    """Durable idempotency check (`record_stripe_event_if_new` RPC, AC5).

    Returns True only if THIS call's INSERT actually affected a row — a
    Postgres PRIMARY KEY constraint on `stripe_event_id`, never an
    in-process cache or a prior SELECT a second request could race past.
    """
    resp = await asyncio.to_thread(
        lambda: supabase.rpc(
            "record_stripe_event_if_new",
            {"p_event_id": event_id, "p_session_id": session_id, "p_event_type": event_type},
        ).execute()
    )
    return bool(resp.data)


async def process_webhook_event(supabase: Client, event: WebhookEvent) -> None:
    """Grant credits on a verified, first-seen `checkout.session.completed`.

    A redelivered event id, or any event type other than
    `checkout.session.completed`, is a documented no-op — the caller still
    acknowledges 200 either way (AC6), never treats either case as an error.
    """
    is_new = await _record_stripe_event_if_new(
        supabase,
        event_id=event.event_id,
        session_id=str(event.data_object.get("id") or ""),
        event_type=event.event_type,
    )
    if not is_new:
        logger.info("stripe webhook: duplicate event_id=%s ignored (idempotent)", event.event_id)
        return

    if event.event_type != "checkout.session.completed":
        return

    user_id = (event.data_object.get("metadata") or {}).get("user_id")
    if not user_id:
        # Scale & Load Q2: never a silent drop, never an uncaught 500 that
        # would make Stripe retry forever against a payload that will never
        # parse differently — logged at ERROR so an operator sees it.
        logger.error(
            "stripe webhook: checkout.session.completed event_id=%s carried no "
            "metadata.user_id -- no credits granted, needs manual investigation",
            event.event_id,
        )
        return

    from app.config import get_settings

    settings = get_settings()
    await grant_lesson_credits(supabase, str(user_id), settings.stripe_lesson_credits_per_purchase)
