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


class WebhookVerificationError(Exception):
    """A webhook payload failed signature verification or could not be
    parsed into the shape this codebase expects, even after a valid
    signature (e.g. a malformed/unexpected JSON structure).

    Review Finding (Story 5-3): the original design let
    `stripe.SignatureVerificationError` cross the provider boundary
    directly, forcing the router to `import stripe` just to catch it —
    exactly the direct-provider-dependency CLAUDE.md's abstraction rule
    exists to prevent. Every provider implementation must catch its own
    SDK-specific exceptions and re-raise this one instead.
    """


class PaymentProviderError(Exception):
    """A payment provider's API call failed for a reason outside this
    codebase's control (network error, invalid price, provider outage).

    Review Finding (Story 5-3): `create_checkout_session` had no error
    handling at all — a bad price, network failure, or provider outage
    surfaced as an opaque generic 500. Provider implementations must catch
    their own SDK-specific errors and re-raise this one instead.
    """


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

        Raises:
            PaymentProviderError: The provider's API call failed (network,
                invalid price, provider outage). Never the provider SDK's
                own exception type — that would leak across the boundary.
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
            WebhookVerificationError: A missing/invalid signature, or a
                signature-valid-but-malformed payload. Never the provider
                SDK's own exception type. Callers must catch this and
                return an explicit error response — never a DB write on
                an unverified or unparseable payload.
        """
        ...
