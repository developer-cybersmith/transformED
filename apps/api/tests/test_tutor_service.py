"""Unit tests for the tutor CES signal buffer (Dev 4 — Sprint 0 redis_lpush_pattern).

Covers ``apps/api/app/modules/tutor/service.py``:
- ``_parse_signal``           — boundary mapping (envelope/flat, required vs optional fields)
- ``process_attention_signal`` — Redis ``ces_window`` write + ``ces_history`` LPUSH/LTRIM/EXPIRE/LRANGE
  and the ``distraction_detected`` trigger guards (2-below-threshold + cooldown).

``process_attention_signal`` lazy-imports ``get_redis``, ``get_settings`` and ``dispatch_event`` inside
the function body, so the effective patch targets are the SOURCE modules
(``app.core.redis.get_redis`` etc.) — the namespaces the lazy ``from ... import`` resolve against.

All tests are ``@pytest.mark.unit`` — no real Redis / state machine. ``asyncio_mode = "auto"``
(pyproject.toml) runs the async tests directly.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.tutor.service import (
    CesResult,
    NormalizedSignal,
    _parse_signal,
    compute_ces,
)

_VALID_PAYLOAD = {
    "session_id": "sess-1",
    "quiz_accuracy": 0.8,
    "teachback_score": None,
    "behavioral_score": 0.9,
    "head_pose_score": 0.7,
    "blink_rate": 0.3,
}

_WINDOW_KEY = "session:sess-1:ces_window"
_HISTORY_KEY = "session:sess-1:ces_history"


def _settings_mock(threshold: float = 0.5) -> MagicMock:
    """A settings mock carrying the real §11 weights.

    compute_ces reads ces_weight_*, so the mock must expose real floats — otherwise the weights are
    MagicMock attributes and the arithmetic breaks. These are the real ``Settings`` defaults, so
    compute_ces returns the same value everywhere this mock is used (keeps buffer-write assertions
    exact) without constructing a real ``Settings()`` (which needs env vars at import time).
    """
    s = MagicMock()
    s.ces_threshold = threshold
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    return s


# The value process_attention_signal writes is whatever compute_ces returns — pin the buffer-write
# assertions to that (not a hard-coded number) so they track the real §11 formula. Computed under a
# patched get_settings so it uses the real weights without building an env-dependent Settings().
with patch("app.config.get_settings", return_value=_settings_mock()):
    _EXPECTED_CES = compute_ces(_parse_signal(_VALID_PAYLOAD))


def _setup(mocker, *, lrange_vals: list[str], exists: int = 0, threshold: float = 0.5):
    """Patch the three lazy-imported dependencies and return (mock_redis, mock_dispatch)."""
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=lrange_vals)
    mock_redis.exists = AsyncMock(return_value=exists)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mocker.patch("app.config.get_settings", return_value=_settings_mock(threshold))

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    return mock_redis, mock_dispatch


# ── Parsing (_parse_signal) ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_envelope_and_flat_equivalent() -> None:
    """AC1: a WsMessage envelope and a flat dict produce an equal NormalizedSignal."""
    envelope = {"type": "attention_signal", "payload": dict(_VALID_PAYLOAD)}
    flat = dict(_VALID_PAYLOAD)

    parsed_envelope = _parse_signal(envelope)
    parsed_flat = _parse_signal(flat)

    assert isinstance(parsed_envelope, NormalizedSignal)
    assert parsed_envelope == parsed_flat


@pytest.mark.unit
def test_parse_missing_session_id_raises() -> None:
    """AC2: missing session_id → ValueError."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "session_id"}
    with pytest.raises(ValueError):
        _parse_signal(payload)


@pytest.mark.unit
@pytest.mark.parametrize("field", ["behavioral_score", "head_pose_score", "blink_rate"])
def test_parse_missing_required_float_raises(field: str) -> None:
    """AC2: missing ANY required float → ValueError (covers all three _require_float branches)."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != field}
    with pytest.raises(ValueError):
        _parse_signal(payload)


@pytest.mark.unit
def test_parse_none_optionals_preserved() -> None:
    """AC3: quiz_accuracy=None and teachback_score=None are preserved as None."""
    payload = dict(_VALID_PAYLOAD)
    payload["quiz_accuracy"] = None
    payload["teachback_score"] = None

    parsed = _parse_signal(payload)

    assert parsed.quiz_accuracy is None
    assert parsed.teachback_score is None


@pytest.mark.unit
def test_parse_non_numeric_required_raises() -> None:
    """AC3: a non-numeric required field → ValueError."""
    payload = dict(_VALID_PAYLOAD)
    payload["behavioral_score"] = "abc"
    with pytest.raises(ValueError):
        _parse_signal(payload)


@pytest.mark.unit
def test_parse_non_numeric_optional_raises() -> None:
    """AC3: a non-numeric OPTIONAL field → ValueError (distinct _optional_float branch)."""
    payload = dict(_VALID_PAYLOAD)
    payload["quiz_accuracy"] = "x"
    with pytest.raises(ValueError):
        _parse_signal(payload)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_parse_non_finite_required_raises(bad) -> None:
    """Non-finite required field → ValueError. float('nan') would otherwise propagate through
    compute_ces and clamp to a misleading CES (NaN→100), silently suppressing interventions."""
    payload = dict(_VALID_PAYLOAD)
    payload["behavioral_score"] = bad
    with pytest.raises(ValueError):
        _parse_signal(payload)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_parse_non_finite_optional_raises(bad) -> None:
    """Non-finite OPTIONAL field → ValueError (distinct _optional_float branch)."""
    payload = dict(_VALID_PAYLOAD)
    payload["quiz_accuracy"] = bad
    with pytest.raises(ValueError):
        _parse_signal(payload)


# ── Buffer writes (process_attention_signal) ────────────────────────────────────


@pytest.mark.unit
async def test_ces_window_written_with_ttl(mocker) -> None:
    """AC4: ces_window is written with the 24 h TTL under the correct key."""
    mock_redis, _ = _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_redis.set.assert_any_call(_WINDOW_KEY, _EXPECTED_CES, ex=86400)


@pytest.mark.unit
async def test_history_lpush_ltrim_expire_called(mocker) -> None:
    """AC5: history is built via lpush → ltrim(key,0,9) → expire(key,86400), in that order."""
    mock_redis, _ = _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_redis.lpush.assert_any_call(_HISTORY_KEY, _EXPECTED_CES)
    mock_redis.ltrim.assert_any_call(_HISTORY_KEY, 0, 9)
    mock_redis.expire.assert_any_call(_HISTORY_KEY, 86400)

    # Order check: lpush must precede ltrim which must precede expire.
    method_order = [c[0] for c in mock_redis.mock_calls if c[0] in {"lpush", "ltrim", "expire"}]
    assert method_order.index("lpush") < method_order.index("ltrim") < method_order.index("expire")


@pytest.mark.unit
async def test_history_read_via_lrange(mocker) -> None:
    """AC6: history is read via lrange(key, 0, 9)."""
    mock_redis, _ = _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_redis.lrange.assert_any_call(_HISTORY_KEY, 0, 9)


# ── Trigger logic ───────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_two_below_threshold_no_cooldown_dispatches(mocker) -> None:
    """AC7: two most-recent values below threshold + no cooldown → distraction_detected."""
    _, mock_dispatch = _setup(mocker, lrange_vals=["0.1", "0.2"], exists=0, threshold=0.5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    # The dispatch now carries the current segment's pre-generated messages ({} here — the
    # _setup mock has no cached package, so selection degrades to empty).
    mock_dispatch.assert_called_once_with(
        "sess-1", "distraction_detected", payload={"intervention_messages": {}}
    )
    assert result.intervention_dispatched is True


@pytest.mark.unit
async def test_one_below_one_above_no_dispatch(mocker) -> None:
    """AC8: one below + one above threshold → no dispatch."""
    _, mock_dispatch = _setup(mocker, lrange_vals=["0.1", "0.9"], exists=0, threshold=0.5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_cooldown_blocks_dispatch(mocker) -> None:
    """AC9: both below threshold BUT cooldown active → no dispatch."""
    mock_redis, mock_dispatch = _setup(mocker, lrange_vals=["0.1", "0.2"], exists=1, threshold=0.5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    # The cooldown guard must actually be consulted — distinguishes "blocked by cooldown"
    # from "trigger never ran at all".
    mock_redis.exists.assert_called_once_with("tutor_cooldown:sess-1")
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_short_history_no_dispatch(mocker) -> None:
    """AC10: fewer than 2 history values → no dispatch."""
    _, mock_dispatch = _setup(mocker, lrange_vals=["0.1"], exists=0, threshold=0.5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_empty_history_no_dispatch(mocker) -> None:
    """AC10: empty history (the realistic first-signal case) → no dispatch, no IndexError."""
    _, mock_dispatch = _setup(mocker, lrange_vals=[], exists=0, threshold=0.5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_value_equal_to_threshold_no_dispatch(mocker) -> None:
    """Boundary: value == threshold is NOT below (strict <) → no dispatch.

    Guards against a `<` → `<=` mutation that would silently over-fire interventions.
    """
    _, mock_dispatch = _setup(mocker, lrange_vals=["0.5", "0.5"], exists=0, threshold=0.5)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


@pytest.mark.unit
async def test_only_two_most_recent_considered(mocker) -> None:
    """Trigger keys off history[:2] only — older below-threshold values must not count.

    history[0]=0.1 (below), history[1]=0.9 (above) → no dispatch, even though indices 2-3
    are below threshold.
    """
    _, mock_dispatch = _setup(
        mocker, lrange_vals=["0.1", "0.9", "0.05", "0.05"], exists=0, threshold=0.5
    )

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    assert result.intervention_dispatched is False


# ── Result ───────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_cesresult_fields(mocker) -> None:
    """AC11: CesResult carries the correct session_id and the computed ces.

    Pinned to the dynamic ``compute_ces(...)`` value (not a hard-coded stub) so it stays correct
    now that the real §11 formula is in place.
    """
    _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    assert isinstance(result, CesResult)
    assert result.session_id == "sess-1"
    assert result.ces == compute_ces(_parse_signal(_VALID_PAYLOAD))


# ── Intervention selection + delivery (s2-5) ──────────────────────────────────


def _intervention_redis(package_json: str | None) -> AsyncMock:
    """Key-aware Redis for the intervention-delivery path: triggers (lrange below threshold,
    no cooldown) and serves the cached package + segment index by key."""
    redis = AsyncMock()

    async def _get(key: str):
        if key == "lesson_package:sess-1":
            return package_json
        if key == "session:sess-1:segment_index":
            return "0"
        return None

    redis.get = AsyncMock(side_effect=_get)
    redis.lrange = AsyncMock(return_value=["0.1", "0.2"])  # 2 windows below threshold → trigger
    redis.exists = AsyncMock(return_value=0)  # no cooldown
    return redis


def _patch_dispatch(mocker, intervention_message):
    """Mock dispatch_event to return an INTERVENING result (real selection covered in test_tutor_graph)."""
    mock_dispatch = AsyncMock(
        return_value={
            "current_state": "INTERVENING",
            "intervention_message": intervention_message,
            "intervention_type": "distraction",
        }
    )
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)
    return mock_dispatch


@pytest.mark.unit
async def test_intervention_delivers_tutor_intervene_message(mocker) -> None:
    """Triggered intervention passes the segment's messages to the FSM and delivers tutor_intervene."""
    # Segment field is `interventions` per the frozen LessonPackage schema (SegmentInterventions).
    pkg = {
        "segments": [
            {"interventions": {"distraction": ["focus up", "x", "y"], "confusion": ["c"], "fatigue": ["f"]}}
        ]
    }
    mocker.patch("app.core.redis.get_redis", return_value=_intervention_redis(json.dumps(pkg)))
    mocker.patch("app.config.get_settings", return_value=_settings_mock(0.5))
    mock_dispatch = _patch_dispatch(mocker, "focus up")

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()
    mocker.patch("app.core.websocket.manager", mock_manager)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    # The segment's messages were passed into the dispatch payload.
    _, kwargs = mock_dispatch.call_args
    assert kwargs["payload"]["intervention_messages"]["distraction"][0] == "focus up"

    # The client received a ws.ts-shaped tutor_intervene message.
    mock_manager.send.assert_called_once()
    sid_arg, sent = mock_manager.send.call_args[0]
    assert sid_arg == "sess-1"
    assert sent["type"] == "tutor_intervene"
    assert sent["payload"]["message"] == "focus up"
    assert sent["payload"]["type"] == "distraction"
    assert sent["payload"]["session_id"] == "sess-1"
    assert result.intervention_dispatched is True


@pytest.mark.unit
async def test_intervention_no_delivery_on_cache_miss(mocker) -> None:
    """Cache miss → no message → tutor_intervene skipped; no crash; CesResult still returned."""
    mocker.patch("app.core.redis.get_redis", return_value=_intervention_redis(None))  # no cached package
    mocker.patch("app.config.get_settings", return_value=_settings_mock(0.5))
    _patch_dispatch(mocker, None)  # FSM returns no message when no package supplied

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()
    mocker.patch("app.core.websocket.manager", mock_manager)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_manager.send.assert_not_called()
    assert result.intervention_dispatched is True  # the intervention still fired in the FSM


@pytest.mark.unit
async def test_segment_complete_increments_segment_index(mocker) -> None:
    """advance_tutor_state(segment_complete) advances the current-segment pointer."""
    redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=redis)
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state("sess-9", "segment_complete")

    redis.incr.assert_called_once_with("session:sess-9:segment_index")
    redis.expire.assert_any_call("session:sess-9:segment_index", 86_400)
    mock_dispatch.assert_called_once_with("sess-9", "segment_complete")


# ── _segment_intervention_messages helper (direct unit coverage) ──────────────


def _pkg_redis(get_map: dict) -> AsyncMock:
    redis = AsyncMock()

    async def _get(key: str):
        return get_map.get(key)

    redis.get = AsyncMock(side_effect=_get)
    return redis


@pytest.mark.unit
async def test_segment_messages_returns_interventions_for_segment(mocker) -> None:
    """Reads the frozen `interventions` field for the current segment."""
    from app.modules.tutor.service import _segment_intervention_messages

    pkg = {"segments": [
        {"interventions": {"distraction": ["d0"], "confusion": ["c0"], "fatigue": ["f0"]}},
        {"interventions": {"distraction": ["d1"], "confusion": ["c1"], "fatigue": ["f1"]}},
    ]}
    redis = _pkg_redis({"lesson_package:s": json.dumps(pkg), "session:s:segment_index": "1"})

    out = await _segment_intervention_messages("s", redis)

    assert out == {"distraction": ["d1"], "confusion": ["c1"], "fatigue": ["f1"]}


@pytest.mark.unit
async def test_segment_messages_cache_miss_returns_empty(mocker) -> None:
    from app.modules.tutor.service import _segment_intervention_messages

    redis = _pkg_redis({})  # no cached package
    assert await _segment_intervention_messages("s", redis) == {}


@pytest.mark.unit
async def test_segment_messages_malformed_json_returns_empty(mocker) -> None:
    from app.modules.tutor.service import _segment_intervention_messages

    redis = _pkg_redis({"lesson_package:s": "not-json{"})
    assert await _segment_intervention_messages("s", redis) == {}


@pytest.mark.unit
async def test_segment_messages_empty_segments_returns_empty(mocker) -> None:
    from app.modules.tutor.service import _segment_intervention_messages

    redis = _pkg_redis({"lesson_package:s": json.dumps({"segments": []})})
    assert await _segment_intervention_messages("s", redis) == {}


@pytest.mark.unit
async def test_segment_messages_index_clamped_to_range(mocker) -> None:
    """An out-of-range segment_index (e.g. stale) clamps to the last segment instead of raising."""
    from app.modules.tutor.service import _segment_intervention_messages

    pkg = {"segments": [{"interventions": {"distraction": ["only"], "confusion": ["c"], "fatigue": ["f"]}}]}
    redis = _pkg_redis({"lesson_package:s": json.dumps(pkg), "session:s:segment_index": "9"})

    out = await _segment_intervention_messages("s", redis)

    assert out == {"distraction": ["only"], "confusion": ["c"], "fatigue": ["f"]}


# ── Group G — CES formula (s3-3 ces_computation) ──────────────────────────────
#
# compute_ces lazy-imports get_settings inside the function body, so the patch target is the SOURCE
# module ``app.config.get_settings`` (consistent with the rest of this file).


@pytest.mark.unit
def test_g1_all_signals_present(mocker) -> None:
    """AC1: 0–100 weighted score with all five signals present."""
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=0.8,
        teachback_score=0.6,
        behavioral_score=0.9,
        head_pose_score=0.7,
        blink_rate=0.3,
    )
    # (.8·.35 + .6·.25 + .9·.20 + .7·.12 + .3·.08)·100 = (.28+.15+.18+.084+.024)·100 = 71.8
    assert compute_ces(sig) == pytest.approx(71.8, abs=1e-3)


@pytest.mark.unit
def test_g2_teachback_none_redistributes(mocker) -> None:
    """AC2: teachback None → §11 redistribution (each present weight ÷ 0.75)."""
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=0.8,
        teachback_score=None,
        behavioral_score=0.9,
        head_pose_score=0.7,
        blink_rate=0.3,
    )
    # (.8·.46667 + .9·.26667 + .7·.16 + .3·.10667)·100 ≈ 75.733
    assert compute_ces(sig) == pytest.approx(75.733, abs=1e-2)


@pytest.mark.unit
def test_g3_quiz_and_teachback_none(mocker) -> None:
    """AC3: quiz + teachback both None → redistribute across the 3 present signals (weights sum .40)."""
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=None,
        teachback_score=None,
        behavioral_score=0.9,
        head_pose_score=0.7,
        blink_rate=0.3,
    )
    expected = (0.9 * 0.20 + 0.7 * 0.12 + 0.3 * 0.08) / 0.40 * 100
    result = compute_ces(sig)
    assert result == pytest.approx(expected, abs=1e-6)
    assert 0.0 <= result <= 100.0


@pytest.mark.unit
def test_g4_clamps_to_100(mocker) -> None:
    """AC6: an out-of-range input signal cannot push CES above 100."""
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=1.0,
        teachback_score=1.0,
        behavioral_score=2.0,  # bad input (parser is type-checked, not range-checked)
        head_pose_score=1.0,
        blink_rate=1.0,
    )
    assert compute_ces(sig) <= 100.0


@pytest.mark.unit
def test_g4b_clamps_to_zero(mocker) -> None:
    """AC6 lower bound: a negative input signal cannot push CES below 0."""
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=-5.0,  # bad input
        teachback_score=-5.0,
        behavioral_score=-5.0,
        head_pose_score=-5.0,
        blink_rate=-5.0,
    )
    assert compute_ces(sig) == 0.0


@pytest.mark.unit
def test_g4c_all_none_returns_zero(mocker) -> None:
    """The weight_sum<=0 guard: an all-None signal (constructible directly) degrades to 0.0, not a
    crash. Unreachable via _parse_signal (3 fields are required) but compute_ces is called directly."""
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=None,
        teachback_score=None,
        behavioral_score=None,  # type: ignore[arg-type]
        head_pose_score=None,  # type: ignore[arg-type]
        blink_rate=None,  # type: ignore[arg-type]
    )
    assert compute_ces(sig) == 0.0


@pytest.mark.unit
async def test_g5_tutor_ces_written(mocker) -> None:
    """AC4: process_attention_signal persists the CES to tutor_ces:{session_id} with the 24 h TTL."""
    mock_redis, _ = _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_redis.set.assert_any_call("tutor_ces:sess-1", _EXPECTED_CES, ex=86400)


@pytest.mark.unit
def test_g6_compute_ces_benchmark_under_5ms(mocker) -> None:
    """AC5: in-process compute_ces averages < 5 ms/call. Pure arithmetic — expect microseconds.

    Measures the IN-PROCESS computation only; Redis network I/O is excluded (environment-dependent).
    """
    mocker.patch("app.config.get_settings", return_value=_settings_mock())

    sig = NormalizedSignal(
        session_id="s",
        quiz_accuracy=0.8,
        teachback_score=0.6,
        behavioral_score=0.9,
        head_pose_score=0.7,
        blink_rate=0.3,
    )
    compute_ces(sig)  # warmup — exclude the first-call lazy import from the measurement
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        compute_ces(sig)
    per_call = (time.perf_counter() - t0) / n
    assert per_call < 0.005
