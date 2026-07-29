"""Story 2-33: an unpriced model must not switch the $3.00 ceiling off.

Why this file exists
--------------------
`_maybe_accumulate_cost` used to bail out before calling `accumulate_cost`
whenever the model was missing from `_COST_PER_1K`:

    pricing = _COST_PER_1K.get(model)
    if pricing is None:
        logger.warning("No pricing data for model '%s' — cost not tracked", model)
        return

The lesson's running total therefore stayed at $0.00, and `check_ceiling` —
which compares that total against `max_lesson_cost_usd` — never fired. An
unpriced model spent without limit.

The price table holds two models. CLAUDE.md's evaluation-candidate list names
four, and CLAUDE.md mandates that swapping models is an env var change only. So
the model-evaluation sprint the PRD asks for is precisely what disabled cost
tracking, signalled by one WARNING line.

Fail closed: charge the most expensive KNOWN rate, log at ERROR, complete the
lesson (PRD §14 — "downshift ... complete lesson, flag in admin").
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

FAKE_LESSON_ID = "77777777-7777-7777-7777-777777777777"
UNPRICED_MODEL = "claude-3-5-sonnet"  # a real CLAUDE.md evaluation candidate, absent from the table


def _chat_response(
    content: str = "hello",
    prompt: int | None = 1000,
    completion: int | None = 500,
) -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    resp.usage.prompt_tokens = prompt
    resp.usage.completion_tokens = completion
    return resp


def _provider_patches(
    *,
    accumulate: AsyncMock,
    ceiling: AsyncMock,
    response: MagicMock | None = None,
) -> tuple[Any, ...]:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response or _chat_response())
    mod = "app.providers.llm.openai"
    return (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
        patch("app.core.cost_tracker.accumulate_cost", new=accumulate),
        patch("app.core.cost_tracker.check_ceiling", new=ceiling),
    )


async def _run(
    model: str,
    *,
    accumulate: AsyncMock,
    ceiling: AsyncMock,
    response: MagicMock | None = None,
) -> Any:  # noqa: ANN401
    from app.providers.llm.openai import OpenAILLMProvider

    p = _provider_patches(accumulate=accumulate, ceiling=ceiling, response=response)
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        return await provider.complete([{"role": "user", "content": "hi"}], model)


# ── Real cost-tracking helpers (review round 2, D16) ────────────────────────
#
# Everything above stubs `accumulate_cost`/`check_ceiling`, which is right for
# asserting WHAT was charged. It is wrong for asserting that a charge TRIPS the
# ceiling: with `check_ceiling` hardcoded, that assertion is about the `if`, not
# about the arithmetic. These helpers run the real functions against fakeredis.

try:  # fakeredis[aioredis] is a dev dependency; skip rather than fail without it.
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis

    _HAS_FAKEREDIS = True
except ImportError:  # pragma: no cover - depends on environment
    _HAS_FAKEREDIS = False


def _fake_redis() -> Any:  # noqa: ANN401
    return FakeRedis(server=FakeServer(), decode_responses=True)


def _cost_key(lesson_id: str) -> str:
    from app.core.cost_tracker import _key

    return _key(lesson_id)


async def _seed_cost(redis: Any, lesson_id: str, amount: float) -> None:  # noqa: ANN401
    await redis.set(_cost_key(lesson_id), str(amount))


async def _read_cost(redis: Any, lesson_id: str) -> float:  # noqa: ANN401
    raw = await redis.get(_cost_key(lesson_id))
    return float(raw) if raw is not None else 0.0


async def _run_with_real_cost_tracking(model: str) -> Any:  # noqa: ANN401
    """Same call as `_run`, but with accumulate_cost/check_ceiling UNSTUBBED.

    The caller patches `app.core.cost_tracker.get_redis`, so the real functions
    run their real arithmetic against a fake store.
    """
    from app.providers.llm.openai import OpenAILLMProvider

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_chat_response())
    mod = "app.providers.llm.openai"
    with (
        patch(f"{mod}.AsyncOpenAI", return_value=client),
        patch(f"{mod}.get_langfuse", MagicMock(return_value=None)),
        patch(f"{mod}.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.core.circuit_breaker.record_success", new=AsyncMock()),
        patch("app.core.circuit_breaker.record_failure", new=AsyncMock()),
    ):
        provider = OpenAILLMProvider(lesson_id=FAKE_LESSON_ID)
        return await provider.complete([{"role": "user", "content": "hi"}], model)


# ── AC-1: an unpriced model is still charged ─────────────────────────────────


async def test_unpriced_model_still_accumulates_cost() -> None:
    """THE bug. Before this story the assertion below saw zero calls."""
    accumulate = AsyncMock(return_value=0.5)
    ceiling = AsyncMock(return_value=False)

    await _run(UNPRICED_MODEL, accumulate=accumulate, ceiling=ceiling)

    accumulate.assert_awaited_once()
    charged = accumulate.await_args.args[1]
    assert charged > 0, f"an unpriced model must still be charged, got {charged}"


async def test_priced_model_is_unaffected() -> None:
    """The fix must not disturb the normal path."""
    from app.providers.llm.openai import _COST_PER_1K

    accumulate = AsyncMock(return_value=0.1)
    ceiling = AsyncMock(return_value=False)

    await _run("gpt-4o-mini", accumulate=accumulate, ceiling=ceiling)

    pricing = _COST_PER_1K["gpt-4o-mini"]
    expected = (1000 / 1000 * pricing["input"]) + (500 / 1000 * pricing["output"])
    assert accumulate.await_args.args[1] == pytest.approx(expected)


# ── AC-2: the fallback is conservative and derived ───────────────────────────


async def test_fallback_rate_is_the_most_expensive_known_rate() -> None:
    """Over-charging is the SAFE direction — it makes the ceiling fire earlier,
    never later. Derived from the table so it cannot drift when a pricier model
    is priced later; a hardcoded literal would silently stop being conservative.
    """
    from app.providers.llm.openai import _COST_PER_1K

    accumulate = AsyncMock(return_value=0.5)
    await _run(UNPRICED_MODEL, accumulate=accumulate, ceiling=AsyncMock(return_value=False))

    max_in = max(p["input"] for p in _COST_PER_1K.values())
    max_out = max(p["output"] for p in _COST_PER_1K.values())
    expected = (1000 / 1000 * max_in) + (500 / 1000 * max_out)

    assert accumulate.await_args.args[1] == pytest.approx(expected)


async def test_fallback_is_at_least_every_known_model_rate() -> None:
    """Property form of AC-2: whatever the table contains, the unpriced charge is
    never cheaper than charging that same call on any priced model."""
    from app.providers.llm.openai import _COST_PER_1K

    accumulate = AsyncMock(return_value=0.5)
    await _run(UNPRICED_MODEL, accumulate=accumulate, ceiling=AsyncMock(return_value=False))
    unpriced_charge = accumulate.await_args.args[1]

    for name, pricing in _COST_PER_1K.items():
        known = (1000 / 1000 * pricing["input"]) + (500 / 1000 * pricing["output"])
        assert unpriced_charge >= known, f"fallback is cheaper than {name} — not conservative"


# ── AC-3: it is loud ─────────────────────────────────────────────────────────


async def test_unpriced_model_logs_at_error_not_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sentry's default LoggingIntegration has event_level=ERROR, so WARNING was
    invisible in production. An unpriced model is an operational defect."""
    with caplog.at_level(logging.DEBUG):
        await _run(
            UNPRICED_MODEL,
            accumulate=AsyncMock(return_value=0.5),
            ceiling=AsyncMock(return_value=False),
        )

    records = [r for r in caplog.records if UNPRICED_MODEL in r.getMessage()]
    assert records, "the unpriced model must be named in the logs"
    assert any(r.levelno >= logging.ERROR for r in records), (
        "must log at ERROR so Sentry raises it — WARNING was why this went unnoticed"
    )


# ── AC-4: the lesson still completes ─────────────────────────────────────────


async def test_unpriced_model_does_not_abort_the_lesson() -> None:
    """PRD §14 is 'downshift ... complete lesson, flag in admin' — never abort.
    Hard-failing would also make the model-evaluation workflow CLAUDE.md
    mandates impossible."""
    result = await _run(
        UNPRICED_MODEL,
        accumulate=AsyncMock(return_value=0.5),
        ceiling=AsyncMock(return_value=False),
    )
    assert result == "hello"


# ── AC-5: the ceiling actually fires ─────────────────────────────────────────


async def test_ceiling_fires_on_an_unpriced_model() -> None:
    """The end-to-end property, and the one AC-1 alone would NOT have caught:
    charging is only useful if it can still trip the ceiling."""
    from app.core.cost_tracker import CostCeilingError

    accumulate = AsyncMock(return_value=3.01)
    ceiling = AsyncMock(return_value=True)  # already over budget

    with pytest.raises(CostCeilingError):
        await _run(UNPRICED_MODEL, accumulate=accumulate, ceiling=ceiling)

    accumulate.assert_awaited_once()


async def test_no_lesson_id_still_skips_cost_entirely() -> None:
    """The one legitimate early return: a provider built outside a pipeline run
    has no lesson to bill. This must survive the fix."""
    from app.providers.llm.openai import OpenAILLMProvider

    accumulate = AsyncMock(return_value=0.0)
    p = _provider_patches(accumulate=accumulate, ceiling=AsyncMock(return_value=False))
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
        provider = OpenAILLMProvider(lesson_id=None)
        await provider.complete([{"role": "user", "content": "hi"}], UNPRICED_MODEL)

    accumulate.assert_not_awaited()


# ── AC-6: standing guard ─────────────────────────────────────────────────────


async def test_no_early_return_before_accumulate_except_the_lesson_id_guard() -> None:
    """Structural guard (DEV1-FIX-PLAN item 10 — "add standing guard tests").

    The original defect was a `return` reached before `accumulate_cost`. A
    behavioural test only catches the cases it thinks to enumerate; this catches
    ANY newly-introduced early exit. Exactly one bare `return` is permitted —
    the `self._lesson_id is None` guard.
    """
    import ast
    import inspect
    import textwrap

    from app.providers.llm.openai import OpenAILLMProvider

    src = textwrap.dedent(inspect.getsource(OpenAILLMProvider._maybe_accumulate_cost))
    tree = ast.parse(src)

    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert len(returns) == 1, (
        f"expected exactly one early return (the lesson_id guard), found {len(returns)} — "
        "a new early exit before accumulate_cost re-opens the cost-ceiling fail-open"
    )

    # ...and it must be the lesson_id guard, not something new wearing its place.
    guard = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.If) and any(isinstance(c, ast.Return) for c in ast.walk(n))
    )
    assert "_lesson_id" in ast.dump(guard.test), (
        "the sole early return must be the `self._lesson_id is None` guard"
    )

    assert any(isinstance(n, ast.Name) and n.id == "accumulate_cost" for n in ast.walk(tree)), (
        "accumulate_cost must still be called"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Review round 2 (2026-07-29) — D16 and D17
# ═══════════════════════════════════════════════════════════════════════════
#
# D16: `test_ceiling_fires_on_an_unpriced_model` above stubs
# `check_ceiling -> True` UNCONDITIONALLY. It therefore asserts "when
# check_ceiling returns True, CostCeilingError is raised" — i.e. it tests the
# `if` statement, not the ceiling. It cannot distinguish a charge that trips
# the ceiling from one that doesn't, which is the property AC-5 claims to prove.
# The test below runs the REAL accumulate_cost/check_ceiling arithmetic against
# fakeredis so the charge itself has to do the work.


@pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis[aioredis] not installed")
async def test_unpriced_charge_really_trips_the_ceiling_via_real_arithmetic() -> None:
    """AC-5, with nothing stubbed between the charge and the verdict.

    Seed the lesson just under the $3.00 ceiling, then make one unpriced-model
    call. Nothing tells `check_ceiling` what to return — the fallback rate has
    to actually push the running total over on its own.
    """
    from app.core.cost_tracker import CostCeilingError

    redis = _fake_redis()
    seeded = 2.999

    with patch("app.core.cost_tracker.get_redis", return_value=redis):
        await _seed_cost(redis, FAKE_LESSON_ID, seeded)
        with pytest.raises(CostCeilingError):
            await _run_with_real_cost_tracking(UNPRICED_MODEL)

        total = await _read_cost(redis, FAKE_LESSON_ID)

    assert total > seeded, "the unpriced call must have added a real charge"
    assert total >= 3.00, f"charge did not carry the total over the ceiling: ${total}"


@pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis[aioredis] not installed")
async def test_a_charge_below_the_ceiling_does_not_trip_it() -> None:
    """The other half, and the reason the stubbed version proved nothing: with
    `check_ceiling` hardcoded to True, this scenario is indistinguishable from
    the one above. Here the same code path must NOT raise.
    """
    redis = _fake_redis()

    with patch("app.core.cost_tracker.get_redis", return_value=redis):
        await _run_with_real_cost_tracking(UNPRICED_MODEL)  # must not raise
        total = await _read_cost(redis, FAKE_LESSON_ID)

    assert 0 < total < 3.00, f"expected a small real charge well under the ceiling, got ${total}"


# ── D17: missing or nonsensical token counts must not kill the node ──────────
#
# `usage.prompt_tokens` is typed `int` by the OpenAI SDK, but this codebase is
# explicitly built to swap models by env var (CLAUDE.md), and OpenAI-compatible
# endpoints do return `null` usage fields. Before this round that raised
# `TypeError: unsupported operand type(s) for /: 'NoneType' and 'int'` — an
# unknown exception, so `with_retry` would not retry it and the node died.
#
# Verified reachable: calling `_maybe_accumulate_cost(model, None, 500)` raised.


@pytest.mark.parametrize(
    ("prompt", "completion"),
    [(None, 500), (1000, None), (None, None)],
)
async def test_missing_token_counts_do_not_crash_the_node(
    prompt: int | None, completion: int | None
) -> None:
    """A billing-metadata gap must never destroy an already-paid-for completion.

    The provider call succeeded and the money is spent; throwing here would make
    ARQ re-run and re-pay for the node. Treat the missing half as zero, charge
    what we can, and keep going.
    """
    accumulate = AsyncMock(return_value=0.5)
    response = _chat_response(prompt=prompt, completion=completion)

    result = await _run(
        UNPRICED_MODEL,
        accumulate=accumulate,
        ceiling=AsyncMock(return_value=False),
        response=response,
    )

    assert result == "hello", "the completion must still be returned"
    accumulate.assert_awaited_once()
    charged = accumulate.await_args.args[1]
    assert charged >= 0, f"charge must never be negative, got {charged}"


async def test_negative_token_counts_are_clamped_not_propagated() -> None:
    """`accumulate_cost` raises ValueError on a negative cost — an unknown
    exception that `with_retry` will not retry, so it kills the node. A
    nonsensical count from a provider must be clamped here, at the source,
    rather than becoming a fatal error two layers down.
    """
    accumulate = AsyncMock(return_value=0.5)

    await _run(
        UNPRICED_MODEL,
        accumulate=accumulate,
        ceiling=AsyncMock(return_value=False),
        response=_chat_response(prompt=-1000, completion=-500),
    )

    accumulate.assert_awaited_once()
    charged = accumulate.await_args.args[1]
    assert charged >= 0, f"negative token counts must not produce a negative charge: {charged}"
