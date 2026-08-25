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
    """Durable idempotency check with NO credit grant (`record_stripe_event_if_new`
    RPC, AC5). Used for every event that does not itself grant a credit —
    a real credit grant goes through `_record_event_and_grant_credits`
    instead, atomically, in the SAME database call (see that function's
    docstring for why the two steps must not be split in Python).

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


async def _record_event_and_grant_credits(
    supabase: Client,
    *,
    event_id: str,
    session_id: str,
    event_type: str,
    user_id: str,
    credits: int,
) -> bool:
    """Atomic idempotency-check-AND-credit-grant in one database call
    (`record_stripe_event_and_grant_credits` RPC).

    Review Finding (Story 5-3, code review 2026-08-26): the original design
    called `_record_stripe_event_if_new` and `grant_lesson_credits` as two
    SEPARATE RPC calls. If the second call failed for any reason after the
    first had already committed, the event was permanently marked
    "processed" with no credit ever granted, and Stripe's retry would then
    silently no-op forever — a real, previously-unguarded money-losing bug.
    A single plpgsql function body is one implicit transaction: either both
    the idempotency row and the credit grant land, or neither does.

    Returns whether THIS call actually processed the event (True) or found
    it already recorded by an earlier delivery (False, no-op).
    """
    resp = await asyncio.to_thread(
        lambda: supabase.rpc(
            "record_stripe_event_and_grant_credits",
            {
                "p_event_id": event_id,
                "p_session_id": session_id,
                "p_event_type": event_type,
                "p_user_id": user_id,
                "p_credits": credits,
            },
        ).execute()
    )
    return bool(resp.data)


async def process_webhook_event(supabase: Client, event: WebhookEvent) -> None:
    """Grant credits on a verified, first-seen, ACTUALLY-PAID
    `checkout.session.completed`.

    A redelivered event id is always a no-op regardless of type (AC6/AC5).
    For `checkout.session.completed` specifically: Stripe documents that
    this event can fire for delayed/async payment methods before payment
    is actually confirmed (Review Finding, Story 5-3) — `payment_status`
    must be `"paid"` before any credit is granted; a not-yet-paid session
    is recorded in the idempotency ledger (so a later duplicate delivery of
    the SAME not-yet-paid event doesn't re-process) but grants nothing.
    Handling the follow-up `checkout.session.async_payment_succeeded` event
    is out of scope for this story (registered as a defer item).
    """
    if event.event_type != "checkout.session.completed":
        await _record_stripe_event_if_new(
            supabase,
            event_id=event.event_id,
            session_id=str(event.data_object.get("id") or ""),
            event_type=event.event_type,
        )
        return

    session_id = str(event.data_object.get("id") or "")
    user_id = (event.data_object.get("metadata") or {}).get("user_id")
    payment_status = event.data_object.get("payment_status")

    if user_id and payment_status == "paid":
        from app.config import get_settings

        settings = get_settings()
        is_new = await _record_event_and_grant_credits(
            supabase,
            event_id=event.event_id,
            session_id=session_id,
            event_type=event.event_type,
            user_id=str(user_id),
            credits=settings.stripe_lesson_credits_per_purchase,
        )
        if not is_new:
            logger.info(
                "stripe webhook: duplicate event_id=%s ignored (idempotent)", event.event_id
            )
        return

    # Not (yet) paid, and/or missing metadata.user_id — record the ledger
    # entry (so a redelivery of this exact malformed/unpaid event doesn't
    # reprocess indefinitely) but grant nothing.
    is_new = await _record_stripe_event_if_new(
        supabase, event_id=event.event_id, session_id=session_id, event_type=event.event_type
    )
    if not is_new:
        return

    if not user_id:
        # Scale & Load Q2: never a silent drop, never an uncaught 500 that
        # would make Stripe retry forever against a payload that will never
        # parse differently — logged at ERROR so an operator sees it.
        logger.error(
            "stripe webhook: checkout.session.completed event_id=%s carried no "
            "metadata.user_id -- no credits granted, needs manual investigation",
            event.event_id,
        )
    elif payment_status != "paid":
        logger.info(
            "stripe webhook: checkout.session.completed event_id=%s payment_status=%r "
            "is not yet 'paid' -- no credits granted (awaiting async confirmation, "
            "if any; async_payment_succeeded handling is out of scope for this story)",
            event.event_id,
            payment_status,
        )
