"""
Abstract base classes for all AI provider integrations.

Architecture rule (PRD §5): No business logic layer may call an AI provider
directly.  All AI calls must go through a concrete implementation of one of
these abstract classes.

Provider types
--------------
LLMProvider     Text generation (chat completions, structured output)
TTSProvider     Text-to-speech synthesis
ImageProvider   Image generation
AvatarProvider  Pre-cached HeyGen avatar clips (no live per-lesson calls)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract interface for large-language-model completions."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> str:
        """Return a plain-text completion.

        Args:
            messages:  OpenAI-style message list, e.g.
                       ``[{"role": "user", "content": "Hello"}]``.
            model:     Model identifier string (e.g. ``"gpt-4o"``).
            **kwargs:  Provider-specific overrides (temperature, max_tokens…).

        Returns:
            The assistant's reply as a plain string.
        """
        ...

    @abstractmethod
    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_format: type,
        **kwargs: Any,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """Return a completion parsed into a Pydantic model.

        Args:
            messages:        OpenAI-style message list.
            model:           Model identifier string.
            response_format: A Pydantic ``BaseModel`` subclass.  The provider
                             must use structured-output mode (JSON schema) to
                             guarantee the response can be parsed into this type.
            **kwargs:        Provider-specific overrides.

        Returns:
            An instance of *response_format*.
        """
        ...


class TTSProvider(ABC):
    """Abstract interface for text-to-speech synthesis."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Synthesise *text* into audio and return word-level timestamps.

        Args:
            text:     The text to synthesise.
            voice_id: Provider-specific voice identifier.

        Returns:
            A 2-tuple of:
            - ``bytes``: Raw audio data (MP3 or PCM depending on provider).
            - ``list[dict]``: Word-level timestamp dicts, each with at minimum
              ``{"word": str, "start": float, "end": float}`` keys (seconds).
        """
        ...


class ImageProvider(ABC):
    """Abstract interface for AI image generation."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
    ) -> str:
        """Generate an image from *prompt* and return its URL.

        Args:
            prompt: Natural-language image description.
            size:   Dimensions string, e.g. ``"1024x1024"``, ``"1792x1024"``.

        Returns:
            A URL pointing to the generated image.  May be a temporary CDN URL
            that should be downloaded and re-uploaded to Supabase Storage.
        """
        ...


class EmbeddingsProvider(ABC):
    """Abstract interface for text embedding generation.

    Embeddings are computed ONCE at ingestion and never regenerated for stored
    content (CLAUDE.md rule).  Phase 2 RAG tutor query-embedding is permitted
    (embed the student's question at query time — not stored content).
    """

    @abstractmethod
    async def embed_texts(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], int]:
        """Embed a batch of texts and return their vector representations.

        Args:
            texts: List of text strings to embed (max 2048 per call for OpenAI).

        Returns:
            A 2-tuple of:
            - ``list[list[float]]``: One embedding vector per input text.
            - ``int``: Total tokens consumed (for cost tracking).
        """
        ...


class AvatarProvider(ABC):
    """Abstract interface for avatar intro/outro video clips.

    Per PRD §8 (Option 6 cached approach): HeyGen clips are pre-generated
    and stored in Supabase Storage.  There are NO live HeyGen API calls per
    lesson.  This provider simply returns signed URLs to the cached clips.
    """

    @abstractmethod
    async def get_cached_clip(self, clip_type: str) -> str:
        """Return a signed Supabase Storage URL for a cached avatar clip.

        Args:
            clip_type: One of ``"intro"`` or ``"outro"`` (may be extended to
                       include specific module variants in future sprints).

        Returns:
            A time-limited signed URL to the cached MP4 clip in Supabase Storage.
        """
        ...
