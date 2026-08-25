"""
Stripe implementation of `PaymentProvider`.

The ONLY file in this module tree allowed to `import stripe` (CLAUDE.md:
"No direct provider calls in business logic — go through providers/"). No
router or service module imports the `stripe` SDK directly.
"""

from __future__ import annotations

from typing import Any

import stripe

from app.providers.payments.base import CheckoutSession, PaymentProvider, WebhookEvent


class StripePaymentProvider(PaymentProvider):
    def __init__(self, *, api_key: str, webhook_secret: str) -> None:
        self._api_key = api_key
        self._webhook_secret = webhook_secret

    def create_checkout_session(
        self,
        *,
        price_id: str,
        quantity: int,
        user_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        session: Any = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": price_id, "quantity": quantity}],
            metadata={"user_id": user_id},
            success_url=success_url,
            cancel_url=cancel_url,
            api_key=self._api_key,
        )
        return CheckoutSession(checkout_url=session.url, session_id=session.id)

    def verify_and_parse_webhook(self, payload: bytes, sig_header: str) -> WebhookEvent:
        # Raises stripe.SignatureVerificationError on a missing/invalid
        # signature — callers must not catch this and write to any table.
        event: Any = stripe.Webhook.construct_event(payload, sig_header, self._webhook_secret)
        # StripeObject is deliberately NOT dict()-convertible or iterable
        # (raises TypeError, verified against the installed SDK) — .to_dict()
        # is the documented conversion.
        data_object = event["data"]["object"].to_dict()
        return WebhookEvent(
            event_id=event["id"],
            event_type=event["type"],
            data_object=data_object,
        )
