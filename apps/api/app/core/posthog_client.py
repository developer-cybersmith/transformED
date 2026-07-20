"""PostHog event capture wrapper.

Sets PostHog credentials once at module import time (when Settings are available)
and exposes a single fire-and-forget capture_event() function used by service
and router layers.

In test environments where env vars are absent the Settings construction is
silently skipped — posthog.api_key remains unset (None/empty) so capture_event()
is a no-op.  Test fixtures may then set posthog.api_key explicitly via
monkeypatch to exercise the instrumentation code.

If POSTHOG_API_KEY is unset (empty-string default), capture_event() is a
silent no-op — no network call, no exception.

DPDP Act 2023 compliance: capture_event() requires analytics_consent=True
(explicitly passed by each call site after checking the users.analytics_consent
column). Default is False — no events are sent without explicit user consent.
"""

from __future__ import annotations

import logging

import posthog

logger = logging.getLogger(__name__)

# Attempt credential setup at import time (AC 12 — set once, not on every call).
# BLOCKER-001 fix: bare `pass` replaced with a WARNING log so unexpected init
# failures (AttributeError, ValidationError) are visible in logs, not silently
# swallowed. The posthog.api_key intentionally stays falsy → no-op mode is
# the correct safe default when credentials are unavailable.
try:
    from app.config import get_settings as _get_settings

    _s = _get_settings()
    posthog.api_key = _s.posthog_api_key
    posthog.host = _s.posthog_host
except Exception as _exc:
    logger.warning(
        "PostHog client init failed — PostHog disabled for this process: %s",
        _exc,
    )


def capture_event(
    *,
    distinct_id: str,
    event: str,
    properties: dict,
    analytics_consent: bool = False,
) -> None:
    """Fire a PostHog event if PostHog is configured AND the user has consented.

    Silent no-op when:
    - posthog.api_key is falsy (PostHog not configured / test env)
    - analytics_consent is False (user has not granted consent — DPDP Act 2023)

    Never raises — any SDK exception is caught and logged at WARNING so the
    HTTP response is never affected by an observability outage (AC 11).

    Args:
        distinct_id: User UUID from the decoded JWT (never email or name).
        event: PostHog event name (e.g. "assessment_quiz_submitted").
        properties: Event properties dict — must contain no PII beyond user_id
            (enforced by AC 5; callers are responsible for content).
        analytics_consent: Must be True for the event to fire. Callers fetch
            this value from the users.analytics_consent DB column via
            service.get_analytics_consent() before calling this function.
    """
    if not posthog.api_key:
        return
    if not analytics_consent:
        return
    try:
        posthog.capture(distinct_id, event, properties)
    except Exception as exc:
        logger.warning("PostHog capture failed event=%r: %s", event, exc)
