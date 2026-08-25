"""
Payments module router — Stripe Checkout session creation + webhook.

Story 5-3/S4-3. Hosted Stripe Checkout only — no custom payment UI, no card
data ever touches this server (CLAUDE.md's Locked Technology Stack: "Stripe
Checkout (hosted) — no card data on TransformED servers under any
circumstances").
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.config import get_settings
from app.core.db import get_supabase
from app.core.rate_limit import _get_user_key, limiter
from app.dependencies import CurrentUser
from app.modules.payments.schemas import CreateCheckoutSessionResponse
from app.modules.payments.service import process_webhook_event
from app.providers.payments.base import PaymentProviderError, WebhookVerificationError
from app.providers.payments.stripe import StripePaymentProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])

# Frontend routes Dev 2 owns (docs/master-tracker.md Sprint 4: "Stripe
# Checkout redirect integrated into onboarding flow" is Dev 2's own task —
# this story only sets these URLs, the pages themselves are out of scope).
# Review Finding (Story 5-3): Stripe's real Checkout Session API rejects
# relative success_url/cancel_url outright — these must be joined with
# settings.app_base_url into fully-qualified URLs before being sent.
_SUCCESS_PATH = "/payment/success?session_id={CHECKOUT_SESSION_ID}"
_CANCEL_PATH = "/payment/cancel"

# Review Finding (Story 5-3, Scale & Load Q4): the webhook route is
# deliberately unauthenticated and unrate-limited (Stripe retries must never
# be throttled), which made an unbounded `await request.body()` read a real
# memory-exhaustion vector for ANY caller, not just Stripe. Real
# checkout.session.completed payloads are small, fixed-schema JSON (well
# under 10 KB in practice) — 64 KB is generous headroom, not a tight fit.
_MAX_WEBHOOK_BYTES = 64 * 1024


def _provider() -> StripePaymentProvider:
    settings = get_settings()
    return StripePaymentProvider(
        api_key=settings.stripe_secret_key, webhook_secret=settings.stripe_webhook_secret
    )


@router.post(
    "/create-checkout-session",
    response_model=CreateCheckoutSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a Stripe Checkout Session for one lesson-credit purchase",
)
@limiter.limit("5/minute", key_func=_get_user_key)
async def create_checkout_session(
    request: Request, response: Response, current_user: CurrentUser
) -> CreateCheckoutSessionResponse:
    """AC1/AC2: server-side Price ID only — never a client-supplied amount.

    `request: Request` is load-bearing for slowapi's key resolution (see the
    identical note on `generate_chapter_lesson` — the parameter must be
    literally named `request` of type `Request` or `@limiter.limit` raises
    at call time, not import time). `response: Response` is likewise
    load-bearing — `headers_enabled=True` on the shared `limiter` makes
    slowapi inject rate-limit headers into it after the handler returns;
    omitting it raises at call time (`_inject_headers` requires a real
    `Response` instance). Otherwise unused; do not remove either.
    """
    settings = get_settings()
    user_id: str = current_user["sub"]
    base = settings.app_base_url.rstrip("/")

    try:
        session = _provider().create_checkout_session(
            price_id=settings.stripe_price_id_lesson_credit,
            quantity=1,
            user_id=user_id,
            success_url=f"{base}{_SUCCESS_PATH}",
            cancel_url=f"{base}{_CANCEL_PATH}",
        )
    except PaymentProviderError as exc:
        logger.error("stripe checkout session creation failed user_id=%s", user_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Payment provider error"
        ) from exc

    return CreateCheckoutSessionResponse(
        checkout_url=session.checkout_url, session_id=session.session_id
    )


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Stripe webhook — checkout.session.completed grants lesson credits",
)
async def stripe_webhook(request: Request) -> dict[str, bool]:
    """AC3: reads the RAW body before any parsing — no `CurrentUser`/JWT
    dependency (Stripe, not a logged-in student, is the caller), and no
    per-user rate limit (a burst of legitimate Stripe retries must never be
    throttled)."""
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large"
        )

    payload = await request.body()
    if len(payload) > _MAX_WEBHOOK_BYTES:
        # Backstop for a missing/understated Content-Length header — the
        # header check above is the fast-path rejection, this catches a
        # caller that omits or lies about it.
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large"
        )

    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = _provider().verify_and_parse_webhook(payload, sig_header)
    except WebhookVerificationError as exc:
        # AC3: a missing/invalid signature (or a malformed payload) writes
        # NOTHING to any table — verification happens strictly before any
        # DB call below.
        logger.warning("stripe webhook: verification failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature or payload"
        ) from exc

    supabase = get_supabase()
    await process_webhook_event(supabase, event)
    return {"received": True}
