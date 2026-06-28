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

from unittest.mock import AsyncMock, MagicMock

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


def _setup(mocker, *, lrange_vals: list[str], exists: int = 0, threshold: float = 0.5):
    """Patch the three lazy-imported dependencies and return (mock_redis, mock_dispatch)."""
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=lrange_vals)
    mock_redis.exists = AsyncMock(return_value=exists)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.ces_threshold = threshold
    mocker.patch("app.config.get_settings", return_value=mock_settings)

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

    mock_dispatch.assert_called_once_with("sess-1", "distraction_detected")
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
    """AC11: CesResult carries the correct session_id and ces (stub 0.5)."""
    _setup(mocker, lrange_vals=["0.5"])

    from app.modules.tutor.service import process_attention_signal

    result = await process_attention_signal("sess-1", _VALID_PAYLOAD)

    assert isinstance(result, CesResult)
    assert result.session_id == "sess-1"
    assert result.ces == compute_ces(_parse_signal(_VALID_PAYLOAD))
    assert result.ces == 0.5
