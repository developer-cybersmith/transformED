"""
Razorpay payment provider.

Responsibilities
----------------
- Wraps Razorpay Orders API using httpx.AsyncClient (async-native; no sync SDK).
- Provides HMAC-SHA256 webhook signature verification over raw request bytes.
- Never logs or exposes razorpay_key_secret or razorpay_webhook_secret.

AC-2 note: verify_signature() operates on the raw bytes passed in — it never
re-serializes JSON, because re-dumping changes key order and whitespace, which
breaks the signature that Razorpay computed over the original payload bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RAZORPAY_ORDERS_URL = "https://api.razorpay.com/v1/orders"


class RazorpayProvider:
    """Async Razorpay client — order creation and webhook signature verification."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ── Signature verification (AC-2) ─────────────────────────────────────────

    def verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """Return True iff signature matches HMAC-SHA256 of raw_body.

        Uses raw_body bytes directly — never re-serializes JSON (AC-2).
        Uses hmac.compare_digest to prevent timing attacks.
        Returns False (reject) if RAZORPAY_WEBHOOK_SECRET is not configured.
        """
        if not signature or not self._settings.razorpay_webhook_secret:
            return False
        expected = hmac.new(
            key=self._settings.razorpay_webhook_secret.encode(),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ── Order creation (AC-1) ─────────────────────────────────────────────────

    async def create_order(
        self,
        amount_paise: int,
        currency: str = "INR",
        notes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Call Razorpay Orders API and return the raw response dict.

        Basic Auth uses key_id:key_secret — secret is ONLY in the auth header,
        never in the request body or the returned dict.
        Raises RuntimeError if credentials are not configured.
        """
        if not self._settings.razorpay_key_id or not self._settings.razorpay_key_secret:
            raise RuntimeError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set before calling create_order"
            )
        payload: dict[str, Any] = {
            "amount": amount_paise,
            "currency": currency,
            "notes": notes or {},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _RAZORPAY_ORDERS_URL,
                json=payload,
                auth=(self._settings.razorpay_key_id, self._settings.razorpay_key_secret),
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
