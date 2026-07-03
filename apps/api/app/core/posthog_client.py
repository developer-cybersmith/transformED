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
"""
from __future__ import annotations

import logging

import posthog

logger = logging.getLogger(__name__)

# Attempt credential setup at import time (AC 12 — set once, not on every call).
# Wrapped in try/except so the module loads cleanly in test environments where
# required env vars (supabase_url, openai_api_key, etc.) are absent.
try:
    from app.config import get_settings as _get_settings
    _s = _get_settings()
    posthog.api_key = _s.posthog_api_key
    posthog.host = _s.posthog_host
except Exception:
    pass  # settings unavailable; posthog.api_key stays falsy → no-op mode


def capture_event(*, distinct_id: str, event: str, properties: dict) -> None:
    """Fire a PostHog event. Silent no-op when posthog.api_key is falsy.

    Never raises — any SDK exception is caught and logged at WARNING so the
    HTTP response is never affected by an observability outage (AC 11).
    """
    if not posthog.api_key:
        return
    try:
        posthog.capture(distinct_id, event, properties)
    except Exception as exc:
        logger.warning("PostHog capture failed event=%r: %s", event, exc)
