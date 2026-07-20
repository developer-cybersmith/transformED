"""
Sarvam AI Bulbul v2 TTS provider implementation.

Responsibilities
----------------
- Implements TTSProvider using Sarvam's Bulbul v2 text-to-speech HTTP API.
- Returns (audio_bytes, word_timestamps) tuples — timestamps always empty
  (Story 2-8 scope decision: slide-level timestamp mapping is deferred to a
  follow-up story; Narration.timestamps has no min_length constraint).
- Applies circuit breaker ("sarvam" provider key) and retry decorator.
- A 429 response body is inspected: "insufficient_quota_error" is NOT
  retryable (raised as a plain RuntimeError so with_retry's catch-all
  no-retry branch applies); any other 429 (e.g. "rate_limit_exceeded_error")
  is left to propagate as httpx.HTTPStatusError, which with_retry's default
  status-code classification already retries.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

import httpx

from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.retry import with_retry
from app.providers.base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "sarvam"
_SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


class SarvamTTSProvider(TTSProvider):
    """Primary TTS provider — Sarvam AI Bulbul v2."""

    def __init__(self) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.sarvam_api_key

    @with_retry(max_attempts=3)
    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* with Sarvam Bulbul v2.

        Args:
            text:     Narration text (one segment's script).
            voice_id: Sarvam speaker name (e.g. "meera").

        Returns:
            ``(audio_bytes, [])`` — Sarvam alignment data is not parsed into
            word timestamps in this story (see module docstring).
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _SARVAM_TTS_URL,
                    headers={"API-Subscription-Key": self._api_key},
                    json={"inputs": [text], "speaker": voice_id, "target_language_code": "en-IN"},
                )
                if response.status_code == 429:
                    body: dict[str, Any] = {}
                    with contextlib.suppress(Exception):
                        body = response.json()
                    error_code = (body.get("error") or {}).get("code", "")
                    if error_code == "insufficient_quota_error":
                        await record_failure(_PROVIDER_KEY)
                        raise RuntimeError(
                            f"Sarvam TTS insufficient_quota_error — not retryable: {body}"
                        )
                    # Any other 429 (e.g. rate_limit_exceeded_error) — let
                    # raise_for_status() raise the normal HTTPStatusError so
                    # with_retry's default 429-is-retryable path applies.
                response.raise_for_status()
                audio_bytes = response.content

            await record_success(_PROVIDER_KEY)
            return audio_bytes, []

        except RuntimeError:
            raise
        except Exception:
            await record_failure(_PROVIDER_KEY)
            raise
