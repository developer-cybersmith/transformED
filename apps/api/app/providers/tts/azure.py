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
from langfuse import Langfuse

from app.core.circuit_breaker import CircuitOpenError, guard_breaker, is_circuit_open
from app.core.langfuse import deterministic_trace_context, get_langfuse, safe_trace
from app.core.retry import with_retry
from app.providers.base import TTSProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "azure_tts"

# Azure Cognitive Services TTS pricing (USD per character) — same figure
# tts_node's own cost-tracking uses; see sarvam.py's COST_PER_CHAR for why
# this lives here rather than as a private duplicate in graph.py.
COST_PER_CHAR = 0.000016


class AzureTTSProvider(TTSProvider):
    """Fallback TTS provider — Azure Cognitive Services Speech."""

    def __init__(self, lesson_id: str | None = None) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._api_key = settings.azure_tts_key
        self._region = settings.azure_tts_region
        self._lesson_id = lesson_id
        self._langfuse: Langfuse | None
        try:
            self._langfuse = get_langfuse()
        except Exception:
            logger.warning(
                "Langfuse init failed — tracing disabled for AzureTTSProvider",
                exc_info=True,
            )
            self._langfuse = None

    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* with Azure Speech, recording exactly one breaker
        outcome per logical call (Story 2-32 AC-3).

        Like Sarvam, this provider's httpx errors were always classified, so it
        always retried and always recorded `max_attempts` failures for one
        logical call — a pre-existing defect the accounting fix also closes.
        """
        return await guard_breaker(_PROVIDER_KEY, lambda: self._synthesize_inner(text, voice_id))

    @with_retry(max_attempts=3)
    async def _synthesize_inner(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Retried body of `synthesize`. Records NO breaker outcome.

        Args:
            text:     Narration text (one segment's script).
            voice_id: Azure neural voice name (e.g. "en-IN-NeerjaNeural").

        Returns:
            ``(audio_bytes, [])`` — see module docstring for why timestamps
            are always empty.
        """
        # Checked on EVERY attempt (Story 2-32 AC-4).
        if await is_circuit_open(_PROVIDER_KEY):
            raise CircuitOpenError(
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

        # settings.azure_tts_key is typed Optional; coerce to str so the header
        # map is dict[str, str]. A configured Azure fallback always has a key,
        # so this is types-only — the same header value is sent at runtime.
        api_key = self._api_key or ""

        generation = None
        langfuse = self._langfuse
        if langfuse is not None:
            generation = safe_trace(
                lambda: langfuse.start_observation(
                    # Same name as sarvam.py's primary observation — see
                    # that file's comment for why.
                    name="synthesize-speech",
                    as_type="generation",
                    model="azure-neural-tts",
                    input=f"{len(text)} chars, voice={voice_id}",
                    metadata={"voice_id": voice_id, "lesson_id": self._lesson_id},
                    trace_context=deterministic_trace_context(langfuse, self._lesson_id),
                )
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1",
                    headers={
                        "Ocp-Apim-Subscription-Key": api_key,
                        "Content-Type": "application/ssml+xml",
                        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                    },
                    content=ssml.encode("utf-8"),
                )
                response.raise_for_status()
                audio_bytes = response.content

            if generation is not None:
                cost = len(text) * COST_PER_CHAR
                safe_trace(
                    lambda: generation.update(
                        output=f"{len(audio_bytes)} bytes audio",
                        usage_details={"characters": len(text)},
                        cost_details={"input": cost},
                    )
                )

            return audio_bytes, []

        except Exception as exc:
            if generation is not None:
                error_message = str(exc)
                safe_trace(lambda: generation.update(level="ERROR", status_message=error_message))
            raise

        finally:
            if generation is not None:
                safe_trace(generation.end)


def _escape_ssml(text: str) -> str:
    """Escape characters that are structurally significant in SSML/XML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
