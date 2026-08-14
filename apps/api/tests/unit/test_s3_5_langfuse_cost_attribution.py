"""Story 3-56 (S3-5) — pipeline cost attribution in Langfuse.

The gap: `providers/llm/openai.py` (`complete()` and `complete_structured()`) and
`providers/embeddings/openai.py` each compute a real dollar cost in
`_maybe_accumulate_cost` and pass it to `cost_tracker.accumulate_cost()`, but never
write that value back to the Langfuse `generation` span — only `usage_details` (raw
token counts) reaches Langfuse, never `cost_details` (the dollar figure). The other
4 providers with real per-call cost (Sarvam TTS, Azure TTS, Imagen, GPT Image) already
call `generation.update(..., cost_details={"input": cost})` — this file asserts the
two LLM methods and the embeddings call now do the same, extending that established
pattern rather than inventing a new one.

LLM cost genuinely splits by token type (input vs output priced differently), so
`cost_details` should carry BOTH keys, mirroring `usage_details`'s existing
input/output split — more granular than the single-key pattern the other 4
providers use (correct there, since none of them have split-rate billing).
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:  # pragma: no cover — the real SDK is present in every supported env
    import openai  # noqa: F401
except ImportError:  # pragma: no cover
    _openai_stub = sys.modules.setdefault("openai", MagicMock())
    _openai_types_stub = sys.modules.setdefault("openai.types", MagicMock())
    sys.modules.setdefault("openai.types.chat", _openai_types_stub.chat)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

FAKE_LESSON_ID = "88888888-8888-8888-8888-888888888888"


def _working_langfuse_client() -> tuple[MagicMock, MagicMock]:
    """A Langfuse client whose start_observation returns a live generation mock."""
    client = MagicMock()
    generation = MagicMock()
    client.start_observation.return_value = generation
    return client, generation


def _chat_response(prompt: int = 1000, completion: int = 500) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "hello"
    resp.usage.prompt_tokens = prompt
    resp.usage.completion_tokens = completion
    return resp


def _structured_response(prompt: int = 1000, completion: int = 500) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.parsed = MagicMock()
    resp.usage.prompt_tokens = prompt
    resp.usage.completion_tokens = completion
    return resp


def _embeddings_response(total_tokens: int = 2000) -> MagicMock:
    resp = MagicMock()
    item = MagicMock()
    item.embedding = [0.1] * 1536
    resp.data = [item]
    resp.usage.total_tokens = total_tokens
    return resp


# ── complete() — cost_details on the generation span ─────────────────────────


async def test_complete_records_cost_details_matching_priced_rates() -> None:
    from app.providers.llm.openai import OpenAILLMProvider

    langfuse, generation = _working_langfuse_client()
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_chat_response(1000, 500))

    mod = "app.providers.llm.openai"
    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=langfuse)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0)),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o-mini")

    # gpt-4o-mini: input $0.000150/1k, output $0.000600/1k (openai.py's _COST_PER_1K)
    expected_input_cost = 1000 / 1000 * 0.000150
    expected_output_cost = 500 / 1000 * 0.000600

    generation.update.assert_any_call(
        cost_details={
            "input": pytest.approx(expected_input_cost),
            "output": pytest.approx(expected_output_cost),
        }
    )


async def test_complete_structured_records_cost_details_matching_priced_rates() -> None:
    from pydantic import BaseModel

    from app.providers.llm.openai import OpenAILLMProvider

    class _Out(BaseModel):
        value: str

    langfuse, generation = _working_langfuse_client()
    client = MagicMock()
    client.beta.chat.completions.parse = AsyncMock(return_value=_structured_response(2000, 1000))

    mod = "app.providers.llm.openai"
    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=langfuse)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0)),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        await provider.complete_structured([{"role": "user", "content": "hi"}], "gpt-4o", _Out)

    # gpt-4o: input $0.005/1k, output $0.015/1k
    expected_input_cost = 2000 / 1000 * 0.005
    expected_output_cost = 1000 / 1000 * 0.015

    generation.update.assert_any_call(
        cost_details={
            "input": pytest.approx(expected_input_cost),
            "output": pytest.approx(expected_output_cost),
        }
    )


async def test_complete_cost_details_sum_matches_accumulated_cost() -> None:
    """cost_details (Langfuse-visible) must be arithmetically consistent with the
    real dollar amount handed to cost_tracker.accumulate_cost — the two numbers
    are meant to be cross-checkable in the Langfuse UI, not independently
    computed and liable to silently disagree."""
    from app.providers.llm.openai import OpenAILLMProvider

    langfuse, generation = _working_langfuse_client()
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_chat_response(1000, 500))
    accumulate = AsyncMock(return_value=0.0)

    mod = "app.providers.llm.openai"
    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=langfuse)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("app.core.cost_tracker.accumulate_cost", new=accumulate),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o-mini")

    accumulated_cost = accumulate.await_args.args[1]

    cost_details_call = next(
        c for c in generation.update.call_args_list if "cost_details" in c.kwargs
    )
    traced_total = (
        cost_details_call.kwargs["cost_details"]["input"]
        + cost_details_call.kwargs["cost_details"]["output"]
    )
    assert traced_total == pytest.approx(accumulated_cost), (
        f"Langfuse-visible cost ({traced_total}) must equal the real accumulated "
        f"cost ({accumulated_cost}) — they must never silently disagree."
    )


# ── embed_texts() — cost_details on the generation span ──────────────────────


async def test_embed_records_cost_details_matching_priced_rate() -> None:
    from app.providers.embeddings.openai import OpenAIEmbeddingsProvider

    langfuse, generation = _working_langfuse_client()
    client = MagicMock()
    client.embeddings.create = AsyncMock(return_value=_embeddings_response(2000))

    mod = "app.providers.embeddings.openai"
    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=langfuse)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0)),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        provider = OpenAIEmbeddingsProvider(lesson_id=FAKE_LESSON_ID)
        await provider.embed_texts(["hello world"])

    # text-embedding-3-small rate: _EMBED_COST_PER_1K_USD = 0.00002
    expected_cost = 2000 / 1000 * 0.00002

    generation.update.assert_any_call(cost_details={"input": pytest.approx(expected_cost)})
