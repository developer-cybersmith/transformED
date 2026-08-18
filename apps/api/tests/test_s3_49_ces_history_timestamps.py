"""S3-49: JSON timestamps in ces_history {v:float, t:int} and gap-check on trigger (D4).

All tests are @pytest.mark.unit — no real Redis, DB, or network.
"""

from __future__ import annotations

import inspect
import json
import statistics
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────


_VALID_PAYLOAD: dict[str, Any] = {
    "session_id": "sess-001",
    "behavioral_score": 0.8,
    "head_pose_score": 0.7,
    "blink_rate": 0.6,
}


def _mock_settings(
    *,
    threshold: float = 50.0,
    cadence: int = 5,
) -> MagicMock:
    s = MagicMock()
    s.ces_threshold = threshold
    s.ces_cadence_seconds = cadence
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    s.max_distraction_per_session = 3
    s.intervention_cooldown_seconds = 120
    return s


def _mock_redis(
    *,
    lrange_vals: list[str] | None = None,
    state: str = "TEACHING",
) -> AsyncMock:
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.lpush = AsyncMock(return_value=1)
    r.ltrim = AsyncMock(return_value=True)
    r.expire = AsyncMock(return_value=True)

    if lrange_vals is not None:
        r.lrange = AsyncMock(return_value=lrange_vals)
    else:
        r.lrange = AsyncMock(return_value=[])

    async def _get(key: str) -> str | None:
        if "tutor_state:" in key:
            return state
        if "quiz_deadline_at" in key:
            return None
        return None

    r.get = AsyncMock(side_effect=_get)
    r.delete = AsyncMock(return_value=0)
    return r


def _setup_trigger(
    mocker,
    *,
    lrange_vals: list[str],
    state: str = "TEACHING",
    can_dispatch: bool = True,
    threshold: float = 50.0,
    cadence: int = 5,
):
    """Wire up all mocks needed to test the distraction trigger path."""
    settings = _mock_settings(threshold=threshold, cadence=cadence)
    redis = _mock_redis(lrange_vals=lrange_vals, state=state)

    mocker.patch("app.config.get_settings", return_value=settings)
    mocker.patch("app.core.redis.get_redis", return_value=redis)
    mocker.patch("app.modules.tutor.state_machine.graph._trace_dispatch", return_value=None)

    mock_guard = mocker.patch(
        "app.modules.tutor.state_machine.graph._can_intervene_distraction",
        new_callable=AsyncMock,
    )
    mock_guard.return_value = can_dispatch

    mock_dispatch = mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        new_callable=AsyncMock,
    )
    mock_dispatch.return_value = {"current_state": "INTERVENING", "intervention_message": None}

    return redis, mock_dispatch, mock_guard


# ── AC 1: JSON write ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ces_history_write_is_json_not_bare_float() -> None:
    """AC 1 source guard: json.dumps present; bare lpush(history_key, ces) absent."""
    from app.modules.tutor.service import process_attention_signal

    src = inspect.getsource(process_attention_signal)
    assert "json.dumps" in src, "process_attention_signal must use json.dumps for ces_history"
    assert "lpush(history_key, ces)" not in src, (
        "bare lpush(history_key, ces) must not appear — use json.dumps({'v': ces, 't': ...})"
    )


@pytest.mark.unit
async def test_ces_history_lpush_value_is_valid_json(mocker) -> None:
    """AC 1 runtime: value pushed to ces_history is parseable by json.loads."""
    redis, _, _ = _setup_trigger(mocker, lrange_vals=[])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-001", _VALID_PAYLOAD)

    # Find the lpush call for the ces_history key
    history_key = "session:sess-001:ces_history"
    history_calls = [c for c in redis.lpush.call_args_list if c.args[0] == history_key]
    assert history_calls, "lpush must be called with the ces_history key"
    pushed_val = history_calls[0].args[1]
    parsed = json.loads(pushed_val)
    assert "v" in parsed
    assert "t" in parsed


@pytest.mark.unit
async def test_ces_history_json_has_v_float_and_t_int(mocker) -> None:
    """AC 1 type assertions: parsed entry has isinstance(v, float) and isinstance(t, int)."""
    redis, _, _ = _setup_trigger(mocker, lrange_vals=[])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-001", _VALID_PAYLOAD)

    history_key = "session:sess-001:ces_history"
    history_calls = [c for c in redis.lpush.call_args_list if c.args[0] == history_key]
    pushed_val = history_calls[0].args[1]
    parsed = json.loads(pushed_val)

    assert isinstance(parsed["v"], float), f"v must be float, got {type(parsed['v'])}"
    assert isinstance(parsed["t"], int), f"t must be int, got {type(parsed['t'])}"
    assert abs(parsed["t"] - int(time.time())) <= 2, "timestamp must be within 2 s of now"
    assert 0.0 <= parsed["v"] <= 100.0, f"CES must be in [0, 100], got {parsed['v']}"


# ── AC 2: ces_cadence_seconds env var ─────────────────────────────────────────


@pytest.mark.unit
def test_ces_cadence_seconds_in_settings() -> None:
    """AC 2 source: ces_cadence_seconds declared in Settings."""
    from app.config import Settings

    src = inspect.getsource(Settings)
    assert "ces_cadence_seconds" in src, "Settings must declare ces_cadence_seconds"


@pytest.mark.unit
def test_ces_cadence_seconds_default_is_5(monkeypatch) -> None:
    """AC 2 value: default is 5 when CES_CADENCE_SECONDS env var not set."""
    monkeypatch.delenv("CES_CADENCE_SECONDS", raising=False)
    from app.config import Settings

    s = Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
    )
    assert s.ces_cadence_seconds == 5


# ── AC 3: gap check blocks / allows ───────────────────────────────────────────


@pytest.mark.unit
async def test_gap_check_blocks_intervention_when_timestamps_too_far_apart(mocker) -> None:
    """AC 3 fail case: gap=15s > 10s (2*cadence=5); both v below threshold; NOT dispatched."""
    history = [
        '{"v": 40.0, "t": 1720000015}',
        '{"v": 42.0, "t": 1720000000}',
    ]
    _, mock_dispatch, _ = _setup_trigger(mocker, lrange_vals=history, cadence=5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-gap-fail", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_gap_check_allows_intervention_when_timestamps_within_tolerance(mocker) -> None:
    """AC 3 pass case: gap=8s <= 10s (2*cadence=5); both v below threshold; dispatched."""
    history = [
        '{"v": 40.0, "t": 1720000008}',
        '{"v": 42.0, "t": 1720000000}',
    ]
    _, mock_dispatch, mock_guard = _setup_trigger(mocker, lrange_vals=history, cadence=5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-gap-pass", _VALID_PAYLOAD)

    mock_guard.assert_called_once()
    mock_dispatch.assert_called_once()
    assert result.intervention_dispatched is True


# ── AC 4: legacy bare-float backward compat ───────────────────────────────────


@pytest.mark.unit
async def test_legacy_bare_float_entry_does_not_trigger_intervention(mocker) -> None:
    """AC 4: legacy 'bare float' entry → t=0 → gap check fails → no intervention."""
    history = [
        '{"v": 40.0, "t": 1720000000}',
        "42.0",  # legacy bare float: t=0 → gap = current_time >> 10s
    ]
    _, mock_dispatch, _ = _setup_trigger(mocker, lrange_vals=history, cadence=5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-legacy", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_legacy_entry_does_not_raise_exception(mocker) -> None:
    """AC 4: mixed JSON + legacy entries do not raise; returns CesResult."""
    history = [
        '{"v": 40.0, "t": 1720000000}',
        "42.0",
    ]
    _setup_trigger(mocker, lrange_vals=history, cadence=5)

    from app.modules.tutor.service import CesResult, process_attention_signal

    result = await process_attention_signal("sess-legacy-noexc", _VALID_PAYLOAD)
    assert isinstance(result, CesResult)


# ── AC 5: compute_ces_from_session_aggregates JSON parsing ────────────────────


@pytest.mark.unit
async def test_compute_ces_aggregates_parses_json_entries() -> None:
    """AC 5: 5 valid JSON entries — returns round(mean(v_values), 2)."""
    raw = [
        '{"v": 50.0, "t": 1720000000}',
        '{"v": 60.0, "t": 1719999995}',
        '{"v": 70.0, "t": 1719999990}',
        '{"v": 80.0, "t": 1719999985}',
        '{"v": 45.0, "t": 1719999980}',
    ]
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=raw)

    settings = _mock_settings()

    from app.modules.assessment.service import compute_ces_from_session_aggregates

    result = await compute_ces_from_session_aggregates("sess-001", redis, settings)

    expected = round(statistics.mean([50.0, 60.0, 70.0, 80.0, 45.0]), 2)
    assert result == expected  # == 61.0


@pytest.mark.unit
async def test_compute_ces_aggregates_skips_non_json_and_non_float_entries() -> None:
    """AC 5: 'not_a_number' skipped; 5 valid JSON entries remain → correct mean."""
    raw = [
        '{"v": 50.0, "t": 1720000000}',
        '{"v": 60.0, "t": 1719999995}',
        "not_a_number",
        '{"v": 70.0, "t": 1719999990}',
        '{"v": 80.0, "t": 1719999985}',
        '{"v": 45.0, "t": 1719999980}',
    ]
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=raw)

    settings = _mock_settings()

    from app.modules.assessment.service import compute_ces_from_session_aggregates

    result = await compute_ces_from_session_aggregates("sess-001", redis, settings)

    expected = round(statistics.mean([50.0, 60.0, 70.0, 80.0, 45.0]), 2)
    assert result == expected  # 5 valid entries, corrupt one skipped


@pytest.mark.unit
async def test_compute_ces_aggregates_backward_compat_bare_float() -> None:
    """AC 5 backward compat: mix of JSON + legacy bare-float entries both parsed correctly."""
    raw = [
        '{"v": 50.0, "t": 1720000000}',
        "60.0",  # legacy bare float
        '{"v": 70.0, "t": 1719999990}',
        "80.0",  # legacy bare float
        '{"v": 45.0, "t": 1719999980}',
    ]
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=raw)

    settings = _mock_settings()

    from app.modules.assessment.service import compute_ces_from_session_aggregates

    result = await compute_ces_from_session_aggregates("sess-001", redis, settings)

    expected = round(statistics.mean([50.0, 60.0, 70.0, 80.0, 45.0]), 2)
    assert result == expected


# ── AC 6: CI source guard ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_legacy_float_pattern_not_in_process_attention_signal_source() -> None:
    """AC 6: pre-D4 bare-float parse pattern must not appear in trigger source."""
    from app.modules.tutor.service import process_attention_signal

    src = inspect.getsource(process_attention_signal)
    assert "float(v) for v in history_raw[:2]" not in src, (
        "Legacy bare-float trigger pattern found — D4 gap-check must replace it"
    )
