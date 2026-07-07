"""
OpenAI Embeddings provider implementation.

Uses text-embedding-3-small (1536 dims) — the fixed embedding model for
TransformED AI.  Embeddings are generated ONCE at ingestion and never
regenerated for stored content (CLAUDE.md rule).
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.core.circuit_breaker import is_circuit_open, record_failure, record_success
from app.core.langfuse import get_langfuse
from app.core.retry import with_retry
from app.providers.base import EmbeddingsProvider

logger = logging.getLogger(__name__)

_PROVIDER_KEY = "openai"

# text-embedding-3-small pricing (USD per 1K tokens, as of June 2026)
_EMBED_COST_PER_1K_USD = 0.00002


class OpenAIEmbeddingsProvider(EmbeddingsProvider):
    """Production embeddings provider backed by OpenAI text-embedding-3-small."""

    def __init__(self, lesson_id: str | None = None) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.embedding_model
        self._langfuse = get_langfuse()
        self._lesson_id = lesson_id

    @with_retry(max_attempts=3)
    async def embed_texts(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], int]:
        """Embed *texts* using the configured OpenAI model.

        Args:
            texts: Up to 2048 non-empty strings per call (OpenAI limit).

        Returns:
            (embeddings, total_tokens) where embeddings[i] corresponds to texts[i].

        Raises:
            RuntimeError: If the circuit breaker is open for the OpenAI provider.
        """
        if await is_circuit_open(_PROVIDER_KEY):
            raise RuntimeError(
                f"Circuit breaker OPEN for provider '{_PROVIDER_KEY}' — embeddings call rejected"
            )

        trace = self._langfuse.trace(
            name="embed.texts",
            metadata={
                "model": self._model,
                "batch_size": len(texts),
                "lesson_id": self._lesson_id,
            },
        )
        generation = trace.generation(
            name="openai.embeddings",
            model=self._model,
            input=f"{len(texts)} texts",
        )

        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
            embeddings: list[list[float]] = [item.embedding for item in response.data]
            total_tokens: int = response.usage.total_tokens

            generation.end(
                output=f"{len(embeddings)} embeddings × {len(embeddings[0]) if embeddings else 0} dims",
                usage={"input": total_tokens, "output": 0},
            )

            await self._maybe_accumulate_cost(total_tokens)
            await record_success(_PROVIDER_KEY)
            return embeddings, total_tokens

        except Exception as exc:
            generation.end(level="ERROR", status_message=str(exc))
            await record_failure(_PROVIDER_KEY)
            raise

    async def _maybe_accumulate_cost(self, total_tokens: int) -> None:
        if self._lesson_id is None:
            return

        cost = total_tokens / 1000 * _EMBED_COST_PER_1K_USD

        from app.core.cost_tracker import accumulate_cost, check_ceiling

        total = await accumulate_cost(self._lesson_id, cost)
        if await check_ceiling(self._lesson_id):
            raise RuntimeError(
                f"Lesson {self._lesson_id} exceeded cost ceiling at ${total:.4f} — pipeline aborted"
            )
