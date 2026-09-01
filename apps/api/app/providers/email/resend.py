"""
Resend transactional email provider implementation (Story 2-52).

Responsibilities
----------------
- Implements EmailProvider using Resend's REST API (POST /emails).
- Applies the existing retry decorator (app.core.retry.with_retry) — this
  provider does NOT reimplement retry/backoff, and does NOT add a circuit
  breaker: email delivery is not on the pipeline's critical/cost-tracked
  path the way LLM/TTS/Image calls are, so a new breaker key would be scope
  beyond what Story 2-52 asks for.
"""

from __future__ import annotations

import logging

import httpx

from app.core.retry import with_retry
from app.providers.base import EmailProvider

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


class ResendEmailProvider(EmailProvider):
    """Sends transactional email via the Resend REST API."""

    def __init__(self) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.resend_api_key
        self._from_email = settings.resend_from_email

    @with_retry(max_attempts=3)
    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
    ) -> str:
        """Send one email via Resend.

        Raises:
            RuntimeError: if RESEND_API_KEY is not configured (an ops/account
                setup gap, not a transient failure — never retried).
            httpx.HTTPStatusError: on a non-2xx response — classified by
                with_retry per CLAUDE.md §14 (429/5xx retried, 400/401 not).
        """
        if not self._api_key:
            raise RuntimeError(
                "RESEND_API_KEY is not configured — cannot send email. "
                "This is an account-setup gap, not a transient failure."
            )

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                _RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._from_email,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            response.raise_for_status()
            body = response.json()

        message_id: str = body.get("id", "")
        logger.info("ResendEmailProvider sent email id=%s to=%s", message_id, _mask_email(to))
        return message_id


def _mask_email(email: str) -> str:
    """Redact the local part of an email address for safe logging."""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    masked_local = local[0] + "***" if local else "***"
    return f"{masked_local}@{domain}"
