"""RED tests for S3-52: CES production hardening — 3 gaps identified by BMAD audit.

Gap A (AC 1-3): _can_intervene_fatigue must check the cooldown key before
  dispatching fatigue, so a learner cannot receive a fatigue intervention
  within 2 minutes of a distraction intervention (PRD §10 violation).

Gap B (AC 4): D4 timestamp gap-check non-dispatch path — stale entries with
  abs(t0-t1) > 2×cadence must suppress the distraction trigger.

Gap C (AC 5-6): Non-TEACHING state guard tests — dispatch_event and lpush
  must never be called when state is QUIZZING or INTERVENING.
"""
from __future__ import annotations

import inspect
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Shared settings helper (mirrors test_s3_45_fatigue_trigger.py) ─────────────

def _mock_settings(**overrides: Any) -> MagicMock:
    s = MagicMock()
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    s.ces_threshold = 50.0
    s.ces_cadence_seconds = 5
    s.ces_fatigue_blink_threshold = 0.3
    s.ces_fatigue_head_pose_threshold = 0.3
    s.ces_fatigue_min_session_seconds = 900
    s.intervention_cooldown_seconds = 120
    s.max_distraction_per_session = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


_NORMAL_SIGNAL = {
    "session_id": "ses-52",       # _parse_signal reads session_id from the dict
    "quiz_accuracy": 0.5,
    "behavioral_score": 0.7,
    "head_pose_score": 0.8,
    "blink_rate": 0.6,
    "teachback_score": None,
}


# ──────────────────────────────────────────────────────────────────────────────
# Gap A — AC 1: _can_intervene_fatigue source checks the cooldown key
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_can_intervene_fatigue_source_checks_cooldown_key():
    """AC 1: _can_intervene_fatigue must reference the cooldown key before
    setting the fatigue flag, so the 2-minute inter-intervention cooldown
    applies to fatigue (not just distraction).
    """
    from app.modules.tutor.state_machine.graph import _can_intervene_fatigue  # noqa: PLC2701

    src = inspect.getsource(_can_intervene_fatigue)
    assert "tutor_cooldown" in src, (
        "_can_intervene_fatigue must check the cooldown key (PRD §10: 2-min gap after any intervention)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gap A — AC 1 (signature): function accepts optional redis kwarg for testability
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_can_intervene_fatigue_signature_accepts_redis_kwarg():
    """_can_intervene_fatigue must accept an optional redis keyword argument
    so callers can inject a mock; existing call sites that omit it use get_redis().
    """
    from app.modules.tutor.state_machine.graph import _can_intervene_fatigue  # noqa: PLC2701

    sig = inspect.signature(_can_intervene_fatigue)
    assert "redis" in sig.parameters, (
        "_can_intervene_fatigue must accept a redis kwarg for testability"
    )
    param = sig.parameters["redis"]
    assert param.default is not inspect.Parameter.empty, (
        "redis parameter must be optional (default=None)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gap A — AC 2: fatigue blocked when cooldown is active
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_can_intervene_fatigue_blocked_by_active_cooldown():
    """AC 2: fatigue returns False when the cooldown key exists (distraction
    just fired). The learner must not receive two interventions within 120 s.
    """
    from app.modules.tutor.state_machine.graph import _can_intervene_fatigue  # noqa: PLC2701

    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=1)   # cooldown key present
    redis.set = AsyncMock(return_value="OK")   # should NOT be reached

    result = await _can_intervene_fatigue("ses-52-cooldown", redis=redis)

    assert result is False, (
        "_can_intervene_fatigue must return False when cooldown key exists"
    )
    redis.set.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# Gap A — AC 3a: fatigue allowed when cooldown cleared and flag not yet set
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_can_intervene_fatigue_allowed_after_cooldown_expires():
    """AC 3: fatigue returns True when cooldown key absent and flag not yet set."""
    from app.modules.tutor.state_machine.graph import _can_intervene_fatigue  # noqa: PLC2701

    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)    # cooldown clear
    redis.set = AsyncMock(return_value="OK")    # SET NX succeeds (key was absent)

    result = await _can_intervene_fatigue("ses-52-ok", redis=redis)

    assert result is True, (
        "_can_intervene_fatigue must return True when cooldown clear and flag not set"
    )
    redis.set.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# Gap A — AC 3b: fatigue blocked when once-per-session flag already set
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_can_intervene_fatigue_blocked_when_flag_already_set():
    """AC 3 (flag path): returns False when flag already set, even if cooldown clear."""
    from app.modules.tutor.state_machine.graph import _can_intervene_fatigue  # noqa: PLC2701

    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)   # cooldown clear
    redis.set = AsyncMock(return_value=None)    # SET NX fails — key pre-existed

    result = await _can_intervene_fatigue("ses-52-flag-set", redis=redis)

    assert result is False, (
        "_can_intervene_fatigue must return False when SET-NX fails (once-per-session already fired)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gap B — AC 4: D4 timestamp gap-check suppresses stale-entry dispatch
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_distraction_not_dispatched_when_timestamps_are_stale():
    """AC 4: Two CES entries both below 50 but timestamps > 10 s apart
    (> 2 × ces_cadence_seconds=5) must NOT trigger a distraction dispatch.

    Prior tests all use t=0 for both entries — abs(0-0)=0 ≤ 10 always passes.
    This test explicitly exercises the rejection path.
    """
    from app.modules.tutor.service import process_attention_signal

    now = int(time.time())
    entry_recent = json.dumps({"v": 30.0, "t": now})
    entry_stale = json.dumps({"v": 25.0, "t": now - 60})  # 60 s > 2×5 s cadence

    mock_redis = AsyncMock()

    async def fake_get(key: str):
        if "tutor_state" in key:
            return "TEACHING"
        if "session_start_ts" in key:
            return None   # skip fatigue path for this test
        return None

    async def fake_lrange(key: str, start: int, end: int):
        if "ces_history" in key:
            return [entry_recent, entry_stale]
        return []

    mock_redis.get = AsyncMock(side_effect=fake_get)
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.lrange = AsyncMock(side_effect=fake_lrange)
    mock_redis.set = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()

    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch("app.modules.tutor.service._segment_intervention_messages", AsyncMock(return_value={})),
    ):
        result = await process_attention_signal(
            session_id="ses-52-gap",
            signal=_NORMAL_SIGNAL,
        )

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False, (
        "intervention_dispatched must be False when timestamp gap > 2×cadence"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Gap C — AC 5: dispatch_event NOT called in QUIZZING state with low CES
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_event_not_called_in_quizzing_state_with_low_ces():
    """AC 5 (QUIZZING): dispatch_event must never be called when state=QUIZZING,
    even when two CES history entries are both below the 50-threshold.
    """
    from app.modules.tutor.service import process_attention_signal

    now = int(time.time())
    entry_a = json.dumps({"v": 20.0, "t": now})
    entry_b = json.dumps({"v": 22.0, "t": now - 5})

    mock_redis = AsyncMock()

    async def fake_get(key: str):
        if "tutor_state" in key:
            return "QUIZZING"
        return None

    async def fake_lrange(key: str, start: int, end: int):
        if "ces_history" in key:
            return [entry_a, entry_b]
        return []

    mock_redis.get = AsyncMock(side_effect=fake_get)
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.lrange = AsyncMock(side_effect=fake_lrange)
    mock_redis.set = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()

    mock_dispatch = AsyncMock(return_value={"current_state": "QUIZZING"})

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch("app.modules.tutor.service._segment_intervention_messages", AsyncMock(return_value={})),
    ):
        result = await process_attention_signal(
            session_id="ses-52-quiz",
            signal=_NORMAL_SIGNAL,
        )

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_event_not_called_in_intervening_state_with_low_ces():
    """AC 5 (INTERVENING): dispatch_event must never be called when state=INTERVENING,
    even when two CES history entries are both below the threshold.
    """
    from app.modules.tutor.service import process_attention_signal

    now = int(time.time())
    entry_a = json.dumps({"v": 15.0, "t": now})
    entry_b = json.dumps({"v": 18.0, "t": now - 5})

    mock_redis = AsyncMock()

    async def fake_get(key: str):
        if "tutor_state" in key:
            return "INTERVENING"
        return None

    async def fake_lrange(key: str, start: int, end: int):
        if "ces_history" in key:
            return [entry_a, entry_b]
        return []

    mock_redis.get = AsyncMock(side_effect=fake_get)
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.lrange = AsyncMock(side_effect=fake_lrange)
    mock_redis.set = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()

    mock_dispatch = AsyncMock(return_value={"current_state": "INTERVENING"})

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch("app.modules.tutor.service._segment_intervention_messages", AsyncMock(return_value={})),
    ):
        result = await process_attention_signal(
            session_id="ses-52-intervene",
            signal=_NORMAL_SIGNAL,
        )

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


# ──────────────────────────────────────────────────────────────────────────────
# Gap C — AC 6: per-signal lpush NOT called when state is non-TEACHING
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_signal_lpush_not_called_when_state_is_quizzing():
    """AC 6: behavioral_history, head_pose_history, blink_history must NOT be
    written via lpush when the session state is QUIZZING.
    """
    from app.modules.tutor.service import process_attention_signal

    mock_redis = AsyncMock()

    async def fake_get(key: str):
        if "tutor_state" in key:
            return "QUIZZING"
        return None

    mock_redis.get = AsyncMock(side_effect=fake_get)
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.lrange = AsyncMock(return_value=[])
    mock_redis.set = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", AsyncMock(return_value={})),
        patch("app.modules.tutor.service._segment_intervention_messages", AsyncMock(return_value={})),
    ):
        await process_attention_signal(
            session_id="ses-52-lpush",
            signal=_NORMAL_SIGNAL,
        )

    called_keys = [str(c) for c in mock_redis.lpush.call_args_list]
    assert not any("behavioral_history" in k for k in called_keys), (
        "behavioral_history must not be written when state=QUIZZING"
    )
    assert not any("head_pose_history" in k for k in called_keys), (
        "head_pose_history must not be written when state=QUIZZING"
    )
    assert not any("blink_history" in k for k in called_keys), (
        "blink_history must not be written when state=QUIZZING"
    )
