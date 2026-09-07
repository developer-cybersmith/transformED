"""Story 4-28 (Phase 2 P2-1) — LLMProvider.complete_with_meta().

Additive method: `complete()` (every existing pipeline node's call path) is
completely unchanged. `complete_with_meta()` is new, used only by tutor
Q&A, and returns (content, finish_reason, cost_usd) — the two pieces of
information `complete()`'s plain-str contract can't carry, which Story
4-28's own AC5/Scale & Load Q2 need: truncation visibility and a per-call
cost figure that does NOT depend on `lesson_id`/the $3.00 generation
ceiling (a different unit of work — one live question, not one lesson).

`_price_tokens()` is the pure pricing helper extracted from
`_maybe_accumulate_cost` (Story 2-33's fail-closed contract preserved
verbatim) so both the lesson-generation cost path and this new
lesson_id-free path share one pricing implementation, not two that could
silently drift apart.
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

pytestmark = pytest.mark.unit


def _chat_response(
    content: str = "hello", finish_reason: str = "stop", prompt: int = 100, completion: int = 50
) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = finish_reason
    resp.usage.prompt_tokens = prompt
    resp.usage.completion_tokens = completion
    return resp


def _provider_with_mocked_client(response: MagicMock) -> tuple[object, MagicMock]:
    from app.providers.llm.openai import OpenAILLMProvider

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    mod = "app.providers.llm.openai"
    patches = [
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
    ]
    for p in patches:
        p.start()
    # No lesson_id — the exact tutor Q&A construction shape (Story 4-28: never
    # accumulated against any lesson's cost ceiling).
    provider = OpenAILLMProvider(lesson_id=None)
    return provider, client


# ── complete_with_meta() — the real (content, finish_reason, cost) contract ────


@pytest.mark.asyncio
async def test_complete_with_meta_returns_content_finish_reason_and_cost() -> None:
    response = _chat_response(
        content="the answer", finish_reason="stop", prompt=1000, completion=500
    )
    provider, _client = _provider_with_mocked_client(response)

    content, finish_reason, cost_usd = await provider.complete_with_meta(
        [{"role": "user", "content": "hi"}], "gpt-4o"
    )

    assert content == "the answer"
    assert finish_reason == "stop"
    # gpt-4o: input $0.005/1k, output $0.015/1k (openai.py's _COST_PER_1K)
    expected = (1000 / 1000 * 0.005) + (500 / 1000 * 0.015)
    assert cost_usd == pytest.approx(expected)


@pytest.mark.asyncio
async def test_complete_with_meta_reports_length_truncation_not_indistinguishable_from_stop() -> (
    None
):
    """Story 4-28 Scale & Load Q2's exact concern: a max_tokens-truncated
    answer must be visible on the record, not silently treated as complete."""
    response = _chat_response(finish_reason="length")
    provider, _client = _provider_with_mocked_client(response)

    _content, finish_reason, _cost = await provider.complete_with_meta(
        [{"role": "user", "content": "hi"}], "gpt-4o"
    )

    assert finish_reason == "length"


@pytest.mark.asyncio
async def test_complete_with_meta_never_calls_cost_tracker_accumulate() -> None:
    """The whole point of the lesson_id=None construction: tutor Q&A spend
    must never be accumulated against (or checked against) any lesson's
    $3.00 generation ceiling — a different unit of work."""
    response = _chat_response()
    provider, _client = _provider_with_mocked_client(response)

    with patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock()) as mock_accumulate:
        await provider.complete_with_meta([{"role": "user", "content": "hi"}], "gpt-4o")

    mock_accumulate.assert_not_called()


@pytest.mark.asyncio
async def test_complete_with_meta_missing_usage_defaults_to_zero_tokens_not_a_crash() -> None:
    response = _chat_response()
    response.usage = None
    provider, _client = _provider_with_mocked_client(response)

    _content, _finish_reason, cost_usd = await provider.complete_with_meta(
        [{"role": "user", "content": "hi"}], "gpt-4o"
    )

    assert cost_usd == 0.0


@pytest.mark.asyncio
async def test_complete_unchanged_still_returns_a_bare_string() -> None:
    """complete() itself (every existing pipeline node's call path) must be
    completely unaffected by this addition."""
    response = _chat_response(content="plain text")
    provider, _client = _provider_with_mocked_client(response)

    with (
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0)),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        result = await provider.complete([{"role": "user", "content": "hi"}], "gpt-4o")

    assert result == "plain text"
    assert isinstance(result, str)


# ── _price_tokens() — pure pricing helper, no provider/client needed ───────────


def test_price_tokens_known_model_matches_cost_per_1k_table() -> None:
    from app.providers.llm.openai import _price_tokens

    input_cost, output_cost, total = _price_tokens("gpt-4o-mini", 1000, 500)

    assert input_cost == pytest.approx(1000 / 1000 * 0.000150)
    assert output_cost == pytest.approx(500 / 1000 * 0.000600)
    assert total == pytest.approx(input_cost + output_cost)


def test_price_tokens_unpriced_model_fails_closed_at_most_expensive_known_rate() -> None:
    """Story 2-33's fail-closed contract, preserved through the extraction:
    an unpriced model is charged at the most expensive KNOWN rate, never
    silently skipped/free."""
    from app.providers.llm.openai import _COST_PER_1K, _price_tokens

    input_cost, output_cost, _total = _price_tokens("claude-3-5-sonnet-not-in-table", 1000, 1000)

    max_input_rate = max(p["input"] for p in _COST_PER_1K.values())
    max_output_rate = max(p["output"] for p in _COST_PER_1K.values())
    assert input_cost == pytest.approx(1000 / 1000 * max_input_rate)
    assert output_cost == pytest.approx(1000 / 1000 * max_output_rate)


def test_price_tokens_negative_counts_clamped_not_negative_cost() -> None:
    from app.providers.llm.openai import _price_tokens

    _input_cost, _output_cost, total = _price_tokens("gpt-4o", -100, -50)

    assert total == 0.0


def test_price_tokens_none_counts_treated_as_zero_not_a_crash() -> None:
    from app.providers.llm.openai import _price_tokens

    input_cost, output_cost, total = _price_tokens("gpt-4o", None, None)

    assert input_cost == 0.0
    assert output_cost == 0.0
    assert total == 0.0
