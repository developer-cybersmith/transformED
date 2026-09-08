"""
OpenAI Whisper STT provider — voice teach-back transcription (Story F2-4).

Responsibilities
----------------
- Wraps the Whisper API (`audio.transcriptions.create`) with circuit breaker + retry.
- Reads model name from ``settings.stt_model`` — never hardcodes it.
- Returns (transcript_text, duration_seconds) so the caller can compute cost.
- Cost accumulation is the caller's responsibility (see service.py).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.retry import with_retry

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "openai_stt"


class WhisperProvider:
    """Async Whisper transcription provider backed by OpenAI."""

    def __init__(self, settings: Any) -> None:  # noqa: ANN401
        self._model: str = settings.stt_model
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=0,
            timeout=httpx.Timeout(120.0, connect=5.0),
        )

    async def transcribe(self, audio_bytes: bytes, filename: str) -> tuple[str, float]:
        """Transcribe audio and return (transcript, duration_seconds).

        Args:
            audio_bytes: Raw audio file contents (WAV, MP3, MP4, WEBM, etc.).
            filename: Original filename — Whisper uses the extension for format detection.

        Returns:
            (transcript text, duration in seconds from verbose_json)

        Raises:
            Exception: Any OpenAI API error, timeout, or circuit-breaker open.
        """

        @with_retry(max_attempts=3)
        async def _call() -> tuple[str, float]:
            if await is_circuit_open(_PROVIDER_KEY):
                raise CircuitOpenError(f"Circuit breaker open for {_PROVIDER_KEY!r}")
            import io

            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=audio_file,
                response_format="verbose_json",
            )
            text: str = response.text or ""
            duration: float = float(getattr(response, "duration", 0.0) or 0.0)
            return text, duration

        return await guard_breaker(_PROVIDER_KEY, _call)
