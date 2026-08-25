"""
Abstract base class for payment provider integrations.

Story 5-3/S4-3. Mirrors `apps/api/app/providers/base.py`'s LLM/TTS/Image
shape (PRD §5, CLAUDE.md: "no direct provider client calls in business
logic"). Stripe has no fallback-chain requirement the way TTS/Image do —
the wrapper exists for testability (mock `PaymentProvider` in every router
test, not the `stripe` SDK) and as a single choke point if a second payment
provider is ever added.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckoutSession:
    """The two fields a caller needs from a created Checkout Session."""

    checkout_url: str
    session_id: str


@dataclass(frozen=True)
class WebhookEvent:
    """A verified, parsed Stripe event — only the fields this codebase reads.

    `data_object` is the raw dict under `event.data.object` (e.g. the
    Checkout Session for a `checkout.session.completed` event) so callers
    can read `metadata`/`id` without depending on the SDK's own object
    shape beyond this boundary.
    """

    event_id: str
    event_type: str
    data_object: dict[str, Any]


class PaymentProvider(ABC):
    """Abstract interface for hosted-checkout payment providers."""

    @abstractmethod
    def create_checkout_session(
        self,
        *,
        price_id: str,
        quantity: int,
        user_id: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        """Create a hosted Checkout Session for a single line item.

        Args:
            price_id:     Provider-side Price ID — never a client-supplied
                           amount (this story's AC1: the endpoint never
                           accepts a client-supplied price or amount).
            quantity:     Line-item quantity.
            user_id:      Embedded as session metadata so the webhook can
                           attribute the completed payment to a user without
                           trusting anything the client sends at redirect time.
            success_url:  Where the provider redirects on success.
            cancel_url:   Where the provider redirects on cancel.

        Returns:
            The created session's redirect URL and provider-side session id.
        """
        ...

    @abstractmethod
    def verify_and_parse_webhook(self, payload: bytes, sig_header: str) -> WebhookEvent:
        """Verify a webhook delivery's signature and return the parsed event.

        Args:
            payload:    The RAW request body bytes — signature verification
                        needs the exact bytes the provider signed, not a
                        re-serialized JSON parse.
            sig_header: The provider's signature header value.

        Returns:
            The verified, parsed event.

        Raises:
            Exception: A provider-specific signature-verification failure
                (e.g. Stripe's `SignatureVerificationError`). Callers must
                catch this and return an explicit error response — never a
                DB write on an unverified payload.
        """
        ...
