"""Unit tests for the pure aggregation logic of scripts/ws_load_test.py
(Dev 4 — Sprint 4 ws_load_test).

Only ``summarize()`` is tested here — it is socket-free and deterministic. The end-to-end harness
(``_run_session`` / ``_reference_server``) is validated by running the script's ``--self-test`` mode
live (see docs/sprint4-ws-load-test.md); it is intentionally NOT exercised in the unit suite to
avoid binding real sockets in CI.

The script lives under ``scripts/`` (not a package), so it is loaded by file path via importlib.
``@pytest.mark.unit``.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

# __file__ = <root>/apps/api/tests/test_ws_load_test.py → parents[3] is the repo root.
_SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "ws_load_test.py"
_spec = importlib.util.spec_from_file_location("ws_load_test", _SCRIPT)
assert _spec and _spec.loader
ws_load_test = importlib.util.module_from_spec(_spec)
# Register before exec so dataclass machinery can resolve the module by name.
sys.modules["ws_load_test"] = ws_load_test
_spec.loader.exec_module(ws_load_test)

SessionResult = ws_load_test.SessionResult
summarize = ws_load_test.summarize


@pytest.mark.unit
def test_summarize_all_connected_zero_drops() -> None:
    results = [
        SessionResult("a", connected=True, signals_sent=3, acks=3, latencies=[0.01, 0.02, 0.03]),
        SessionResult("b", connected=True, signals_sent=3, acks=3, latencies=[0.01, 0.01, 0.01]),
        SessionResult("c", connected=True, signals_sent=3, acks=3, latencies=[0.02, 0.02, 0.02]),
    ]
    s = summarize(results, sessions_requested=3)

    assert s["sessions_requested"] == 3
    assert s["sessions_connected"] == 3
    assert s["sessions_dropped"] == 0
    assert s["sessions_errored"] == 0
    assert s["signals_sent"] == 9
    assert s["acks_received"] == 9
    assert s["acks_missed"] == 0
    assert s["latency_ms_p50"] is not None
    assert s["latency_ms_p95"] is not None
    assert s["latency_ms_max"] is not None


@pytest.mark.unit
def test_summarize_counts_drops() -> None:
    """drops = sessions_requested - connected
    (covers never-connected AND errored-before-connect).
    """
    results = [
        SessionResult("a", connected=True, signals_sent=1, acks=1, latencies=[0.01]),
        SessionResult("b", connected=False, error="ConnectionRefusedError()"),
        SessionResult("c", connected=False, error="TimeoutError()"),
    ]
    s = summarize(results, sessions_requested=5)  # 2 connected of 5 requested

    assert s["sessions_connected"] == 1
    assert s["sessions_dropped"] == 4  # 5 - 1
    assert s["sessions_errored"] == 2


@pytest.mark.unit
def test_summarize_latency_percentiles() -> None:
    """Known latency set → exact ms percentiles. Values: 10,20,30,40,50 ms (0.01..0.05 s)."""
    results = [
        SessionResult(
            "a",
            connected=True,
            signals_sent=5,
            acks=5,
            latencies=[0.01, 0.02, 0.03, 0.04, 0.05],
        )
    ]
    s = summarize(results, sessions_requested=1)

    # p50 → index round(0.5*4)=2 → 30ms; p95 → round(0.95*4)=4 → 50ms; max → 50ms
    assert s["latency_ms_p50"] == 30.0
    assert s["latency_ms_p95"] == 50.0
    assert s["latency_ms_max"] == 50.0


@pytest.mark.unit
def test_summarize_counts_missed_acks() -> None:
    results = [
        SessionResult("a", connected=True, signals_sent=3, acks=1, missed_acks=2, latencies=[0.01]),
        SessionResult(
            "b", connected=True, signals_sent=3, acks=3, missed_acks=0, latencies=[0.01, 0.01, 0.01]
        ),
    ]
    s = summarize(results, sessions_requested=2)

    assert s["acks_received"] == 4
    assert s["acks_missed"] == 2
    assert s["sessions_dropped"] == 0


@pytest.mark.unit
def test_summarize_no_latencies_returns_none() -> None:
    """No acks anywhere → percentile fields are None, not a crash."""
    results = [SessionResult("a", connected=True, signals_sent=2, acks=0, missed_acks=2)]
    s = summarize(results, sessions_requested=1)

    assert s["latency_ms_p50"] is None
    assert s["latency_ms_p95"] is None
    assert s["latency_ms_max"] is None


@pytest.mark.unit
def test_summarize_mid_run_death_counts_as_drop() -> None:
    """A session that connects then dies mid-run (connected=True + error) is a DROP, not a clean
    session — guards against the false-green where only never-connected sessions count."""
    results = [
        SessionResult(
            "a", connected=True, signals_sent=60, acks=60, latencies=[0.01] * 60
        ),  # healthy
        SessionResult(
            "b",
            connected=True,
            signals_sent=30,
            acks=30,
            latencies=[0.01] * 30,
            error="ConnectionClosedError()",
        ),  # connected, then killed mid-run
    ]
    s = summarize(results, sessions_requested=2)

    assert s["sessions_connected"] == 2  # both handshook
    assert s["sessions_completed"] == 1  # only 'a' finished cleanly
    assert s["sessions_dropped"] == 1  # 'b' died mid-run → counted as a drop
    assert s["sessions_errored"] == 1
    assert s["passed"] is False  # a drop fails the AC


@pytest.mark.unit
def test_summarize_passed_flag() -> None:
    """passed is True only when 0 drops AND 0 errors AND 0 missed acks."""
    clean = [SessionResult("a", connected=True, signals_sent=2, acks=2, latencies=[0.01, 0.02])]
    assert summarize(clean, sessions_requested=1)["passed"] is True

    missed = [
        SessionResult("a", connected=True, signals_sent=2, acks=1, missed_acks=1, latencies=[0.01])
    ]
    assert summarize(missed, sessions_requested=1)["passed"] is False  # missed ack fails

    never = [SessionResult("a", connected=False, error="ConnectionRefusedError()")]
    assert summarize(never, sessions_requested=1)["passed"] is False  # drop fails
