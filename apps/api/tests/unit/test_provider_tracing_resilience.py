"""
AC-3 (Story 2-0) — observability failures must NEVER fail the pipeline.

Behavioral proof of the never-fail clause for the OpenAI providers:
a broken Langfuse client (raising at start/update/end), or get_langfuse
itself raising at construction, must not prevent the provider from
returning results, recording circuit-breaker success, or accumulating
cost. Conversely, a real OpenAI failure must propagate UNMASKED —
tracing exceptions never replace it.

OpenAI, Langfuse, circuit breaker, and cost tracker are fully mocked —
no network calls (tests/conftest.py stubs sys.modules['openai']).
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# tests/conftest.py stubs sys.modules['openai'] only; the LLM provider also does
# `from openai.types.chat import ChatCompletion` — stub the submodules too so
# app.providers.llm.openai imports without a real openai install.
_openai_stub = sys.modules.setdefault("openai", MagicMock())
_openai_types_stub = sys.modules.setdefault("openai.types", MagicMock())
sys.modules.setdefault("openai.types.chat", _openai_types_stub.chat)

FAKE_LESSON_ID = "55555555-5555-5555-5555-555555555555"
_FAKE_EMBEDDING = [0.1] * 1536


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_embeddings_response(n: int = 2, total_tokens: int = 42) -> MagicMock:
    resp = MagicMock()
    items = []
    for _ in range(n):
        item = MagicMock()
        item.embedding = list(_FAKE_EMBEDDING)
        items.append(item)
    resp.data = items
    resp.usage.total_tokens = total_tokens
    return resp


def _make_chat_response(content: str = "hello") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


def _broken_langfuse_client(
    start_raises: bool = False,
    update_raises: bool = False,
    end_raises: bool = False,
) -> MagicMock:
    """Langfuse client mock whose tracing surface raises where requested."""
    client = MagicMock()
    if start_raises:
        client.start_observation.side_effect = RuntimeError("langfuse: start down")
    else:
        generation = MagicMock()
        if update_raises:
            generation.update.side_effect = RuntimeError("langfuse: update down")
        if end_raises:
            generation.end.side_effect = RuntimeError("langfuse: end down")
        client.start_observation.return_value = generation
    return client


def _embed_patches(
    langfuse: Any,
    openai_response: MagicMock | None = None,
    openai_error: Exception | None = None,
) -> tuple[Any, ...]:
    """Patch set for app.providers.embeddings.openai module-level imports.

    ``langfuse`` may be a client mock OR an Exception instance (then
    get_langfuse itself raises at provider construction).
    """
    client = MagicMock()
    if openai_error is not None:
        client.embeddings.create = AsyncMock(side_effect=openai_error)
    else:
        client.embeddings.create = AsyncMock(
            return_value=openai_response or _make_embeddings_response()
        )

    if isinstance(langfuse, Exception):
        get_langfuse = MagicMock(side_effect=langfuse)
    else:
        get_langfuse = MagicMock(return_value=langfuse)

    mod = "app.providers.embeddings.openai"
    return (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", get_langfuse),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch(f"{mod}.record_success", new=AsyncMock()),
        patch(f"{mod}.record_failure", new=AsyncMock()),
    )


def _llm_patches(
    langfuse: Any,
    openai_response: MagicMock | None = None,
    openai_error: Exception | None = None,
) -> tuple[Any, ...]:
    """Patch set for app.providers.llm.openai module-level imports."""
    client = MagicMock()
    if openai_error is not None:
        client.chat.completions.create = AsyncMock(side_effect=openai_error)
    else:
        client.chat.completions.create = AsyncMock(
            return_value=openai_response or _make_chat_response()
        )

    if isinstance(langfuse, Exception):
        get_langfuse = MagicMock(side_effect=langfuse)
    else:
        get_langfuse = MagicMock(return_value=langfuse)

    mod = "app.providers.llm.openai"
    return (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", get_langfuse),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch(f"{mod}.record_success", new=AsyncMock()),
        patch(f"{mod}.record_failure", new=AsyncMock()),
    )


# ── Embeddings provider ───────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_succeeds_when_start_observation_raises() -> None:
    """(a) Langfuse start_observation raising must not fail embed_texts;
    record_success is still recorded on the circuit breaker."""
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    langfuse = _broken_langfuse_client(start_raises=True)
    p1, p2, p3, p4, p5 = _embed_patches(langfuse)
    with p1, p2, p3, p4 as record_success, p5:
        provider = OpenAIEmbeddingsProvider()
        embeddings, total_tokens = await provider.embed_texts(["a", "b"])

    assert embeddings == [_FAKE_EMBEDDING, _FAKE_EMBEDDING]
    assert total_tokens == 42
    langfuse.start_observation.assert_called_once()  # tracing attempted, failed, ignored
    record_success.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_succeeds_when_generation_update_and_end_raise() -> None:
    """(b) generation.update/end raising must not fail embed_texts."""
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    langfuse = _broken_langfuse_client(update_raises=True, end_raises=True)
    p1, p2, p3, p4, p5 = _embed_patches(langfuse)
    with p1, p2, p3, p4 as record_success, p5:
        provider = OpenAIEmbeddingsProvider()
        embeddings, total_tokens = await provider.embed_texts(["a", "b"])

    assert embeddings == [_FAKE_EMBEDDING, _FAKE_EMBEDDING]
    assert total_tokens == 42
    generation = langfuse.start_observation.return_value
    generation.update.assert_called_once()
    generation.end.assert_called_once()
    record_success.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_provider_constructs_when_get_langfuse_raises() -> None:
    """(c) get_langfuse raising at construction (bad LANGFUSE_* env) must not
    crash the provider — it degrades to no tracing and the call still succeeds."""
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    p1, p2, p3, p4, p5 = _embed_patches(RuntimeError("bad LANGFUSE_* env"))
    with p1, p2, p3, p4 as record_success, p5:
        provider = OpenAIEmbeddingsProvider()  # must NOT raise
        assert provider._langfuse is None
        embeddings, total_tokens = await provider.embed_texts(["a", "b"])

    assert embeddings == [_FAKE_EMBEDDING, _FAKE_EMBEDDING]
    assert total_tokens == 42
    record_success.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_openai_error_propagates_unmasked_with_broken_tracer() -> None:
    """(d) A real OpenAI failure propagates as-is even when every tracing call
    raises — the tracing exception never replaces it. Circuit breaker records
    the failure."""
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    langfuse = _broken_langfuse_client(update_raises=True, end_raises=True)
    p1, p2, p3, p4, p5 = _embed_patches(langfuse, openai_error=ValueError("openai exploded"))
    with p1, p2, p3, p4, p5 as record_failure:
        provider = OpenAIEmbeddingsProvider()
        with pytest.raises(ValueError, match="openai exploded"):
            await provider.embed_texts(["a"])

    record_failure.assert_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_cost_accumulation_runs_when_tracing_fully_broken() -> None:
    """(e) Cost accumulation reads response.usage directly — it must still run
    when the Langfuse client never even constructed."""
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    accumulate = AsyncMock(return_value=0.01)
    ceiling = AsyncMock(return_value=False)

    p1, p2, p3, p4, p5 = _embed_patches(
        RuntimeError("bad LANGFUSE_* env"),
        openai_response=_make_embeddings_response(n=1, total_tokens=1000),
    )
    with (
        p1,
        p2,
        p3,
        p4,
        p5,
        patch("app.core.cost_tracker.accumulate_cost", accumulate),
        patch("app.core.cost_tracker.check_ceiling", ceiling),
    ):
        provider = OpenAIEmbeddingsProvider(lesson_id=FAKE_LESSON_ID)
        await provider.embed_texts(["a"])

    accumulate.assert_awaited_once()
    lesson_id, cost = accumulate.await_args.args
    assert lesson_id == FAKE_LESSON_ID
    assert cost == pytest.approx(1000 / 1000 * 0.00002)
    ceiling.assert_awaited_once_with(FAKE_LESSON_ID)


# ── LLM provider (same AC-3 clause) ───────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_complete_succeeds_when_tracer_raises_everywhere() -> None:
    """(a)+(b) for the LLM provider: raising start/update/end must not fail
    complete(); record_success still recorded."""
    from app.providers.llm.openai import OpenAILLMProvider

    langfuse = _broken_langfuse_client(start_raises=True)
    p1, p2, p3, p4, p5 = _llm_patches(langfuse)
    with p1, p2, p3, p4 as record_success, p5:
        provider = OpenAILLMProvider()
        content = await provider.complete([{"role": "user", "content": "hi"}], model="gpt-4o-mini")

    assert content == "hello"
    record_success.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_provider_constructs_when_get_langfuse_raises() -> None:
    """(c) for the LLM provider: construction survives a broken Langfuse env
    and cost accumulation (e) still runs without any tracer."""
    from app.providers.llm.openai import OpenAILLMProvider

    accumulate = AsyncMock(return_value=0.01)
    ceiling = AsyncMock(return_value=False)

    p1, p2, p3, p4, p5 = _llm_patches(RuntimeError("bad LANGFUSE_* env"))
    with (
        p1,
        p2,
        p3,
        p4,
        p5,
        patch("app.core.cost_tracker.accumulate_cost", accumulate),
        patch("app.core.cost_tracker.check_ceiling", ceiling),
    ):
        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        assert provider._langfuse is None
        content = await provider.complete([{"role": "user", "content": "hi"}], model="gpt-4o-mini")

    assert content == "hello"
    accumulate.assert_awaited_once()
    lesson_id, cost = accumulate.await_args.args
    assert lesson_id == FAKE_LESSON_ID
    # gpt-4o-mini: 10 input + 5 output tokens
    assert cost == pytest.approx(10 / 1000 * 0.000150 + 5 / 1000 * 0.000600)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_openai_error_propagates_unmasked_with_broken_tracer() -> None:
    """(d) for the LLM provider: OpenAI's own exception propagates unmasked."""
    from app.providers.llm.openai import OpenAILLMProvider

    langfuse = _broken_langfuse_client(update_raises=True, end_raises=True)
    p1, p2, p3, p4, p5 = _llm_patches(langfuse, openai_error=ValueError("openai exploded"))
    with p1, p2, p3, p4, p5 as record_failure:
        provider = OpenAILLMProvider()
        with pytest.raises(ValueError, match="openai exploded"):
            await provider.complete([{"role": "user", "content": "hi"}], model="gpt-4o-mini")

    record_failure.assert_awaited()
