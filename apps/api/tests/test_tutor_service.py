"""Unit tests for the tutor CES signal buffer (Dev 4 — Sprint 0 redis_lpush_pattern).

Covers ``apps/api/app/modules/tutor/service.py``:
- ``_parse_signal``           — boundary mapping (envelope/flat, required vs optional fields)
- ``process_attention_signal`` — Redis ``ces_window`` write + ``ces_history``
  LPUSH/LTRIM/EXPIRE/LRANGE and the ``distraction_detected`` trigger guards
  (2-below-threshold + cooldown).

``process_attention_signal`` lazy-imports ``get_redis``, ``get_settings`` and
``dispatch_event`` inside the function body, so the effective patch targets are the SOURCE modules
(``app.core.redis.get_redis`` etc.) — the namespaces the lazy ``from ... import`` resolve against.

All tests are ``@pytest.mark.unit`` — no real Redis / state machine. ``asyncio_mode = "auto"``
(pyproject.toml) runs the async tests directly.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, call

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

# The value process_attention_signal writes is whatever compute_ces returns — pin the
# assertions to that (currently the 0.5 stub) so they stay correct when Dev 3 swaps in
# the real formula, rather than hard-coding 0.5 in the buffer-write checks.
_EXPECTED_CES = compute_ces(_parse_signal(_VALID_PAYLOAD))


def _settings_mock(threshold: float = 0.5) -> MagicMock:
    """MagicMock settings carrying the five §11 CES weights (config.py defaults).

    compute_ces() reads settings.ces_weight_* at call time; without these a bare
    MagicMock leaks into weight_sum and raises TypeError. Matching config defaults
    makes compute_ces() on the mock equal the module-level _EXPECTED_CES.
    D4 (S3-49): ces_cadence_seconds must also be set — gap check compares int <= int.
    """
    s = MagicMock()
    s.ces_threshold = threshold
    s.ces_cadence_seconds = 5  # D4: gap tolerance = 2 * 5 = 10 s
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    return s


def _setup(
    mocker,
    *,
    lrange_vals: list[str],
    exists: int = 0,
    threshold: float = 0.5,
    can_dispatch: bool = True,
):
    """Patch the lazy-imported dependencies and return (mock_redis, mock_dispatch).

    can_dispatch controls the return value of the Lua-backed _can_intervene_distraction
    guard (D6). Set False to simulate cooldown / max-reached without a real Redis.
    """
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=lrange_vals)
    mock_redis.exists = AsyncMock(return_value=exists)

    # Key-aware get: tutor_state must be TEACHING for the CES intervention guard to fire
    # (CLAUDE.md §10 — CES interventions only active in TEACHING). All other keys default to None:
    # no cached lesson_package → selection degrades to {} (cache-miss), no QUIZZING deadline set.
    # Without this, the 4-8 package fetch would json.loads() a bare AsyncMock and raise.
    async def _get(key: str):
        if key == "tutor_state:sess-1":
            return "TEACHING"
        return None

    mock_redis.get = AsyncMock(side_effect=_get)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mocker.patch("app.config.get_settings", return_value=_settings_mock(threshold))

    # D6 — _can_intervene_distraction is now a Lua-backed atomic guard. Patch it so
    # tests stay unit-level (no real Redis eval). The source-level behaviour (eval called
    # with correct keys/args, fail-closed, etc.) is covered in test_s3_48_lua_distraction_cap.py.
    mock_guard = mocker.patch(
        "app.modules.tutor.state_machine.graph._can_intervene_distraction",
        new_callable=AsyncMock,
    )
    mock_guard.return_value = can_dispatch

    # dispatch_event returns the FSM result dict. Default to INTERVENING with no message so a fired
    # trigger doesn't spuriously enter the 4-8 delivery path — result.get("intervention_message")
    # would otherwise be a truthy MagicMock driving manager.send against the real manager. Delivery
    # is covered explicitly by the _intervention_redis tests below.
    mock_dispatch = AsyncMock(
        return_value={"current_state": "INTERVENING", "intervention_message": None}
    )
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
def test_parse_missing_behavioral_signal_returns_none(field: str) -> None:
    """S3-38 D13 (MediaPipe frame drop): behavioral/head_pose/blink absent or null → None.

    These signals are optional because MediaPipe can drop frames. The old test
    expected ValueError (required-field), but the field is now _optional_float.
    """
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != field}
    parsed = _parse_signal(payload)
    assert getattr(parsed, field) is None, (
        f"_parse_signal must return None for missing {field!r}, not raise"
    )


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
    """AC5: history is built via lpush → ltrim(key,0,9) → expire(key,86400), in that order.

    D4 (S3-49): lpush value is a JSON string {"v": float, "t": int}, not a bare float.
    """
    mock_redis, _ = _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    # D4: the pushed value is a JSON string — find the call by key and validate the format.
    import json as _json  # noqa: PLC0415

    history_calls = [c for c in mock_redis.lpush.call_args_list if c.args[0] == _HISTORY_KEY]
    assert history_calls, "lpush must be called with the ces_history key"
    pushed = _json.loads(history_calls[0].args[1])
    assert isinstance(pushed.get("v"), float)
    assert isinstance(pushed.get("t"), int)
    assert abs(pushed["v"] - _EXPECTED_CES) < 0.001

    mock_redis.ltrim.assert_any_call(_HISTORY_KEY, 0, 9)
    mock_redis.expire.assert_any_call(_HISTORY_KEY, 86400)

    # Order check: lpush must precede ltrim which must precede expire.
    method_order = [c[0] for c in mock_redis.mock_calls if c[0] in {"lpush", "ltrim", "expire"}]
    assert method_order.index("lpush") < method_order.index("ltrim") < method_order.index("expire")


@pytest.mark.unit
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
    """AC9: both below threshold BUT Lua guard returns False (cooldown/cap) → no dispatch.

    D6: the guard is now _can_intervene_distraction (Lua) — no separate redis.exists call.
    We simulate the guard returning False (as it would when in cooldown or at the cap).
    """
    _, mock_dispatch = _setup(
        mocker, lrange_vals=["0.1", "0.2"], threshold=0.5, can_dispatch=False
    )

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
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
    """AC11: CesResult carries the correct session_id and the real §11 weighted CES."""
    _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    assert isinstance(result, CesResult)
    assert result.session_id == "sess-1"
    # Pinned to the real formula (0.5 stub is gone); _EXPECTED_CES ≈ 75.733 for _VALID_PAYLOAD.
    assert result.ces == _EXPECTED_CES
    # Concrete literal anchor so this is NOT circular: a compute_ces regression would move
    # _EXPECTED_CES with the code, but not this hard-coded §11 value.
    assert result.ces == pytest.approx(75.733, abs=0.01)


# ── Intervention selection + delivery (s2-5) ──────────────────────────────────


def _intervention_redis(package_json: str | None) -> AsyncMock:
    """Key-aware Redis for the intervention-delivery path: triggers (lrange below threshold,
    no cooldown) and serves the cached package + segment index by key."""
    redis = AsyncMock()

    async def _get(key: str):
        if key == "tutor_state:sess-1":
            return "TEACHING"  # §10: CES interventions only fire in TEACHING state
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
    """Mock dispatch_event to return an INTERVENING result
    (real selection covered in test_tutor_graph)."""
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
    """Triggered intervention passes the segment's messages to the FSM
    and delivers tutor_intervene."""
    # Segment field is `interventions` per the frozen LessonPackage schema (SegmentInterventions).
    pkg = {
        "segments": [
            {
                "interventions": {
                    "distraction": ["focus up", "x", "y"],
                    "confusion": ["c"],
                    "fatigue": ["f"],
                }
            }
        ]
    }
    mocker.patch("app.core.redis.get_redis", return_value=_intervention_redis(json.dumps(pkg)))
    mocker.patch("app.config.get_settings", return_value=_settings_mock(0.5))
    # D6: Lua guard — mock returning True so the dispatch path is exercised.
    _guard = mocker.patch(
        "app.modules.tutor.state_machine.graph._can_intervene_distraction",
        new_callable=AsyncMock,
    )
    _guard.return_value = True
    mock_dispatch = _patch_dispatch(mocker, "focus up")

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()
    mocker.patch("app.core.websocket.manager", mock_manager)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    # The segment's messages were passed into the dispatch payload.
    _, kwargs = mock_dispatch.call_args
    assert kwargs["payload"]["intervention_messages"]["distraction"][0] == "focus up"

    # Bug fix: every attention signal now also emits a ces_update, so a fired
    # intervention means TWO sends this window, not one -- find each by type
    # rather than assuming call_args is the only/last call.
    assert mock_manager.send.call_count == 2
    sent_messages = [call.args[1] for call in mock_manager.send.call_args_list]
    ces_sent = next(m for m in sent_messages if m["type"] == "ces_update")
    assert ces_sent["payload"]["session_id"] == "sess-1"

    # The client received a ws.ts-shaped tutor_intervene message.
    sent = next(m for m in sent_messages if m["type"] == "tutor_intervene")
    assert sent["payload"]["message"] == "focus up"
    assert sent["payload"]["type"] == "distraction"
    assert sent["payload"]["session_id"] == "sess-1"
    assert result.intervention_dispatched is True


@pytest.mark.unit
async def test_intervention_no_delivery_on_cache_miss(mocker) -> None:
    """Cache miss → no message → tutor_intervene skipped; no crash; CesResult still returned."""
    mocker.patch(
        "app.core.redis.get_redis", return_value=_intervention_redis(None)
    )  # no cached package
    mocker.patch("app.config.get_settings", return_value=_settings_mock(0.5))
    # D6: Lua guard — mock returning True; dispatch fires but message is None.
    _guard = mocker.patch(
        "app.modules.tutor.state_machine.graph._can_intervene_distraction",
        new_callable=AsyncMock,
    )
    _guard.return_value = True
    _patch_dispatch(mocker, None)  # FSM returns no message when no package supplied

    mock_manager = MagicMock()
    mock_manager.send = AsyncMock()
    mocker.patch("app.core.websocket.manager", mock_manager)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    # Bug fix: ces_update is sent on every signal regardless of intervention
    # delivery -- tutor_intervene is skipped here (cache miss, no message),
    # but that must not suppress the (unrelated) ces_update send.
    mock_manager.send.assert_called_once()
    sid_arg, sent = mock_manager.send.call_args[0]
    assert sid_arg == "sess-1"
    assert sent["type"] == "ces_update"
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

    pkg = {
        "segments": [
            {"interventions": {"distraction": ["d0"], "confusion": ["c0"], "fatigue": ["f0"]}},
            {"interventions": {"distraction": ["d1"], "confusion": ["c1"], "fatigue": ["f1"]}},
        ]
    }
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

    pkg = {
        "segments": [
            {"interventions": {"distraction": ["only"], "confusion": ["c"], "fatigue": ["f"]}}
        ]
    }
    redis = _pkg_redis({"lesson_package:s": json.dumps(pkg), "session:s:segment_index": "9"})

    out = await _segment_intervention_messages("s", redis)

    assert out == {"distraction": ["only"], "confusion": ["c"], "fatigue": ["f"]}


# ── Story 4-20: _quiz_deadline_expired helper ─────────────────────────────────


@pytest.mark.unit
async def test_quiz_deadline_expired_true_when_past() -> None:
    """_quiz_deadline_expired returns True when the stored timestamp is in the past."""
    import time as _time

    from app.modules.tutor.service import _quiz_deadline_expired

    past = str(int(_time.time()) - 10)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=past)

    assert await _quiz_deadline_expired("s", redis) is True


@pytest.mark.unit
async def test_quiz_deadline_expired_false_when_future() -> None:
    """_quiz_deadline_expired returns False when the stored timestamp is in the future."""
    import time as _time

    from app.modules.tutor.service import _quiz_deadline_expired

    future = str(int(_time.time()) + 3600)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=future)

    assert await _quiz_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_quiz_deadline_expired_false_when_key_missing() -> None:
    """_quiz_deadline_expired returns False (safe default) when the key is absent."""
    from app.modules.tutor.service import _quiz_deadline_expired

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    assert await _quiz_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_quiz_deadline_expired_false_on_redis_error() -> None:
    """_quiz_deadline_expired returns False (never crashes) when Redis raises."""
    from app.modules.tutor.service import _quiz_deadline_expired

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=RuntimeError("redis down"))

    assert await _quiz_deadline_expired("s", redis) is False


# ── Story 4-20: advance_tutor_state deadline check ────────────────────────────


@pytest.mark.unit
async def test_advance_tutor_state_quizzing_expired_dispatches_quiz_complete(mocker) -> None:
    """AC2: QUIZZING + expired deadline → advance_tutor_state dispatches quiz_complete."""
    import time as _time

    sid = "s-adv-exp"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "QUIZZING"
        if key == f"session:{sid}:quiz_deadline_at":
            return expired
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.delete = AsyncMock(return_value=1)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "quiz_complete")

    mock_dispatch.assert_called_once_with(sid, "quiz_complete")
    redis.delete.assert_awaited_once_with(f"session:{sid}:quiz_deadline_at")


@pytest.mark.unit
async def test_advance_tutor_state_double_fire_guard_no_dispatch_on_second(mocker) -> None:
    """AC2: redis.delete returns 0 (key already gone) → second dispatch is suppressed."""
    import time as _time

    sid = "s-adv-dfg"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "QUIZZING"
        if key == f"session:{sid}:quiz_deadline_at":
            return expired
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.delete = AsyncMock(return_value=0)  # key already deleted by a concurrent signal
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "quiz_complete")

    mock_dispatch.assert_not_called()


@pytest.mark.unit
async def test_advance_tutor_state_non_quizzing_state_normal_dispatch(mocker) -> None:
    """AC2: non-QUIZZING state → deadline check skipped, event dispatched normally."""
    sid = "s-adv-teach"

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "TEACHING"
        return None  # no quiz_deadline_at — state guard exits before reading it

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "segment_complete")

    mock_dispatch.assert_called_once_with(sid, "segment_complete")


# ── Story 4-20: process_attention_signal deadline check ──────────────────────


def _attention_deadline_setup(mocker, *, expired: bool, has_deadline: bool = True):
    """Setup for process_attention_signal deadline tests.

    Returns (mock_redis, mock_dispatch). History has only 1 value so the
    distraction trigger (len >= 2) is never reached — deadline path isolated.
    """
    import time as _time

    if has_deadline:
        deadline = str(int(_time.time()) - 60) if expired else str(int(_time.time()) + 3600)
    else:
        deadline = None

    async def _get(key: str):
        if "tutor_state" in key:
            return "QUIZZING"
        if "quiz_deadline_at" in key:
            return deadline
        return None  # lesson_package, segment_index — empty

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=_get)
    mock_redis.lrange = AsyncMock(return_value=["0.9"])  # 1 value → no distraction trigger
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.delete = AsyncMock(return_value=1 if (has_deadline and expired) else 0)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.ces_threshold = 50
    # Numeric weights required by compute_ces — avoids TypeError on MagicMock arithmetic
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    mock_settings.ces_weight_behavioral = 0.20
    mock_settings.ces_weight_head_pose = 0.12
    mock_settings.ces_weight_blink = 0.08
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    return mock_redis, mock_dispatch


@pytest.mark.unit
async def test_process_attention_quizzing_expired_deadline_dispatches_quiz_complete(mocker) -> None:
    """AC3: QUIZZING + expired deadline → process_attention_signal auto-dispatches quiz_complete."""
    mock_redis, mock_dispatch = _attention_deadline_setup(mocker, expired=True)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_called_once_with("sess-1", "quiz_complete")
    mock_redis.delete.assert_awaited_once_with("session:sess-1:quiz_deadline_at")
    assert isinstance(result, CesResult)
    assert result.intervention_dispatched is False  # auto-advance path must not set the flag


@pytest.mark.unit
async def test_process_attention_quizzing_active_deadline_no_auto_dispatch(mocker) -> None:
    """AC3/AC6: QUIZZING + deadline not yet expired → no auto-dispatch."""
    _, mock_dispatch = _attention_deadline_setup(mocker, expired=False)

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()


@pytest.mark.unit
async def test_process_attention_quizzing_missing_deadline_no_auto_dispatch(mocker) -> None:
    """AC6: QUIZZING + missing quiz_deadline_at → graceful no-op, no crash."""
    _, mock_dispatch = _attention_deadline_setup(mocker, expired=False, has_deadline=False)

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()


@pytest.mark.unit
async def test_process_attention_deadline_double_fire_guard(mocker) -> None:
    """AC3: delete returns 0 (key gone) → second dispatch suppressed even in QUIZZING+expired."""
    mock_redis, mock_dispatch = _attention_deadline_setup(mocker, expired=True)
    mock_redis.delete = AsyncMock(return_value=0)  # simulate concurrent delete

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()


# ── Story 4-20 review patches ─────────────────────────────────────────────────


@pytest.mark.unit
async def test_advance_tutor_state_non_quiz_complete_event_substituted_on_expired_deadline(
    mocker,
) -> None:
    """AC2 substitution: non-quiz_complete event (segment_complete) while QUIZZING+expired
    → quiz_complete dispatched instead, original event dropped."""
    import time as _time

    sid = "s-adv-sub"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "QUIZZING"
        if key == f"session:{sid}:quiz_deadline_at":
            return expired
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.delete = AsyncMock(return_value=1)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "segment_complete")  # client sends segment_complete

    # quiz_complete dispatched instead; segment_complete never reached
    mock_dispatch.assert_called_once_with(sid, "quiz_complete")


@pytest.mark.unit
async def test_quiz_deadline_expired_false_on_corrupt_redis_value() -> None:
    """_quiz_deadline_expired returns False (safely) when the stored value is non-numeric."""
    from app.modules.tutor.service import _quiz_deadline_expired

    redis = AsyncMock()
    redis.get = AsyncMock(return_value="CORRUPT_NOT_A_TIMESTAMP")

    assert await _quiz_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_process_attention_quizzing_expired_with_low_ces_only_quiz_complete_dispatched(
    mocker,
) -> None:
    """P7: QUIZZING + expired deadline + two below-threshold CES values →
    ONLY quiz_complete dispatched (no distraction_detected) — CLAUDE.md §10:
    CES interventions only active in TEACHING state."""
    import time as _time

    sid = "sess-double"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if "tutor_state" in key:
            return "QUIZZING"
        if "quiz_deadline_at" in key:
            return expired
        return None

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=_get)
    # Two below-threshold CES values — would trigger distraction in TEACHING state
    mock_redis.lrange = AsyncMock(return_value=["0.1", "0.2"])
    mock_redis.exists = AsyncMock(return_value=0)  # no cooldown
    mock_redis.delete = AsyncMock(return_value=1)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.ces_threshold = 50
    mock_settings.ces_cadence_seconds = 5  # D4 (S3-49): gap check requires int attribute
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    mock_settings.ces_weight_behavioral = 0.20
    mock_settings.ces_weight_head_pose = 0.12
    mock_settings.ces_weight_blink = 0.08
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal(sid, _VALID_PAYLOAD)

    # Only quiz_complete — distraction_detected must NOT fire from QUIZZING state
    mock_dispatch.assert_called_once_with(sid, "quiz_complete")
    assert result.intervention_dispatched is False


# ── Story 4-24 / D63: INTERVENING recovery — event path + timeout safety net ──


@pytest.mark.unit
def test_intervention_complete_is_client_drivable() -> None:
    """AC1: intervention_complete is allow-listed — previously it was dispatched by nothing."""
    from app.modules.tutor.service import _CLIENT_DRIVABLE_EVENTS

    assert "intervention_complete" in _CLIENT_DRIVABLE_EVENTS


@pytest.mark.unit
async def test_intervention_deadline_expired_true_when_past() -> None:
    """_intervention_deadline_expired returns True when the stored timestamp is in the past."""
    import time as _time

    from app.modules.tutor.service import _intervention_deadline_expired

    past = str(int(_time.time()) - 10)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=past)

    assert await _intervention_deadline_expired("s", redis) is True


@pytest.mark.unit
async def test_intervention_deadline_expired_false_when_future() -> None:
    """AC4: still within the timeout window → not expired."""
    import time as _time

    from app.modules.tutor.service import _intervention_deadline_expired

    future = str(int(_time.time()) + 3600)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=future)

    assert await _intervention_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_intervention_deadline_expired_false_when_key_missing() -> None:
    """No intervention has ever fired (or it already cleared) → safe default False."""
    from app.modules.tutor.service import _intervention_deadline_expired

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    assert await _intervention_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_intervention_deadline_expired_false_on_redis_error() -> None:
    """Never crashes the hot path — a Redis blip degrades to False (stay put)."""
    from app.modules.tutor.service import _intervention_deadline_expired

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=RuntimeError("redis down"))

    assert await _intervention_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_intervention_deadline_expired_false_on_corrupt_redis_value() -> None:
    """Non-numeric stored value degrades safely to False, not a crash."""
    from app.modules.tutor.service import _intervention_deadline_expired

    redis = AsyncMock()
    redis.get = AsyncMock(return_value="CORRUPT_NOT_A_TIMESTAMP")

    assert await _intervention_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_intervention_deadline_expired_false_at_exact_equality(mocker) -> None:
    """Review finding (2026-08-11, PR #129 six-layer review, Edge Case Hunter layer): the
    exact-equality boundary (time.time() == deadline) was previously untested on both the
    INTERVENING and QUIZZING sides. The comparison is strict `>` (not expired yet at the exact
    deadline instant) — pinning this so a future edit silently drifting to `>=` is caught."""
    import time as _time

    from app.modules.tutor.service import _intervention_deadline_expired

    frozen_now = 1_700_000_000.0
    mocker.patch.object(_time, "time", return_value=frozen_now)
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=str(frozen_now))

    assert await _intervention_deadline_expired("s", redis) is False


@pytest.mark.unit
async def test_advance_tutor_state_intervening_expired_dispatches_intervention_complete(
    mocker,
) -> None:
    """AC3: INTERVENING + expired deadline → advance_tutor_state self-heals to TEACHING
    WITHOUT any client-sent intervention_complete. The client sent segment_complete instead —
    Review Patch #11 (2026-08-11): that event must now be REPLAYED after the self-heal, not
    dropped, so this also proves segment_index gets incremented."""
    import time as _time

    sid = "s-interv-exp"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "INTERVENING"
        if key == f"session:{sid}:intervention_deadline_at":
            return expired
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.eval = AsyncMock(return_value=1)  # atomic compare-and-delete succeeds
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "segment_complete")  # client sent something else entirely

    # Both fire, in order: the self-heal, THEN the replayed client event.
    assert mock_dispatch.await_args_list == [
        call(sid, "intervention_complete"),
        call(sid, "segment_complete"),
    ]
    redis.eval.assert_awaited_once()
    # segment_complete's own side effect (segment_index increment) must still run.
    redis.incr.assert_awaited_once_with(f"session:{sid}:segment_index")


@pytest.mark.unit
async def test_advance_tutor_state_intervening_double_fire_guard(mocker) -> None:
    """AC5: redis.eval (atomic compare-and-delete) returns 0 — a concurrent caller already
    claimed/refreshed the deadline. This call must NOT also dispatch a redundant synthetic
    intervention_complete — but the client's own real event (segment_complete here) still
    reaches the FSM exactly once via the normal path, per Review Patch #11."""
    import time as _time

    sid = "s-interv-dfg"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "INTERVENING"
        if key == f"session:{sid}:intervention_deadline_at":
            return expired
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.eval = AsyncMock(return_value=0)  # lost the race — someone else already claimed it
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "segment_complete")

    # Exactly one dispatch — the client's real event — and it is NOT the synthetic one.
    mock_dispatch.assert_called_once_with(sid, "segment_complete")


@pytest.mark.unit
async def test_advance_tutor_state_intervening_lost_race_still_dispatches_real_dismiss(
    mocker,
) -> None:
    """Review finding fix (2026-08-11): before this fix, losing the internal race while the
    client's OWN event was the real intervention_complete dismiss silently dropped it entirely
    (the old code's unconditional `return` after the double-fire guard). Now it must still reach
    dispatch_event exactly once, via the normal fall-through — never zero, never twice."""
    import time as _time

    sid = "s-interv-lost-race-dismiss"
    expired = str(int(_time.time()) - 60)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "INTERVENING"
        if key == f"session:{sid}:intervention_deadline_at":
            return expired
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    redis.eval = AsyncMock(return_value=0)  # lost the race
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "intervention_complete")

    mock_dispatch.assert_called_once_with(sid, "intervention_complete")


@pytest.mark.unit
async def test_advance_tutor_state_intervening_not_expired_dispatches_original_event(
    mocker,
) -> None:
    """AC4: INTERVENING but still within the timeout window → the client's real event
    (intervention_complete, the normal dismiss path) is dispatched as-is, untouched by the
    safety net. Review Patch #4 (2026-08-11): the original version of this test could not
    distinguish "guard correctly skipped" from "guard incorrectly fired the self-heal", because
    both paths dispatched the identical intervention_complete string. redis.eval.assert_not_called()
    is what actually makes that distinction — the self-heal path always calls it, the pass-through
    path never does."""
    import time as _time

    sid = "s-interv-live"
    future = str(int(_time.time()) + 3600)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "INTERVENING"
        if key == f"session:{sid}:intervention_deadline_at":
            return future
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "intervention_complete")

    mock_dispatch.assert_called_once_with(sid, "intervention_complete")
    redis.eval.assert_not_called()


@pytest.mark.unit
async def test_advance_tutor_state_intervening_other_event_not_expired_is_noop(mocker) -> None:
    """CRITICAL regression test — Review Patch #1 (2026-08-11, Scale & Load Hunter finding).

    Before this fix: INTERVENING + NOT yet expired + any client event other than
    intervention_complete fell through to dispatch_event, which route_from_intervening routed
    straight back into intervening_node — unconditionally re-arming intervention_deadline_at and
    perpetually reopening the exact one-way trap D63 exists to close. A client sending any of the
    other 8 _CLIENT_DRIVABLE_EVENTS at least once per intervention_timeout_seconds while an
    intervention was showing would defeat the entire safety net.

    This test proves the fix: dispatch_event must NOT be called at all in this scenario."""
    import time as _time

    sid = "s-interv-rearm-regression"
    future = str(int(_time.time()) + 3600)

    async def _get(key: str):
        if key == f"tutor_state:{sid}":
            return "INTERVENING"
        if key == f"session:{sid}:intervention_deadline_at":
            return future
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    mocker.patch("app.core.redis.get_redis", return_value=redis)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.modules.tutor.service import advance_tutor_state

    await advance_tutor_state(sid, "segment_complete")

    mock_dispatch.assert_not_called()
    redis.eval.assert_not_called()
    # The pre-D63-fix code also incremented segment_index unconditionally before dispatch — the
    # no-op must skip that too, since the segment boundary hasn't actually been processed by the
    # FSM (the session is still, correctly, sitting in INTERVENING).
    redis.incr.assert_not_called()


def _interv_attention_deadline_setup(mocker, *, expired: bool, has_deadline: bool = True):
    """Setup for process_attention_signal INTERVENING-deadline tests. History has only 1 value
    so the distraction trigger (len >= 2) is never reached — deadline path isolated."""
    import time as _time

    if has_deadline:
        deadline = str(int(_time.time()) - 60) if expired else str(int(_time.time()) + 3600)
    else:
        deadline = None

    async def _get(key: str):
        if "tutor_state" in key:
            return "INTERVENING"
        if "intervention_deadline_at" in key:
            return deadline
        return None  # lesson_package, segment_index — empty

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=_get)
    mock_redis.lrange = AsyncMock(return_value=["0.9"])  # 1 value → no distraction trigger
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.eval = AsyncMock(return_value=1 if (has_deadline and expired) else 0)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.ces_threshold = 50
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    mock_settings.ces_weight_behavioral = 0.20
    mock_settings.ces_weight_head_pose = 0.12
    mock_settings.ces_weight_blink = 0.08
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    return mock_redis, mock_dispatch


@pytest.mark.unit
async def test_process_attention_intervening_expired_dispatches_intervention_complete(
    mocker,
) -> None:
    """AC3: a session stuck in INTERVENING past the deadline self-heals on the very next
    attention signal — no client event required at all. This is the core D63 guarantee."""
    mock_redis, mock_dispatch = _interv_attention_deadline_setup(mocker, expired=True)

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_called_once_with("sess-1", "intervention_complete")
    mock_redis.eval.assert_awaited_once()
    assert isinstance(result, CesResult)


@pytest.mark.unit
async def test_process_attention_intervening_not_expired_no_dispatch(mocker) -> None:
    """AC4: still within the timeout window → no auto-dispatch, session stays INTERVENING."""
    mock_redis, mock_dispatch = _interv_attention_deadline_setup(mocker, expired=False)

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()
    mock_redis.eval.assert_not_called()


@pytest.mark.unit
async def test_process_attention_intervening_double_fire_guard(mocker) -> None:
    """AC5: two concurrent expired-deadline checks on the same session must not both dispatch —
    redis.eval (atomic compare-and-delete) returning 0 (a concurrent caller already won)
    suppresses this one."""
    mock_redis, mock_dispatch = _interv_attention_deadline_setup(mocker, expired=True)
    mock_redis.eval = AsyncMock(return_value=0)  # simulate the race already lost

    from app.modules.tutor.service import process_attention_signal

    await process_attention_signal("sess-1", _VALID_PAYLOAD)

    mock_dispatch.assert_not_called()


# ── Review Patch: _delete_intervention_deadline_if_expired atomic helper ──────────


@pytest.mark.unit
async def test_delete_intervention_deadline_if_expired_true_when_script_deletes() -> None:
    """redis.eval returning a truthy result (1) means the script's own compare found it
    expired and deleted it — the helper reports True."""
    from app.modules.tutor.service import _delete_intervention_deadline_if_expired

    redis = AsyncMock()
    redis.eval = AsyncMock(return_value=1)

    assert await _delete_intervention_deadline_if_expired("s", redis) is True
    redis.eval.assert_awaited_once()


@pytest.mark.unit
async def test_delete_intervention_deadline_if_expired_false_when_script_returns_zero() -> None:
    """redis.eval returning 0 means the script's own compare found it NOT expired (or the key
    was already gone) — the helper reports False, and nothing was deleted."""
    from app.modules.tutor.service import _delete_intervention_deadline_if_expired

    redis = AsyncMock()
    redis.eval = AsyncMock(return_value=0)

    assert await _delete_intervention_deadline_if_expired("s", redis) is False


@pytest.mark.unit
async def test_delete_intervention_deadline_if_expired_false_on_redis_error() -> None:
    """Never crashes the hot path — a Redis/EVAL error (including no Lua support) degrades to
    False, never a dispatch on an uncertain result."""
    from app.modules.tutor.service import _delete_intervention_deadline_if_expired

    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=RuntimeError("redis down"))

    assert await _delete_intervention_deadline_if_expired("s", redis) is False
