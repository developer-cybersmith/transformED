"""Tests for S3-45 — Behavioral Fatigue Trigger (D7).

AC coverage:
  AC1  three config settings with correct defaults and validation
  AC2  session_start_ts written by _init_session_state, not overwritten on reconnect
  AC3  primary trigger dispatches fatigue_detected after 15-min floor
  AC4  no dispatch before ces_fatigue_min_session_seconds
  AC5  requires both blink AND head_pose below threshold (not just one)
  AC6  requires >= 2 windows of history for each signal
  AC7  once-per-session guard blocks second dispatch
  AC8  no dispatch outside TEACHING state
  AC9  exhaustion fallback dispatches when all MediaPipe None after floor (S3-38 dep)
  AC10 exhaustion fallback blocked before duration floor (S3-38 dep)
  AC11 WS tutor_intervene message delivered on fatigue dispatch
  AC12 lrange uses end index 1 (bounded, not -1) — source check
  AC13 session_start_ts missing -> fail-closed, no dispatch

Note on patch targets: dispatch_event, _can_intervene_fatigue, and get_settings are all
lazy-imported inside process_attention_signal's function body. The correct patch target is
the source module (e.g. app.modules.tutor.state_machine.graph.dispatch_event), NOT
app.modules.tutor.service.dispatch_event (which does not exist at module level there).
"""

from __future__ import annotations

import inspect
import re
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

# ── AC 1: config settings ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_ces_fatigue_blink_threshold_default_is_0_3(monkeypatch):
    import os

    for k, v in [
        ("SUPABASE_URL", "http://x"),
        ("SUPABASE_ANON_KEY", "x"),
        ("SUPABASE_SERVICE_ROLE_KEY", "x"),
        ("SUPABASE_JWT_SECRET", "x"),
        ("OPENAI_API_KEY", "x"),
        ("SARVAM_API_KEY", "x"),
    ]:
        monkeypatch.setenv(k, os.environ.get(k, v))

    from app.config import Settings

    s = Settings()
    assert s.ces_fatigue_blink_threshold == pytest.approx(0.3)


@pytest.mark.unit
def test_ces_fatigue_head_pose_threshold_default_is_0_3(monkeypatch):
    import os

    for k, v in [
        ("SUPABASE_URL", "http://x"),
        ("SUPABASE_ANON_KEY", "x"),
        ("SUPABASE_SERVICE_ROLE_KEY", "x"),
        ("SUPABASE_JWT_SECRET", "x"),
        ("OPENAI_API_KEY", "x"),
        ("SARVAM_API_KEY", "x"),
    ]:
        monkeypatch.setenv(k, os.environ.get(k, v))

    from app.config import Settings

    s = Settings()
    assert s.ces_fatigue_head_pose_threshold == pytest.approx(0.3)


@pytest.mark.unit
def test_ces_fatigue_min_session_seconds_default_is_900(monkeypatch):
    import os

    for k, v in [
        ("SUPABASE_URL", "http://x"),
        ("SUPABASE_ANON_KEY", "x"),
        ("SUPABASE_SERVICE_ROLE_KEY", "x"),
        ("SUPABASE_JWT_SECRET", "x"),
        ("OPENAI_API_KEY", "x"),
        ("SARVAM_API_KEY", "x"),
    ]:
        monkeypatch.setenv(k, os.environ.get(k, v))

    from app.config import Settings

    s = Settings()
    assert s.ces_fatigue_min_session_seconds == 900


@pytest.mark.unit
def test_ces_fatigue_min_session_seconds_below_60_raises_validation_error(monkeypatch):
    import os

    for k, v in [
        ("SUPABASE_URL", "http://x"),
        ("SUPABASE_ANON_KEY", "x"),
        ("SUPABASE_SERVICE_ROLE_KEY", "x"),
        ("SUPABASE_JWT_SECRET", "x"),
        ("OPENAI_API_KEY", "x"),
        ("SARVAM_API_KEY", "x"),
    ]:
        monkeypatch.setenv(k, os.environ.get(k, v))
    monkeypatch.setenv("CES_FATIGUE_MIN_SESSION_SECONDS", "59")

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings()


# ── AC 2: session_start_ts written in _init_session_state ─────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_session_state_writes_session_start_ts_to_redis():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.delete = AsyncMock()

    with (
        patch("app.core.websocket._seed_learner_tier", new_callable=AsyncMock),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        from app.core.websocket import _init_session_state

        await _init_session_state("sess-001")

    ts_calls = [
        c
        for c in mock_redis.set.call_args_list
        if "session:sess-001:session_start_ts" in str(c)
    ]
    assert len(ts_calls) == 1, f"Expected 1 session_start_ts SET, got {len(ts_calls)}"
    args, kwargs = ts_calls[0]
    value = args[1] if len(args) > 1 else kwargs.get("value")
    assert isinstance(value, str), f"session_start_ts must be str, got {type(value)}"
    ts_int = int(value)
    assert abs(ts_int - int(time.time())) <= 5, "session_start_ts must be approximately now"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_session_state_session_start_ts_has_86400_ttl():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.delete = AsyncMock()

    with (
        patch("app.core.websocket._seed_learner_tier", new_callable=AsyncMock),
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        from app.core.websocket import _init_session_state

        await _init_session_state("sess-002")

    ts_calls = [
        c
        for c in mock_redis.set.call_args_list
        if "session:sess-002:session_start_ts" in str(c)
    ]
    assert len(ts_calls) == 1
    args, kwargs = ts_calls[0]
    ttl = kwargs.get("ex")
    assert ttl == 86400, f"session_start_ts must have ex=86400, got {ttl}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_start_ts_not_overwritten_on_reconnect():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"TEACHING")

    with (
        patch("app.core.websocket._seed_learner_tier", new_callable=AsyncMock),
        patch("app.core.websocket._init_session_state", new_callable=AsyncMock) as mock_init,
        patch("app.core.redis.get_redis", return_value=mock_redis),
    ):
        from app.core.websocket import _restore_or_init_session

        state = await _restore_or_init_session("sess-003")

    assert state == "TEACHING"
    mock_init.assert_not_called()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fatigue_redis(
    *,
    state: str = "TEACHING",
    start_ts_offset: int | None = 1000,
    blink_hist: tuple[str, ...] = ("0.2", "0.25"),
    hp_hist: tuple[str, ...] = ("0.15", "0.2"),
    fatigue_fired: int = 0,
    cooldown_exists: int = 0,
    ces_window: str = "70.0",
) -> AsyncMock:
    mock_redis = AsyncMock()
    ts_val = str(int(time.time()) - start_ts_offset) if start_ts_offset is not None else None

    async def fake_get(key: str):
        if "tutor_state" in key:
            return state
        if "session_start_ts" in key:
            return ts_val
        if "ces_window" in key:
            return ces_window
        if "quiz_deadline_at" in key:
            return None
        return None

    async def fake_exists(key: str):
        if "tutor_fatigue_fired" in key:
            return fatigue_fired
        if "tutor_cooldown" in key:
            return cooldown_exists
        return 0

    async def fake_lrange(key: str, start: int, end: int):
        if "blink_history" in key:
            return list(blink_hist[:2]) if end == 1 else list(blink_hist)
        if "head_pose_history" in key:
            return list(hp_hist[:2]) if end == 1 else list(hp_hist)
        if "ces_history" in key:
            return ["75.0", "72.0"]
        if "behavioral_history" in key:
            return ["0.7"]
        return []

    mock_redis.get = AsyncMock(side_effect=fake_get)
    mock_redis.exists = AsyncMock(side_effect=fake_exists)
    mock_redis.lrange = AsyncMock(side_effect=fake_lrange)
    mock_redis.set = AsyncMock()
    mock_redis.lpush = AsyncMock(return_value=1)
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.delete = AsyncMock(return_value=0)
    return mock_redis


def _mock_settings(**overrides: Any) -> MagicMock:
    s = MagicMock()
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    s.ces_threshold = 50.0
    s.ces_fatigue_blink_threshold = 0.3
    s.ces_fatigue_head_pose_threshold = 0.3
    s.ces_fatigue_min_session_seconds = 900
    s.intervention_cooldown_seconds = 120
    s.max_distraction_per_session = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# Signal with blink/head_pose above threshold so it won't trigger fatigue via incoming signal.
# The Redis history (low values) is what triggers the primary_trigger evaluation.
_NORMAL_SIGNAL = {
    "session_id": "sess-001",
    "quiz_accuracy": None,
    "teachback_score": None,
    "behavioral_score": 0.7,
    "head_pose_score": 0.6,
    "blink_rate": 0.5,
}


def _fatigue_patches(
    mock_redis: AsyncMock, mock_dispatch: AsyncMock, *, can_intervene: bool = True
) -> list:
    """Return patch context managers for the fatigue trigger path.

    dispatch_event, _can_intervene_fatigue, and get_settings are lazy-imported inside
    process_attention_signal, so they must be patched at the SOURCE module, not at service.py.
    """
    return [
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch(
            "app.modules.tutor.state_machine.graph._can_intervene_fatigue",
            new_callable=AsyncMock,
            return_value=can_intervene,
        ),
        patch(
            "app.modules.tutor.service._segment_intervention_messages",
            new_callable=AsyncMock,
            return_value={},
        ),
    ]


# ── AC 3: primary trigger dispatches after 15-min floor ──────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_detected_dispatched_after_15_minute_floor_with_low_blink_and_head_pose():
    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=1000)
    mock_dispatch = AsyncMock(
        return_value={
            "current_state": "INTERVENING",
            "intervention_type": "fatigue",
            "intervention_message": None,
        }
    )

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        result = await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) >= 1, "fatigue_detected must be dispatched after 15-min floor"
    assert result.intervention_dispatched is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_before_ces_fatigue_min_session_seconds():
    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=100)  # only 100s
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue_detected must NOT fire before min_session_seconds"


# ── AC 5: requires both blink AND head_pose ───────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_when_only_blink_is_low():
    mock_redis = _make_fatigue_redis(
        state="TEACHING",
        start_ts_offset=1000,
        blink_hist=("0.2", "0.25"),  # both < 0.3 (low)
        hp_hist=("0.5", "0.6"),  # both > 0.3 (normal)
    )
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue must NOT fire when only blink is low"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_when_only_head_pose_is_low():
    mock_redis = _make_fatigue_redis(
        state="TEACHING",
        start_ts_offset=1000,
        blink_hist=("0.6", "0.7"),  # both > 0.3 (normal)
        hp_hist=("0.1", "0.2"),  # both < 0.3 (low)
    )
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue must NOT fire when only head_pose is low"


# ── AC 6: requires >= 2 windows ───────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_with_fewer_than_2_blink_windows():
    mock_redis = _make_fatigue_redis(
        state="TEACHING",
        start_ts_offset=1000,
        blink_hist=("0.2",),  # only 1 entry
        hp_hist=("0.15",),
    )
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue must NOT fire with < 2 blink windows"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_with_fewer_than_2_head_pose_windows():
    mock_redis = _make_fatigue_redis(
        state="TEACHING",
        start_ts_offset=1000,
        blink_hist=("0.2", "0.25"),  # 2 blink (low)
        hp_hist=("0.15",),  # only 1 head_pose
    )
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue must NOT fire with < 2 head_pose windows"


# ── AC 7: once-per-session guard ──────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_twice_in_same_session():
    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=1000)
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=False)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, (
        "fatigue must NOT fire when once-per-session guard returns False"
    )


# ── AC 8: only fires in TEACHING state ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_not_dispatched_outside_teaching_state():
    mock_redis = _make_fatigue_redis(state="QUIZZING", start_ts_offset=1000)
    mock_dispatch = AsyncMock(return_value={"current_state": "QUIZZING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue must NOT fire outside TEACHING state"


# ── AC 9 & 10: exhaustion fallback (needs S3-38) ─────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exhaustion_fallback_dispatches_when_all_mediapipe_none_after_floor():
    """Exhaustion fallback requires NormalizedSignal to support None MediaPipe fields (S3-38)."""
    from app.modules.tutor.service import NormalizedSignal

    # Probe whether None is accepted for required float fields
    try:
        none_sig = NormalizedSignal(
            session_id="probe",
            quiz_accuracy=None,
            teachback_score=None,
            behavioral_score=None,  # type: ignore[arg-type]
            head_pose_score=None,  # type: ignore[arg-type]
            blink_rate=None,  # type: ignore[arg-type]
        )
    except (TypeError, ValueError):
        pytest.skip("NormalizedSignal requires float for MediaPipe fields — S3-38 not merged")

    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=1000)
    mock_dispatch = AsyncMock(
        return_value={
            "current_state": "INTERVENING",
            "intervention_type": "fatigue",
            "intervention_message": "Take a break",
        }
    )

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch(
            "app.modules.tutor.state_machine.graph._can_intervene_fatigue",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.modules.tutor.service._segment_intervention_messages",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("app.modules.tutor.service._parse_signal", return_value=none_sig),
        patch("app.modules.tutor.service.compute_ces", return_value=30.0),
    ):
        from app.modules.tutor.service import process_attention_signal

        result = await process_attention_signal("sess-001", {"session_id": "sess-001"})

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) >= 1, "exhaustion fallback must dispatch fatigue_detected"
    assert result.intervention_dispatched is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exhaustion_fallback_not_dispatched_before_duration_floor():
    from app.modules.tutor.service import NormalizedSignal

    try:
        none_sig = NormalizedSignal(
            session_id="probe",
            quiz_accuracy=None,
            teachback_score=None,
            behavioral_score=None,  # type: ignore[arg-type]
            head_pose_score=None,  # type: ignore[arg-type]
            blink_rate=None,  # type: ignore[arg-type]
        )
    except (TypeError, ValueError):
        pytest.skip("NormalizedSignal requires float for MediaPipe fields — S3-38 not merged")

    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=100)  # only 100s
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch(
            "app.modules.tutor.state_machine.graph._can_intervene_fatigue",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.modules.tutor.service._segment_intervention_messages",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("app.modules.tutor.service._parse_signal", return_value=none_sig),
        patch("app.modules.tutor.service.compute_ces", return_value=30.0),
    ):
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", {"session_id": "sess-001"})

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "exhaustion fallback must NOT fire before duration floor"


# ── AC 11: WS tutor_intervene message delivered ───────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fatigue_tutor_intervene_ws_message_delivered_on_dispatch():
    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=1000)
    mock_dispatch = AsyncMock(
        return_value={
            "current_state": "INTERVENING",
            "intervention_type": "fatigue",
            "intervention_message": "Take a short break...",
        }
    )
    mock_manager_send = AsyncMock()

    with (
        patch("app.config.get_settings", return_value=_mock_settings()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch),
        patch(
            "app.modules.tutor.state_machine.graph._can_intervene_fatigue",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.modules.tutor.service._segment_intervention_messages",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("app.core.websocket.manager") as mock_manager,
    ):
        mock_manager.send = mock_manager_send
        from app.modules.tutor.service import process_attention_signal

        result = await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    assert result.intervention_dispatched is True, "fatigue_detected should have been dispatched"
    fatigue_ws = [c for c in mock_manager_send.call_args_list if "fatigue" in str(c)]
    assert len(fatigue_ws) >= 1, "tutor_intervene WS message must be sent with type=fatigue"
    sent_args, _ = fatigue_ws[0]
    sent_payload = sent_args[1]["payload"] if len(sent_args) > 1 else {}
    assert sent_payload.get("type") == "fatigue"
    assert sent_payload.get("message") == "Take a short break..."


# ── AC 12: lrange uses end index 1 ───────────────────────────────────────────


@pytest.mark.unit
def test_blink_history_lrange_uses_end_index_1_not_minus_1():
    """Source must use lrange(key, 0, 1) not lrange(key, 0, -1) for fatigue histories."""
    from app.modules.tutor import service

    src = inspect.getsource(service.process_attention_signal)
    assert "blink_history" in src
    assert "head_pose_history" in src
    # lrange with -1 on either history is unbounded and prohibited by AC12 / CLAUDE.md rule
    bad = re.compile(r"lrange.*(?:blink_history|head_pose_history).*-1")
    assert not bad.search(src), (
        "lrange for fatigue histories must use bounded end index 1, not -1"
    )


# ── AC 13: session_start_ts missing -> fail-closed ───────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_start_ts_missing_does_not_dispatch_fatigue():
    mock_redis = _make_fatigue_redis(state="TEACHING", start_ts_offset=1000)

    async def fake_get_no_ts(key: str):
        if "session_start_ts" in key:
            return None
        if "tutor_state" in key:
            return "TEACHING"
        if "quiz_deadline_at" in key:
            return None
        return None

    mock_redis.get = AsyncMock(side_effect=fake_get_no_ts)
    mock_dispatch = AsyncMock(return_value={"current_state": "TEACHING"})

    ps = _fatigue_patches(mock_redis, mock_dispatch, can_intervene=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4]:
        from app.modules.tutor.service import process_attention_signal

        await process_attention_signal("sess-001", _NORMAL_SIGNAL)

    fatigue_calls = [c for c in mock_dispatch.call_args_list if "fatigue_detected" in str(c)]
    assert len(fatigue_calls) == 0, "fatigue must NOT fire when session_start_ts key is missing"
