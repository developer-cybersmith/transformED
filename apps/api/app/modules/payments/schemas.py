"""
Payments module — Pydantic request/response schemas.

AC-1: CreateOrderRequest / CreateOrderResponse
AC-3: WebhookResponse
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    lesson_id: str = Field(..., description="UUID of the lesson being purchased")
    amount_paise: int = Field(..., gt=0, description="Amount in paise (INR smallest unit)")


class CreateOrderResponse(BaseModel):
    order_id: str = Field(..., description="Razorpay order ID — returned to frontend")
    key_id: str = Field(..., description="Razorpay publishable key ID — returned to frontend")


class WebhookResponse(BaseModel):
    status: str = "ok"
