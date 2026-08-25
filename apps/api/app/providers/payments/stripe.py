"""
Stripe implementation of `PaymentProvider`.

The ONLY file in this module tree allowed to `import stripe` (CLAUDE.md:
"No direct provider calls in business logic — go through providers/"). No
router or service module imports the `stripe` SDK directly, and no
`stripe`-specific exception type crosses this file's boundary — every SDK
exception is translated into `WebhookVerificationError`/`PaymentProviderError`
before it reaches a caller (Review Finding, Story 5-3: the first version of
this file let `stripe.SignatureVerificationError` escape directly, which
forced the router to `import stripe` just to catch it).
"""

from __future__ import annotations

from typing import Any

import stripe

from app.providers.payments.base import (
    CheckoutSession,
    PaymentProvider,
    PaymentProviderError,
    WebhookEvent,
    WebhookVerificationError,
)


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
        try:
            session: Any = stripe.checkout.Session.create(
                mode="payment",
                line_items=[{"price": price_id, "quantity": quantity}],
                metadata={"user_id": user_id},
                success_url=success_url,
                cancel_url=cancel_url,
                api_key=self._api_key,
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        return CheckoutSession(checkout_url=session.url, session_id=session.id)

    def verify_and_parse_webhook(self, payload: bytes, sig_header: str) -> WebhookEvent:
        try:
            event: Any = stripe.Webhook.construct_event(payload, sig_header, self._webhook_secret)
            # StripeObject is deliberately NOT dict()-convertible or iterable
            # (raises TypeError, verified against the installed SDK) —
            # .to_dict() is the documented conversion.
            data_object = event["data"]["object"].to_dict()
            return WebhookEvent(
                event_id=event["id"],
                event_type=event["type"],
                data_object=data_object,
            )
        except stripe.SignatureVerificationError as exc:
            raise WebhookVerificationError("invalid or missing signature") from exc
        except (KeyError, TypeError, IndexError) as exc:
            # Review Finding (Story 5-3): a signature-VALID but
            # structurally-malformed payload (missing data/object/id/type)
            # previously propagated as an uncaught KeyError/TypeError -> 500,
            # instead of the same explicit 400 a bad signature gets.
            raise WebhookVerificationError(f"malformed webhook payload: {exc}") from exc
