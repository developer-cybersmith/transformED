"""RED tests for S3-39 (D14): compute_ces and history writes gated on TEACHING state.

Written RED-first — they fail until process_attention_signal reads state_raw
BEFORE compute_ces and guards CES computation inside 'if state_raw == "TEACHING"'.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_redis(state: str = "TEACHING") -> AsyncMock:
    """Async Redis mock with controllable tutor_state."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda key, *a, **kw: state if "tutor_state" in key else None)
    redis.set = AsyncMock(return_value=True)
    redis.lpush = AsyncMock(return_value=1)
    redis.ltrim = AsyncMock(return_value=True)
    redis.lrange = AsyncMock(return_value=[])
    redis.expire = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=0)
    return redis


def _signal(session_id: str = "ses-39") -> dict:
    return {
        "session_id": session_id,
        "quiz_accuracy": 0.8,
        "teachback_score": None,
        "behavioral_score": None,
        "head_pose_score": None,
        "blink_rate": None,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_not_written_in_quizzing_state():
    """AC2: lpush to ces_history must NOT be called when state == QUIZZING."""
    from app.modules.tutor.service import process_attention_signal  # noqa: PLC0415

    redis = _make_redis(state="QUIZZING")
    settings = MagicMock()
    settings.ces_cadence_seconds = 5

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch("app.config.get_settings", return_value=settings),
        patch("app.modules.tutor.service._quiz_deadline_expired", return_value=False),
    ):
        result = await process_attention_signal("ses-39", _signal())

    lpush_called_for_history = any(
        "ces_history" in str(call) for call in redis.lpush.call_args_list
    )
    assert not lpush_called_for_history, (
        "lpush(ces_history) must NOT be called when state is QUIZZING"
    )
    assert result.intervention_dispatched is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_written_in_teaching_state():
    """AC2: lpush to ces_history IS called when state == TEACHING."""
    from app.modules.tutor.service import process_attention_signal  # noqa: PLC0415

    redis = _make_redis(state="TEACHING")
    settings = MagicMock()
    settings.ces_weight_quiz = 0.35
    settings.ces_weight_teachback = 0.25
    settings.ces_weight_behavioral = 0.20
    settings.ces_weight_head_pose = 0.12
    settings.ces_weight_blink = 0.08
    settings.ces_cadence_seconds = 5
    settings.ces_threshold = 50.0

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch("app.config.get_settings", return_value=settings),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "TEACHING"},
        ),
    ):
        await process_attention_signal("ses-39t", _signal("ses-39t"))

    lpush_called_for_history = any(
        "ces_history" in str(call) for call in redis.lpush.call_args_list
    )
    assert lpush_called_for_history, "lpush(ces_history) MUST be called when state is TEACHING"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_history_not_written_in_intervening_state():
    """AC2: lpush to ces_history must NOT be called when state == INTERVENING."""
    from app.modules.tutor.service import process_attention_signal  # noqa: PLC0415

    redis = _make_redis(state="INTERVENING")
    settings = MagicMock()
    settings.ces_cadence_seconds = 5

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch("app.config.get_settings", return_value=settings),
        patch("app.modules.tutor.service._quiz_deadline_expired", return_value=False),
    ):
        await process_attention_signal("ses-39i", _signal("ses-39i"))

    lpush_called_for_history = any(
        "ces_history" in str(call) for call in redis.lpush.call_args_list
    )
    assert not lpush_called_for_history, (
        "lpush(ces_history) must NOT be called when state is INTERVENING"
    )
