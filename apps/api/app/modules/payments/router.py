"""
Payments module router.

POST /api/payments/create-order — authenticated; creates Razorpay order.
POST /api/payments/webhook      — unauthenticated; HMAC-verified; fulfills payment.

AC-2 critical: raw_body = await request.body() is called BEFORE any JSON parsing.
The raw bytes are used for HMAC verification and never re-serialized.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.dependencies import ApprovedUser
from app.modules.payments import schemas, service
from app.providers.payments.razorpay import RazorpayProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/create-order", response_model=schemas.CreateOrderResponse)
async def create_order_endpoint(
    body: schemas.CreateOrderRequest,
    current_user: ApprovedUser,
    settings: SettingsDep,
) -> schemas.CreateOrderResponse:
    """Create a Razorpay order and return order_id + publishable key_id.

    The key_secret is never included in the response (AC-1).
    """
    user_id: str = current_user["sub"]
    return await service.create_order(
        lesson_id=body.lesson_id,
        user_id=user_id,
        amount_paise=body.amount_paise,
        settings=settings,
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def webhook_endpoint(
    request: Request,
    settings: SettingsDep,
) -> schemas.WebhookResponse:
    """Handle Razorpay webhook events.

    MUST read raw body bytes BEFORE any JSON parse (AC-2).
    Verifies X-Razorpay-Signature as HMAC-SHA256 over raw bytes.
    On payment.captured: writes lesson_access row (AC-3).
    Idempotent on duplicate delivery (AC-4).
    """
    # AC-2: raw bytes first — never re-serialize JSON before hashing
    raw_body: bytes = await request.body()

    signature = request.headers.get("X-Razorpay-Signature", "")
    provider = RazorpayProvider(settings=settings)

    if not provider.verify_signature(raw_body, signature):
        logger.warning("Invalid Razorpay webhook signature — rejecting")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Razorpay webhook payload is not valid JSON")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    event: str = payload.get("event", "")
    logger.info("Razorpay webhook received: event=%s", event)

    if event == "payment.captured":
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        await service.handle_payment_captured(payment_entity)

    return schemas.WebhookResponse(status="ok")
