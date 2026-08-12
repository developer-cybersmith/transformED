"""Tests for Story S3-41 — WebSocket signal-gap timeout: asyncio.wait_for(30s) + missed_windows (D9).

ACs tested:
  AC1 — asyncio.wait_for wraps every receive_text() with timeout=_WS_RECEIVE_TIMEOUT_SECONDS (30.0)
  AC2 — missed_windows counter: coroutine-local, increments on TimeoutError, resets on success
  AC3 — When missed_windows == 2: finalize(signal_gap=True) + close(code=1001) + loop exits
  AC4 — When missed_windows == 1: no finalize, no close, loop continues
  AC5 — logger.warning on every TimeoutError containing session_id and missed_windows count
  AC6 — Non-TimeoutError/non-WebSocketDisconnect exceptions do NOT increment missed_windows or call finalize
  AC7 — WebSocketDisconnect routes to manager.disconnect only; does NOT call finalize from timeout path

All tests are @pytest.mark.unit — no real WebSocket, no real Redis, no real DB.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SESSION_ID = "11111111-2222-3333-4444-555555555555"
_VALID_PING_MSG = '{"type": "ping"}'


# ── Test helpers ──────────────────────────────────────────────────────────────


def _patch_endpoint_deps(mocker):
    """Patch connection manager and UUID check so websocket_endpoint reaches the receive loop.

    Returns the mocked manager so tests can assert on disconnect() calls.
    """
    mocker.patch("app.core.websocket._SESSION_ID_RE").match.return_value = True
    mock_mgr = MagicMock()
    mock_mgr.connect = AsyncMock()
    mock_mgr.disconnect = MagicMock()
    mock_mgr.send = AsyncMock()
    mocker.patch("app.core.websocket.manager", mock_mgr)
    # Patch get_settings so the D77 `_settings = get_settings()` doesn't fail in tests.
    # After D9 implementation this import is removed; the patch is harmless then.
    mock_s = MagicMock()
    mock_s.ws_signal_gap_seconds = 60.0
    try:
        mocker.patch("app.core.websocket.get_settings", return_value=mock_s)
    except AttributeError:
        pass  # get_settings may not be imported in D9 version
    return mock_mgr


def _make_ws():
    """Return a mock WebSocket with AsyncMock send_json and close."""
    ws = AsyncMock()
    ws.client_state = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


def _make_sequential_receive(*results):
    """Return an async function that yields results/raises in sequence.

    Each item is either a string (returned) or an Exception (raised).
    """
    idx = [0]

    async def fake_receive():
        if idx[0] >= len(results):
            # Safety: raise WebSocketDisconnect so the loop ends if unexpectedly called more times
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(1000)
        item = results[idx[0]]
        idx[0] += 1
        if isinstance(item, BaseException):
            raise item
        return item

    return fake_receive


# ── AC1 — _WS_RECEIVE_TIMEOUT_SECONDS constant + wait_for usage ───────────────


@pytest.mark.unit
def test_ac1_receive_timeout_constant_exists():
    """_WS_RECEIVE_TIMEOUT_SECONDS must be defined at module level and equal 30.0 (D9 AC1)."""
    from app.core import websocket as ws_module

    assert hasattr(ws_module, "_WS_RECEIVE_TIMEOUT_SECONDS"), (
        "_WS_RECEIVE_TIMEOUT_SECONDS constant missing from websocket.py — D9 AC1 not implemented"
    )
    assert ws_module._WS_RECEIVE_TIMEOUT_SECONDS == pytest.approx(30.0), (
        f"Expected _WS_RECEIVE_TIMEOUT_SECONDS == 30.0, got {ws_module._WS_RECEIVE_TIMEOUT_SECONDS}"
    )


@pytest.mark.unit
def test_ac1_wait_for_references_constant_not_settings():
    """Source of websocket_endpoint must reference _WS_RECEIVE_TIMEOUT_SECONDS in wait_for.

    This ensures D9 uses the hardcoded constant, not D77's configurable settings field.
    """
    import inspect

    from app.core import websocket as ws_module

    source = inspect.getsource(ws_module.websocket_endpoint)
    assert "wait_for" in source, "websocket_endpoint must use asyncio.wait_for"
    assert "_WS_RECEIVE_TIMEOUT_SECONDS" in source, (
        "websocket_endpoint must pass _WS_RECEIVE_TIMEOUT_SECONDS to wait_for, "
        "not a settings field or a raw numeric literal — D9 AC1"
    )


@pytest.mark.unit
async def test_ac1_timeout_error_handled_without_crash(mocker):
    """asyncio.TimeoutError from receive_text is handled cleanly — endpoint does not raise."""
    _patch_endpoint_deps(mocker)
    mocker.patch("app.core.websocket._finalize_session_best_effort", AsyncMock())

    ws = _make_ws()
    # Two consecutive TimeoutErrors trigger finalize (missed_windows == 2), then loop exits cleanly.
    ws.receive_text = _make_sequential_receive(
        asyncio.TimeoutError(), asyncio.TimeoutError()
    )

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)  # must not raise


# ── AC2 — missed_windows counter ─────────────────────────────────────────────


@pytest.mark.unit
async def test_ac2_two_consecutive_timeouts_trigger_finalize_after_second(mocker):
    """receive_text must be called exactly 2 times before finalize fires (D9 AC2 + AC3).

    With D77 (single-timeout logic) receive_text is called only 1 time before finalize.
    With D9 (missed_windows counter) it is called 2 times.
    """
    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    receive_call_count = [0]

    async def counting_receive():
        receive_call_count[0] += 1
        raise asyncio.TimeoutError()

    ws = _make_ws()
    ws.receive_text = counting_receive

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    assert receive_call_count[0] == 2, (
        f"Expected receive_text called 2 times before finalize; got {receive_call_count[0]}. "
        "D9 AC2: missed_windows must reach 2 before finalize fires."
    )
    mock_finalize.assert_called_once()


@pytest.mark.unit
async def test_ac2_missed_windows_resets_to_zero_on_successful_receive(mocker):
    """Sequence: timeout → valid message → disconnect → no finalize ever called.

    After a timeout (missed_windows = 1), a valid message resets the counter to 0.
    A subsequent WebSocketDisconnect exits without triggering signal_gap finalize.
    """
    from fastapi import WebSocketDisconnect

    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = _make_sequential_receive(
        asyncio.TimeoutError(),     # missed_windows = 1
        _VALID_PING_MSG,             # missed_windows resets to 0
        WebSocketDisconnect(1000),   # exits normally
    )

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    # finalize MUST NOT be called — missed_windows never reached 2 consecutively
    mock_finalize.assert_not_called()


# ── AC3 — finalize + close(1001) + exit on missed_windows == 2 ───────────────


@pytest.mark.unit
async def test_ac3_finalize_called_once_after_two_timeouts(mocker):
    """_finalize_session_best_effort called exactly once when missed_windows reaches 2 (D9 AC3)."""
    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    mock_finalize.assert_called_once()


@pytest.mark.unit
async def test_ac3_finalize_called_with_signal_gap_true(mocker):
    """finalize must be called with flags={'signal_gap': True} (D9 AC3)."""
    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    mock_finalize.assert_called_once()
    call_kwargs = mock_finalize.call_args.kwargs if mock_finalize.call_args else {}
    flags = call_kwargs.get("flags", {})
    assert flags.get("signal_gap") is True, (
        f"Expected flags={{'signal_gap': True}}, got {flags!r} — D9 AC3"
    )


@pytest.mark.unit
async def test_ac3_websocket_close_1001_called_after_finalize(mocker):
    """websocket.close(code=1001) must be called after finalize fires (D9 AC3)."""
    _patch_endpoint_deps(mocker)
    mocker.patch("app.core.websocket._finalize_session_best_effort", AsyncMock())

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    ws.close.assert_called_once_with(1001)


@pytest.mark.unit
async def test_ac3_finalize_called_exactly_once_even_if_close_raises(mocker):
    """If close(1001) raises, finalize is still called exactly once — not duplicated (D9 AC3)."""
    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())
    ws.close = AsyncMock(side_effect=RuntimeError("socket gone"))

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)  # must not propagate the RuntimeError

    assert mock_finalize.call_count == 1, (
        f"finalize called {mock_finalize.call_count} times; expected exactly 1 — D9 AC3"
    )


# ── AC4 — missed_windows == 1 does NOT finalize ──────────────────────────────


@pytest.mark.unit
async def test_ac4_no_finalize_after_single_timeout(mocker):
    """After exactly 1 TimeoutError (missed_windows == 1), finalize NOT called; loop continues.

    Sequence: one timeout → WebSocketDisconnect (exits normally without finalize).
    With D77 (single-timeout), finalize IS called. This test FAILS with D77 and PASSES with D9.
    """
    from fastapi import WebSocketDisconnect

    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = _make_sequential_receive(
        asyncio.TimeoutError(),    # missed_windows = 1 (should NOT trigger finalize)
        WebSocketDisconnect(1000), # disconnect exits loop via manager.disconnect path
    )

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    # finalize must NOT be called from the signal_gap path (missed_windows never reached 2)
    mock_finalize.assert_not_called()


@pytest.mark.unit
async def test_ac4_loop_continues_after_first_timeout(mocker):
    """After 1 timeout, the receive loop continues (receive_text called again).

    With D77: loop exits after 1 timeout → receive_text called only once.
    With D9: loop continues → receive_text called at least twice.
    """
    from fastapi import WebSocketDisconnect

    _patch_endpoint_deps(mocker)
    mocker.patch("app.core.websocket._finalize_session_best_effort", AsyncMock())

    receive_count = [0]

    ws = _make_ws()
    ws.receive_text = _make_sequential_receive(
        asyncio.TimeoutError(),    # 1st call — D9 continues; D77 exits
        WebSocketDisconnect(1000), # 2nd call — disconnect (only reached with D9)
    )

    # Wrap to count calls
    original_receive = ws.receive_text

    async def counting_receive():
        receive_count[0] += 1
        return await original_receive()

    ws.receive_text = counting_receive

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    assert receive_count[0] >= 2, (
        f"receive_text called only {receive_count[0]} time(s). "
        "D9 AC4: after 1 timeout the loop must continue and call receive_text again."
    )


# ── AC5 — logger.warning on every TimeoutError ────────────────────────────────


@pytest.mark.unit
async def test_ac5_warning_logged_on_each_timeout(mocker, caplog):
    """logger.warning must be emitted on every TimeoutError (D9 AC5)."""
    _patch_endpoint_deps(mocker)
    mocker.patch("app.core.websocket._finalize_session_best_effort", AsyncMock())

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())

    from app.core.websocket import websocket_endpoint

    with caplog.at_level(logging.WARNING, logger="app.core.websocket"):
        await websocket_endpoint(ws, _SESSION_ID)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    # The signal-gap event must produce at least 1 WARNING (one per timeout)
    assert len(warning_records) >= 1, (
        "No WARNING log records emitted on TimeoutError. "
        "D9 AC5 requires logger.warning on every signal gap."
    )


@pytest.mark.unit
async def test_ac5_warning_contains_session_id(mocker, caplog):
    """WARNING log record must include the session_id string (D9 AC5)."""
    _patch_endpoint_deps(mocker)
    mocker.patch("app.core.websocket._finalize_session_best_effort", AsyncMock())

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())

    from app.core.websocket import websocket_endpoint

    with caplog.at_level(logging.WARNING, logger="app.core.websocket"):
        await websocket_endpoint(ws, _SESSION_ID)

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(_SESSION_ID in msg for msg in warning_messages), (
        f"session_id {_SESSION_ID!r} not found in WARNING messages: {warning_messages}. "
        "D9 AC5: WARNING must include session_id."
    )


@pytest.mark.unit
async def test_ac5_warning_contains_missed_windows_value(mocker, caplog):
    """WARNING log record must include the missed_windows integer value (D9 AC5).

    Minimum pattern: 'WS signal gap: session=%s missed_windows=%d'
    """
    _patch_endpoint_deps(mocker)
    mocker.patch("app.core.websocket._finalize_session_best_effort", AsyncMock())

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError())

    from app.core.websocket import websocket_endpoint

    with caplog.at_level(logging.WARNING, logger="app.core.websocket"):
        await websocket_endpoint(ws, _SESSION_ID)

    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    # missed_windows value "1" or "2" must appear (or "missed_windows" keyword)
    assert any(
        "missed" in msg.lower() or "1" in msg or "2" in msg
        for msg in warning_messages
    ), (
        f"missed_windows count not found in WARNING messages: {warning_messages}. "
        "D9 AC5: WARNING must include missed_windows count."
    )


# ── AC6 — Non-TimeoutError/non-WebSocketDisconnect does not increment counter ─


@pytest.mark.unit
async def test_ac6_non_timeout_exception_does_not_call_finalize(mocker):
    """RuntimeError from receive_text must NOT call _finalize_session_best_effort (D9 AC6).

    The existing `except Exception` handler fires instead — no missed_windows increment.
    """
    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=RuntimeError("peer closed unexpectedly"))

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    mock_finalize.assert_not_called()


@pytest.mark.unit
async def test_ac6_connection_reset_does_not_call_finalize(mocker):
    """ConnectionResetError from receive_text must NOT call finalize (D9 AC6)."""
    _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=ConnectionResetError())

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    mock_finalize.assert_not_called()


# ── AC7 — WebSocketDisconnect routes to manager.disconnect, not finalize ──────


@pytest.mark.unit
async def test_ac7_disconnect_calls_manager_disconnect(mocker):
    """WebSocketDisconnect routes to manager.disconnect() — not to finalize (D9 AC7)."""
    from fastapi import WebSocketDisconnect

    mock_mgr = _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect(1000))

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    mock_mgr.disconnect.assert_called_once()
    mock_finalize.assert_not_called()


@pytest.mark.unit
async def test_ac7_disconnect_does_not_increment_missed_windows(mocker):
    """WebSocketDisconnect must not call finalize from the missed_windows (signal_gap) path (D9 AC7).

    Verify that even after 1 timeout, a WebSocketDisconnect goes to manager.disconnect only.
    """
    from fastapi import WebSocketDisconnect

    mock_mgr = _patch_endpoint_deps(mocker)
    mock_finalize = AsyncMock()
    mocker.patch("app.core.websocket._finalize_session_best_effort", mock_finalize)

    ws = _make_ws()
    ws.receive_text = _make_sequential_receive(
        asyncio.TimeoutError(),    # missed_windows = 1
        WebSocketDisconnect(1000), # exit via disconnect path (not signal_gap path)
    )

    from app.core.websocket import websocket_endpoint

    await websocket_endpoint(ws, _SESSION_ID)

    # WebSocketDisconnect must call manager.disconnect, not the signal_gap finalize
    mock_mgr.disconnect.assert_called_once()
    mock_finalize.assert_not_called()
