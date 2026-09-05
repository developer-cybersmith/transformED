"""
Payments module — Pydantic request/response schemas.

AC-1: CreateOrderRequest / CreateOrderResponse
AC-3: WebhookResponse
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    lesson_id: str = Field(..., description="UUID of the lesson being purchased")
    # amount_paise is accepted for backward compat with frontend display logic but is
    # intentionally ignored server-side — the canonical price comes from lessons.price_paise
    # in the DB, preventing price-bypass attacks (S4-1 patch 1).
    amount_paise: int | None = Field(
        default=None,
        gt=0,
        description="Informational only — server uses the lesson's canonical DB price",
    )


class CreateOrderResponse(BaseModel):
    order_id: str = Field(..., description="Razorpay order ID — returned to frontend")
    key_id: str = Field(..., description="Razorpay publishable key ID — returned to frontend")
    price_paise: int = Field(..., description="Canonical lesson price used for this Razorpay order")


class WebhookResponse(BaseModel):
    status: str = "ok"
