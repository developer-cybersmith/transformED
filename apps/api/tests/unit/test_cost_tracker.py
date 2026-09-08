"""
Unit tests for app.core.cost_tracker — narrow, isolated coverage of the
Redis-null-key contract that Story 2-1's AC-7 wiring (graph.py's
_fan_out_phase1_economy_nodes) depends on transitively via check_ceiling().

Review finding (2026-07-14, test-coverage): test_phase1_economy_nodes.py's
autouse fixture pins redis.get() to return None for every test in that file
so check_ceiling() doesn't crash on an unconfigured mock, but nothing pinned
get_cost(unknown)==0.0 as its own direct assertion — a regression in this
contract would fail every test in that file simultaneously with no test
isolating the actual root cause. This file closes that gap.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

FAKE_LESSON_ID = "20202020-2020-2020-2020-202020202020"

try:  # fakeredis[aioredis] is a dev dependency; skip rather than fail without it.
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis

    _HAS_FAKEREDIS = True
except ImportError:  # pragma: no cover - depends on environment
    _HAS_FAKEREDIS = False


def _fake_redis() -> Any:  # noqa: ANN401
    return FakeRedis(server=FakeServer(), decode_responses=True)


@pytest.mark.asyncio
async def test_get_cost_returns_zero_for_unknown_lesson() -> None:
    from app.core.cost_tracker import get_cost

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    # cost_tracker.py does `from app.core.redis import get_redis` at module
    # level, binding the name into app.core.cost_tracker's own namespace —
    # patching app.core.redis.get_redis would leave that already-bound
    # reference untouched, so the patch target must be the consuming module.
    with patch("app.core.cost_tracker.get_redis", return_value=mock_redis):
        cost = await get_cost(FAKE_LESSON_ID)

    assert cost == 0.0


@pytest.mark.asyncio
async def test_get_cost_parses_stored_float_string() -> None:
    from app.core.cost_tracker import get_cost

    mock_redis = AsyncMock()
    mock_redis.get.return_value = "1.2345"

    with patch("app.core.cost_tracker.get_redis", return_value=mock_redis):
        cost = await get_cost(FAKE_LESSON_ID)

    assert cost == 1.2345


@pytest.mark.asyncio
async def test_check_ceiling_false_when_cost_key_missing() -> None:
    """The specific transitive contract test_phase1_economy_nodes.py's
    autouse fixture relies on: an unknown lesson's cost reads as 0.0, so
    check_ceiling() returns False rather than raising."""
    from app.core.cost_tracker import check_ceiling

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("app.core.cost_tracker.get_redis", return_value=mock_redis):
        over = await check_ceiling(FAKE_LESSON_ID)

    assert over is False


# ── Story 5-2 AC-3: real concurrency, not a mocked single-call assertion ────
#
# accumulate_cost's docstring/comment claims INCRBYFLOAT is "atomic increment,
# safe under concurrent workers" -- a true claim about Redis's own command,
# but never itself exercised by a real concurrent-access test anywhere in
# this codebase before now. These two tests run the REAL function against
# real (fake) Redis arithmetic, many calls truly concurrent via
# asyncio.gather, not sequential -- exactly what a mocked `AsyncMock` cannot
# prove, since a mock has no shared state to corrupt in the first place.


@pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis[aioredis] not installed")
async def test_accumulate_cost_never_loses_an_update_under_real_concurrency() -> None:
    """Story 5-2 AC-3: N truly-concurrent accumulate_cost() calls for the
    SAME lesson_id must sum to exactly their total -- a read-modify-write
    implementation (GET, add in Python, SET) would lose updates under real
    concurrency; INCRBYFLOAT must not."""
    from app.core.cost_tracker import accumulate_cost, get_cost

    redis = _fake_redis()
    amounts = [0.01] * 50  # 50 concurrent slide-image-sized charges

    with patch("app.core.cost_tracker.get_redis", return_value=redis):
        await asyncio.gather(*(accumulate_cost(FAKE_LESSON_ID, amt) for amt in amounts))
        total = await get_cost(FAKE_LESSON_ID)

    assert total == pytest.approx(sum(amounts), abs=1e-9)


@pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis[aioredis] not installed")
async def test_concurrent_lessons_cost_accumulation_does_not_cross_contaminate() -> None:
    """Story 5-2 AC-3: two DIFFERENT lessons accumulating cost at the same
    time, against the SAME Redis instance (the real single-Redis-many-
    lessons deployment shape), must stay fully isolated -- lesson A's
    charges must never land on lesson B's running total, in either
    direction."""
    from app.core.cost_tracker import accumulate_cost, get_cost

    lesson_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    lesson_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    redis = _fake_redis()

    with patch("app.core.cost_tracker.get_redis", return_value=redis):
        await asyncio.gather(
            *(accumulate_cost(lesson_a, 0.02) for _ in range(20)),
            *(accumulate_cost(lesson_b, 0.05) for _ in range(20)),
        )
        cost_a = await get_cost(lesson_a)
        cost_b = await get_cost(lesson_b)

    assert cost_a == pytest.approx(0.02 * 20, abs=1e-9)
    assert cost_b == pytest.approx(0.05 * 20, abs=1e-9)
