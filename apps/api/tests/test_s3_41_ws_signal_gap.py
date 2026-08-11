"""Tests for Story 3-41 — Configurable WebSocket signal-gap timeout (D77).

ACs tested:
  AC1 — settings.ws_signal_gap_seconds field with correct default (60.0)
  AC2 — websocket_endpoint passes settings value to asyncio.wait_for
  AC3 — TimeoutError triggers finalize(signal_gap=True) + close(1001)
  AC4 — WS_SIGNAL_GAP_SECONDS env var overrides default
  AC5 — ws_signal_gap_seconds <= 0 raises ValidationError at Settings() construction
  AC6 — guard test: ws_signal_gap_seconds in source (not a hardcoded literal)

All tests are @pytest.mark.unit — no real WebSocket, no real Redis.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_settings(gap_seconds: float = 60.0) -> MagicMock:
    """Return a Settings mock with ws_signal_gap_seconds set."""
    s = MagicMock()
    s.ws_signal_gap_seconds = gap_seconds
    return s


# ── AC1 — Config field exists with correct default ────────────────────────────

@pytest.mark.unit
def test_ws_signal_gap_seconds_default_is_60():
    """settings.ws_signal_gap_seconds must default to 60.0."""
    from app.config import Settings

    s = Settings()
    assert s.ws_signal_gap_seconds == pytest.approx(60.0)


@pytest.mark.unit
def test_ws_signal_gap_seconds_is_float():
    """settings.ws_signal_gap_seconds must be a float."""
    from app.config import Settings

    s = Settings()
    assert isinstance(s.ws_signal_gap_seconds, float)


# ── AC4 — Env var configures the field ───────────────────────────────────────

@pytest.mark.unit
def test_ws_signal_gap_seconds_env_var(monkeypatch):
    """WS_SIGNAL_GAP_SECONDS=30 → settings.ws_signal_gap_seconds == 30.0."""
    monkeypatch.setenv("WS_SIGNAL_GAP_SECONDS", "30")

    from app.config import Settings

    s = Settings()
    assert s.ws_signal_gap_seconds == pytest.approx(30.0)


@pytest.mark.unit
def test_ws_signal_gap_seconds_env_var_float(monkeypatch):
    """WS_SIGNAL_GAP_SECONDS=45.5 → settings.ws_signal_gap_seconds == 45.5."""
    monkeypatch.setenv("WS_SIGNAL_GAP_SECONDS", "45.5")

    from app.config import Settings

    s = Settings()
    assert s.ws_signal_gap_seconds == pytest.approx(45.5)


# ── AC5 — Zero and negative values rejected at boot ──────────────────────────

@pytest.mark.unit
def test_ws_signal_gap_zero_raises_validation_error(monkeypatch):
    """ws_signal_gap_seconds=0 must raise ValidationError (server must not start)."""
    from pydantic import ValidationError

    monkeypatch.setenv("WS_SIGNAL_GAP_SECONDS", "0")

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_ws_signal_gap_negative_raises_validation_error(monkeypatch):
    """ws_signal_gap_seconds=-1 must raise ValidationError."""
    from pydantic import ValidationError

    monkeypatch.setenv("WS_SIGNAL_GAP_SECONDS", "-1")

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.unit
def test_ws_signal_gap_very_small_positive_accepted(monkeypatch):
    """ws_signal_gap_seconds=0.1 is accepted (strictly positive)."""
    monkeypatch.setenv("WS_SIGNAL_GAP_SECONDS", "0.1")

    from app.config import Settings

    s = Settings()
    assert s.ws_signal_gap_seconds == pytest.approx(0.1)


# ── AC6 — Source-level guard (CI D77 guard) ───────────────────────────────────

@pytest.mark.unit
def test_ws_signal_gap_timeout_configurable():
    """Guard test: websocket_endpoint source must reference ws_signal_gap_seconds via wait_for.

    This is the CI guard for D77. Fails if a future dev replaces the configurable
    timeout with a hardcoded literal.
    """
    import inspect

    from app.core import websocket as ws_module

    source = inspect.getsource(ws_module.websocket_endpoint)
    assert "wait_for" in source, "websocket_endpoint must use asyncio.wait_for — D77 guard"
    assert "ws_signal_gap_seconds" in source, (
        "websocket_endpoint must reference ws_signal_gap_seconds "
        "(not a hardcoded literal) — D77 guard"
    )


# ── AC2 — websocket_endpoint passes config value to asyncio.wait_for ─────────

@pytest.mark.unit
async def test_ws_endpoint_passes_gap_setting_to_wait_for():
    """asyncio.wait_for is called with the value from get_settings(), not 10.0 or any literal."""
    from app.core.websocket import websocket_endpoint

    mock_ws = AsyncMock()
    mock_ws.client_state = MagicMock()

    captured_timeout = []

    async def fake_wait_for(coro, timeout):
        captured_timeout.append(timeout)
        # Raise WebSocketDisconnect so the endpoint exits cleanly (not via generic except)
        from fastapi import WebSocketDisconnect
        raise WebSocketDisconnect(code=1000)

    with (
        patch("app.core.websocket._SESSION_ID_RE") as mock_re,
        patch("app.core.websocket.manager") as mock_mgr,
        patch("app.core.websocket.asyncio") as mock_asyncio,
        patch("app.core.websocket.get_settings", return_value=_mock_settings(60.0)),
    ):
        mock_re.match.return_value = True
        mock_mgr.connect = AsyncMock()
        mock_mgr.disconnect = MagicMock()
        mock_asyncio.wait_for = fake_wait_for
        mock_asyncio.TimeoutError = asyncio.TimeoutError

        await websocket_endpoint(mock_ws, "00000000-0000-0000-0000-000000000001")

    assert len(captured_timeout) >= 1, "asyncio.wait_for was never called in websocket_endpoint"
    for t in captured_timeout:
        assert t == pytest.approx(60.0), (
            f"wait_for called with timeout={t} instead of settings.ws_signal_gap_seconds=60.0"
        )


# ── AC3 — TimeoutError triggers finalize(signal_gap=True) + close(1001) ──────

@pytest.mark.unit
async def test_timeout_triggers_signal_gap_finalization():
    """asyncio.TimeoutError from wait_for → finalize with signal_gap=True."""
    from app.core.websocket import websocket_endpoint

    mock_ws = AsyncMock()
    mock_ws.client_state = MagicMock()

    finalize_calls = []

    async def fake_finalize(*args, **kwargs):
        finalize_calls.append(kwargs)

    with (
        patch("app.core.websocket._SESSION_ID_RE") as mock_re,
        patch("app.core.websocket.manager") as mock_mgr,
        patch("app.core.websocket.asyncio") as mock_asyncio,
        patch("app.core.websocket.get_settings", return_value=_mock_settings(60.0)),
        patch("app.core.websocket._finalize_session_best_effort", side_effect=fake_finalize),
    ):
        mock_re.match.return_value = True
        mock_mgr.connect = AsyncMock()
        mock_mgr.disconnect = MagicMock()
        mock_asyncio.wait_for = AsyncMock(side_effect=TimeoutError())
        mock_asyncio.TimeoutError = asyncio.TimeoutError

        await websocket_endpoint(mock_ws, "00000000-0000-0000-0000-000000000001")

    assert len(finalize_calls) >= 1, "finalize_session_best_effort not called on TimeoutError"
    flags = finalize_calls[0].get("flags", {})
    assert flags.get("signal_gap") is True, (
        f"Expected flags={{'signal_gap': True}}, got flags={flags}"
    )


@pytest.mark.unit
async def test_timeout_closes_ws_1001():
    """asyncio.TimeoutError → websocket.close(1001)."""
    from app.core.websocket import websocket_endpoint

    mock_ws = AsyncMock()
    mock_ws.client_state = MagicMock()
    mock_ws.close = AsyncMock()

    with (
        patch("app.core.websocket._SESSION_ID_RE") as mock_re,
        patch("app.core.websocket.manager") as mock_mgr,
        patch("app.core.websocket.asyncio") as mock_asyncio,
        patch("app.core.websocket.get_settings", return_value=_mock_settings(60.0)),
        patch("app.core.websocket._finalize_session_best_effort", new_callable=AsyncMock),
    ):
        mock_re.match.return_value = True
        mock_mgr.connect = AsyncMock()
        mock_mgr.disconnect = MagicMock()
        mock_asyncio.wait_for = AsyncMock(side_effect=TimeoutError())
        mock_asyncio.TimeoutError = asyncio.TimeoutError

        await websocket_endpoint(mock_ws, "00000000-0000-0000-0000-000000000001")

    mock_ws.close.assert_called_once_with(1001)


@pytest.mark.unit
async def test_timeout_disconnects_manager():
    """asyncio.TimeoutError → manager.disconnect called."""
    from app.core.websocket import websocket_endpoint

    mock_ws = AsyncMock()
    mock_ws.client_state = MagicMock()

    with (
        patch("app.core.websocket._SESSION_ID_RE") as mock_re,
        patch("app.core.websocket.manager") as mock_mgr,
        patch("app.core.websocket.asyncio") as mock_asyncio,
        patch("app.core.websocket.get_settings", return_value=_mock_settings(60.0)),
        patch("app.core.websocket._finalize_session_best_effort", new_callable=AsyncMock),
    ):
        mock_re.match.return_value = True
        mock_mgr.connect = AsyncMock()
        mock_mgr.disconnect = MagicMock()
        mock_asyncio.wait_for = AsyncMock(side_effect=TimeoutError())
        mock_asyncio.TimeoutError = asyncio.TimeoutError

        await websocket_endpoint(mock_ws, "00000000-0000-0000-0000-000000000001")

    mock_mgr.disconnect.assert_called_once()


@pytest.mark.unit
async def test_normal_messages_not_affected_by_gap_setting():
    """Normal messages before timeout are processed (gap setting doesn't break happy path)."""
    from app.core.websocket import websocket_endpoint

    mock_ws = AsyncMock()
    mock_ws.client_state = MagicMock()
    mock_ws.send_json = AsyncMock()

    call_count = [0]

    async def fake_wait_for(coro, timeout):
        call_count[0] += 1
        if call_count[0] == 1:
            return '{"type": "ping"}'
        else:
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)

    with (
        patch("app.core.websocket._SESSION_ID_RE") as mock_re,
        patch("app.core.websocket.manager") as mock_mgr,
        patch("app.core.websocket.asyncio") as mock_asyncio,
        patch("app.core.websocket.get_settings", return_value=_mock_settings(60.0)),
    ):
        mock_re.match.return_value = True
        mock_mgr.connect = AsyncMock()
        mock_mgr.disconnect = MagicMock()
        mock_asyncio.wait_for = fake_wait_for
        mock_asyncio.TimeoutError = asyncio.TimeoutError

        await websocket_endpoint(mock_ws, "00000000-0000-0000-0000-000000000001")

    mock_ws.send_json.assert_called_with({"type": "pong"})
