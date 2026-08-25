"""Response models for the payments module (Story 5-3/S4-3)."""

from __future__ import annotations

from pydantic import BaseModel


class CreateCheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str
