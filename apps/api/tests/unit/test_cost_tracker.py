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

from unittest.mock import AsyncMock, patch

import pytest

FAKE_LESSON_ID = "20202020-2020-2020-2020-202020202020"


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
