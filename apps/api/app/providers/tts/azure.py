"""
Azure Cognitive Services TTS provider implementation — fallback tier.

Responsibilities
----------------
- Implements TTSProvider using Azure Cognitive Services' Speech synthesis
  REST endpoint.
- Returns (audio_bytes, word_timestamps) tuples — timestamps always empty.
  Azure's basic synthesis endpoint used here does not return word-level
  alignment; slide-level timestamp mapping is out of scope for this story
  regardless (see Story 2-8's Dev Notes).
- Applies circuit breaker ("azure_tts" provider key) and retry decorator.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.retry import with_retry
from app.providers.base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "azure_tts"


class AzureTTSProvider(TTSProvider):
    """Fallback TTS provider — Azure Cognitive Services Speech."""

    def __init__(self) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.azure_tts_key
        self._region = settings.azure_tts_region

    @with_retry(max_attempts=3)
    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* with Azure Cognitive Services Speech.

        Args:
            text:     Narration text (one segment's script).
            voice_id: Azure neural voice name (e.g. "en-IN-NeerjaNeural").

        Returns:
            ``(audio_bytes, [])`` — see module docstring for why timestamps
            are always empty.
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected"
            )

        # 2026-07-15 review finding (Blind Hunter): voice_id was interpolated
        # unescaped into an XML attribute — every current call site passes a
        # fixed config value so it wasn't exploitable today, but synthesize()
        # is a public method with no validation on voice_id. Escape it the
        # same way as text so a future caller can't break out of the
        # attribute or inject SSML/XML elements via a bad voice_id.
        ssml = (
            f"<speak version='1.0' xml:lang='en-US'>"
            f"<voice name='{_escape_ssml(voice_id)}'>{_escape_ssml(text)}</voice>"
            f"</speak>"
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1",
                    headers={
                        "Ocp-Apim-Subscription-Key": self._api_key,
                        "Content-Type": "application/ssml+xml",
                        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                    },
                    content=ssml.encode("utf-8"),
                )
                response.raise_for_status()
                audio_bytes = response.content

            await record_success(_PROVIDER_KEY)
            return audio_bytes, []

        except Exception:
            await record_failure(_PROVIDER_KEY)
            raise


def _escape_ssml(text: str) -> str:
    """Escape characters that are structurally significant in SSML/XML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
