"""
Payments service layer — order creation and webhook fulfillment.

AC-3: handle_payment_captured writes one lesson_access row on payment.captured.
AC-4: idempotency is enforced by the DB UNIQUE(razorpay_payment_id) constraint;
      a duplicate webhook (Razorpay retries) catches PostgreSQL error 23505 and
      returns cleanly — no SELECT-then-INSERT race (same class as D45).
AC-5: all Razorpay HTTP calls go through RazorpayProvider, never direct httpx.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings
from app.modules.payments.schemas import CreateOrderResponse
from app.providers.payments.razorpay import RazorpayProvider

logger = logging.getLogger(__name__)

# PostgreSQL unique violation error code
_PG_UNIQUE_VIOLATION = "23505"


async def create_order(
    lesson_id: str,
    user_id: str,
    amount_paise: int,
    settings: Settings | None = None,
) -> CreateOrderResponse:
    """Call Razorpay to create an order and return order_id + publishable key_id.

    user_id is stored in Razorpay order notes so the webhook handler can
    retrieve it without a separate DB lookup.
    """
    _settings = settings or get_settings()
    provider = RazorpayProvider(settings=_settings)
    result = await provider.create_order(
        amount_paise=amount_paise,
        currency="INR",
        notes={"user_id": user_id, "lesson_id": lesson_id},
    )
    return CreateOrderResponse(
        order_id=result["id"],
        key_id=_settings.razorpay_key_id,
    )


async def handle_payment_captured(
    payment_entity: dict[str, Any],
) -> None:
    """Write a lesson_access row for a verified payment.captured event.

    Idempotent: duplicate payment_id raises PostgreSQL 23505 (unique violation),
    which is caught and logged — no exception propagates to the webhook handler,
    so Razorpay receives 200 and stops retrying.
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
            "payment.captured missing user_id or lesson_id in notes: payment_id=%s order_id=%s",
            payment_id,
            order_id,
        )
        return

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
            user_id, lesson_id, payment_id,
        )
    except Exception as exc:
        # Check for PostgreSQL unique violation (idempotent duplicate webhook)
        exc_str = str(exc)
        if _PG_UNIQUE_VIOLATION in exc_str or "duplicate key" in exc_str.lower():
            logger.info(
                "Duplicate payment.captured (idempotent): payment_id=%s"
                " — lesson_access already exists",
                payment_id,
            )
            return
        # Re-raise unexpected errors so the webhook returns 500 and Razorpay retries
        raise
