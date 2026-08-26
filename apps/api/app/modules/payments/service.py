"""
Payments service layer — order creation and webhook fulfillment.

AC-3: handle_payment_captured writes one lesson_access row on payment.captured.
AC-4: idempotency is enforced by the DB UNIQUE(razorpay_payment_id) constraint;
      a duplicate webhook (Razorpay retries) catches PostgreSQL error 23505 (unique
      violation), which is caught and logged — no exception propagates to the webhook
      handler, so Razorpay receives 200 and stops retrying.
AC-5: all Razorpay HTTP calls go through RazorpayProvider, never direct httpx.

S4-1 patch 1: create_order looks up lessons.price_paise from the DB so the server
      always uses the canonical price — the client-supplied amount_paise is intentionally
      not accepted as a parameter.

S4-1 patch 3: handle_payment_captured catches PostgreSQL FK violations (23503)
      separately from unique violations (23505). A 23503 means the lesson was deleted
      after the order was created; it emits logger.critical (admin alert) and returns
      200 to stop Razorpay retrying an unrecoverable permanent data error.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings
from app.modules.payments.schemas import CreateOrderResponse
from app.providers.payments.razorpay import RazorpayProvider

logger = logging.getLogger(__name__)

# PostgreSQL constraint error codes
_PG_UNIQUE_VIOLATION = "23505"  # duplicate key — idempotent duplicate webhook
_PG_FK_VIOLATION = "23503"       # foreign key violation — lesson deleted after order


class LessonNotFoundError(Exception):
    """Raised when create_order cannot find lesson_id in the lessons table."""


async def create_order(
    lesson_id: str,
    user_id: str,
    settings: Settings | None = None,
) -> CreateOrderResponse:
    """Create a Razorpay order using the lesson's canonical server-side price.

    Looks up lessons.price_paise from the DB so the server always controls the
    amount — the client-supplied amount_paise is never used (price-bypass fix).
    Raises LessonNotFoundError if lesson_id does not exist (router maps to 404).
    """
    # Late import to avoid DB client init at module load time (test isolation)
    from app.core.db import get_supabase

    supabase = get_supabase()
    lesson_row = (
        supabase.table("lessons")
        .select("price_paise")
        .eq("lesson_id", lesson_id)
        .maybe_single()
        .execute()
    )
    if lesson_row.data is None:
        raise LessonNotFoundError(lesson_id)

    price_paise: int = lesson_row.data["price_paise"]
    _settings = settings or get_settings()
    provider = RazorpayProvider(settings=_settings)
    result = await provider.create_order(
        amount_paise=price_paise,
        currency="INR",
        notes={"user_id": user_id, "lesson_id": lesson_id},
    )
    return CreateOrderResponse(
        order_id=result["id"],
        key_id=_settings.razorpay_key_id,
        price_paise=price_paise,
    )


async def handle_payment_captured(
    payment_entity: dict[str, Any],
) -> None:
    """Write a lesson_access row for a verified payment.captured event.

    Idempotent: duplicate payment_id raises PostgreSQL 23505 (unique violation),
    which is caught and logged — no exception propagates to the webhook handler,
    so Razorpay receives 200 and stops retrying.

    FK violation (23503): lesson was deleted after order creation — emits
    logger.critical so the admin can issue a manual refund, then returns 200
    to stop Razorpay retrying an unrecoverable permanent data error.
    """
    payment_id: str = payment_entity["id"]
    order_id: str = payment_entity["order_id"]
    amount_paise: int = payment_entity["amount"]
    currency: str = payment_entity.get("currency", "INR")
    notes: dict[str, str] = payment_entity.get("notes", {})

    user_id = notes.get("user_id")
    lesson_id = notes.get("lesson_id")

    if not user_id or not lesson_id:
        logger.error(
            "payment.captured missing user_id or lesson_id in notes:"
            " payment_id=%s order_id=%s",
            payment_id,
            order_id,
        )
        return

    # Late import to avoid DB client init at module load time (test isolation)
    from app.core.db import get_supabase

    supabase = get_supabase()

    row = {
        "user_id": user_id,
        "lesson_id": lesson_id,
        "razorpay_payment_id": payment_id,
        "razorpay_order_id": order_id,
        "amount_paise": amount_paise,
        "currency": currency,
        "status": "captured",
    }

    try:
        supabase.table("lesson_access").insert(row).execute()
        logger.info(
            "lesson_access granted: user_id=%s lesson_id=%s payment_id=%s",
            user_id,
            lesson_id,
            payment_id,
        )
    except Exception as exc:
        exc_str = str(exc)

        if _PG_UNIQUE_VIOLATION in exc_str or "duplicate key" in exc_str.lower():
            # Razorpay redelivered a webhook we already processed — safe to ignore.
            logger.info(
                "Duplicate payment.captured (idempotent): payment_id=%s"
                " — lesson_access already exists",
                payment_id,
            )
            return

        if _PG_FK_VIOLATION in exc_str or "foreign key" in exc_str.lower():
            # lesson_id was deleted after the order was created — Razorpay retries
            # cannot fix this. Return 200 to stop retrying; admin must refund manually.
            logger.critical(
                "PAYMENT CAPTURED BUT LESSON ACCESS DENIED: lesson_id=%s not found "
                "(FK violation 23503). MANUAL REFUND REQUIRED for "
                "payment_id=%s user_id=%s",
                lesson_id,
                payment_id,
                user_id,
            )
            return

        # Re-raise unexpected errors so the webhook returns 500 and Razorpay retries
        raise
