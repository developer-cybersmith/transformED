"""
ElevenLabs TTS provider implementation.

Responsibilities
----------------
- Implements TTSProvider using the ``elevenlabs`` SDK.
- Returns (audio_bytes, word_timestamps) tuples.
- Applies circuit breaker (``elevenlabs`` provider key) and retry decorator.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.retry import with_retry
from app.providers.base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "elevenlabs"


class ElevenLabsTTSProvider(TTSProvider):
    """Production TTS provider backed by ElevenLabs."""

    def __init__(self) -> None:
        from elevenlabs.client import ElevenLabs  # type: ignore[import]

        from app.config import get_settings

        settings = get_settings()
        self._client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    @with_retry(max_attempts=3)
    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* with ElevenLabs and return audio + word timestamps.

        Uses the ``with_timestamps`` endpoint to get alignment data so the
        slide-sync renderer can lip-sync text to the avatar.

        Args:
            text:     Narration text (one segment / slide worth).
            voice_id: ElevenLabs voice ID string.

        Returns:
            ``(audio_bytes, timestamps)`` where timestamps is a list of
            ``{"word": str, "start": float, "end": float}`` dicts.
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — call rejected")

        try:
            # Use the alignment endpoint for word-level timestamps
            response = self._client.text_to_speech.convert_with_timestamps(
                voice_id=voice_id,
                text=text,
                model_id="eleven_turbo_v2_5",
                output_format="mp3_44100_128",
            )

            audio_bytes: bytes = response.audio_base64  # type: ignore[attr-defined]
            if isinstance(audio_bytes, str):
                import base64
                audio_bytes = base64.b64decode(audio_bytes)

            # Parse alignment into standard timestamp dicts
            timestamps: list[dict[str, Any]] = []
            if hasattr(response, "alignment") and response.alignment:  # type: ignore[attr-defined]
                chars = response.alignment.get("characters", [])  # type: ignore[union-attr]
                starts = response.alignment.get("character_start_times_seconds", [])  # type: ignore[union-attr]
                ends = response.alignment.get("character_end_times_seconds", [])  # type: ignore[union-attr]

                # Build word-level timestamps by aggregating character spans
                timestamps = _chars_to_word_timestamps(chars, starts, ends)

            await record_success(_PROVIDER_KEY)
            return audio_bytes, timestamps

        except Exception:
            await record_failure(_PROVIDER_KEY)
            raise


def _chars_to_word_timestamps(
    chars: list[str],
    starts: list[float],
    ends: list[float],
) -> list[dict[str, Any]]:
    """Aggregate character-level alignment into word-level timestamps."""
    timestamps: list[dict[str, Any]] = []
    current_word: list[str] = []
    word_start: float | None = None
    word_end: float = 0.0

    for char, start, end in zip(chars, starts, ends, strict=False):
        if char == " ":
            if current_word and word_start is not None:
                timestamps.append({
                    "word": "".join(current_word),
                    "start": word_start,
                    "end": word_end,
                })
            current_word = []
            word_start = None
        else:
            if word_start is None:
                word_start = start
            current_word.append(char)
            word_end = end

    # Flush last word
    if current_word and word_start is not None:
        timestamps.append({
            "word": "".join(current_word),
            "start": word_start,
            "end": word_end,
        })

    return timestamps
