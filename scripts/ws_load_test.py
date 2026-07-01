#!/usr/bin/env python3
"""WebSocket load-test harness for the Dev 4 endpoint (Sprint 4 ws_load_test).

Simulates N concurrent WebSocket sessions. Each session: connect → send
``session_start`` → send M ``attention_signal``s spaced over a duration,
awaiting each ``attention_ack`` → disconnect. Aggregates connection drops,
signals sent, acks received/missed, and ack-latency percentiles.

Usage:
    # Against a running server:
    python scripts/ws_load_test.py --host ws://localhost:8000 --sessions 50 --signals 60 --duration 300

    # Self-validation (spins an in-process reference server; no external server needed):
    python scripts/ws_load_test.py --self-test --sessions 50 --signals 3 --duration 1.5

Exit code is 0 iff there were zero dropped connections, so this is CI/gateable.

Dependency note: requires `websockets` (pip install websockets). This package is
NOT listed in apps/api/pyproject.toml — install it manually in your dev
environment before running this script (same as scripts/mock_ws_client.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field

import websockets


# ── Per-session result ──────────────────────────────────────────────────────────


@dataclass
class SessionResult:
    """Outcome of one simulated session."""

    session_id: str
    connected: bool = False
    signals_sent: int = 0
    acks: int = 0
    missed_acks: int = 0
    latencies: list[float] = field(default_factory=list)  # ack RTT in seconds
    error: str | None = None


def _signal(session_id: str) -> str:
    """A nested attention_signal envelope (shape per packages/shared/types/ws.ts)."""
    return json.dumps(
        {
            "type": "attention_signal",
            "payload": {
                "session_id": session_id,
                "quiz_accuracy": 0.8,
                "teachback_score": None,
                "behavioral_score": 0.9,
                "head_pose_score": 0.75,
                "blink_rate": 0.3,
            },
        }
    )


# ── One simulated session ────────────────────────────────────────────────────────


async def _run_session(
    uri: str,
    session_id: str,
    signals: int,
    duration: float,
    connect_timeout: float,
    ack_timeout: float,
) -> SessionResult:
    """Connect, send session_start, send `signals` attention_signals spaced over `duration`
    seconds (awaiting each attention_ack), then disconnect. Any failure → res.error."""
    res = SessionResult(session_id)
    interval = duration / signals if signals else 0.0
    loop = asyncio.get_event_loop()
    try:
        async with websockets.connect(uri, open_timeout=connect_timeout) as ws:
            res.connected = True
            await ws.send(json.dumps({"type": "session_start"}))

            for i in range(signals):
                t0 = loop.time()
                await ws.send(_signal(session_id))
                res.signals_sent += 1

                # Read frames until OUR attention_ack arrives (skip any other server frames),
                # bounded by ack_timeout.
                try:
                    deadline = loop.time() + ack_timeout
                    while True:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise asyncio.TimeoutError
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                        if json.loads(raw).get("type") == "attention_ack":
                            res.acks += 1
                            res.latencies.append(loop.time() - t0)
                            break
                except asyncio.TimeoutError:
                    res.missed_acks += 1

                if i < signals - 1:
                    await asyncio.sleep(interval)
    except Exception as exc:  # noqa: BLE001 — connection refused / handshake / mid-run drop
        res.error = repr(exc)
    return res


# ── Aggregation (pure — unit-tested without sockets) ─────────────────────────────


def summarize(results: list[SessionResult], sessions_requested: int) -> dict:
    """Aggregate SessionResults into a summary dict. Pure: no I/O, deterministic.

    A "drop" is any requested session that did NOT cleanly complete — never connected (handshake
    failed) OR connected and then errored mid-run (e.g. the server killed the socket at signal 30).
    Counting only never-connected here would be a false-green: a connect-then-die session keeps
    ``connected=True`` but is NOT a healthy session.
    """
    connected = [r for r in results if r.connected]  # handshake succeeded (informational)
    completed = [r for r in results if r.connected and not r.error]  # ran to a clean disconnect
    errored = [r for r in results if r.error]  # never-connected OR died mid-run
    dropped = sessions_requested - len(completed)
    acks_missed = sum(r.missed_acks for r in results)
    lat = [x for r in results for x in r.latencies]

    def pct(p: float) -> float | None:
        if not lat:
            return None
        s = sorted(lat)
        k = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
        return round(s[k] * 1000, 2)  # ms

    return {
        "sessions_requested": sessions_requested,
        "sessions_connected": len(connected),
        "sessions_completed": len(completed),
        "sessions_dropped": dropped,
        "sessions_errored": len(errored),
        "signals_sent": sum(r.signals_sent for r in results),
        "acks_received": sum(r.acks for r in results),
        "acks_missed": acks_missed,
        "latency_ms_p50": pct(50),
        "latency_ms_p95": pct(95),
        "latency_ms_max": round(max(lat) * 1000, 2) if lat else None,
        # The AC gate: a clean run has zero drops, zero errors, and every signal acked.
        "passed": dropped == 0 and len(errored) == 0 and acks_missed == 0,
    }


# ── Self-test reference server ───────────────────────────────────────────────────


async def _reference_server(ready: asyncio.Event, port_box: list[int]):
    """In-process reference WS server for --self-test: replies attention_ack to each
    attention_signal and pong to ping; ignores session_start (matches the real server)."""

    async def handler(ws):  # websockets 15.x: single-arg handler
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "attention_signal":
                sid = (msg.get("payload") or {}).get("session_id", "")
                await ws.send(
                    json.dumps({"type": "attention_ack", "payload": {"session_id": sid, "ces": 50.0}})
                )
            elif mtype == "ping":
                await ws.send(json.dumps({"type": "pong"}))
            # session_start: no reply (mirrors the production endpoint)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port_box.append(server.sockets[0].getsockname()[1])
        ready.set()
        await asyncio.Future()  # run until cancelled


# ── Orchestration ────────────────────────────────────────────────────────────────


def _print_summary(summary: dict) -> None:
    # ASCII only — box-drawing chars crash on Windows cp1252 consoles.
    print(json.dumps(summary, indent=2))
    print("\n== WebSocket load test ==============================")
    print(f"  sessions requested : {summary['sessions_requested']}")
    print(f"  sessions connected : {summary['sessions_connected']}")
    print(f"  sessions completed : {summary['sessions_completed']}")
    print(f"  sessions DROPPED   : {summary['sessions_dropped']}  (never-connected OR died mid-run)")
    print(f"  sessions errored   : {summary['sessions_errored']}")
    print(f"  signals sent       : {summary['signals_sent']}")
    print(f"  acks received      : {summary['acks_received']}")
    print(f"  acks missed        : {summary['acks_missed']}")
    print(f"  ack latency p50/p95/max (ms): "
          f"{summary['latency_ms_p50']} / {summary['latency_ms_p95']} / {summary['latency_ms_max']}")
    print(f"  RESULT             : {'PASS' if summary['passed'] else 'FAIL'} "
          f"(0 drops + 0 errors + 0 missed acks)")
    print("=====================================================")


async def _drive(uri: str, args: argparse.Namespace) -> dict:
    tasks = [
        _run_session(
            uri,
            str(uuid.uuid4()),
            args.signals,
            args.duration,
            args.connect_timeout,
            args.ack_timeout,
        )
        for _ in range(args.sessions)
    ]
    results = await asyncio.gather(*tasks)
    return summarize(results, args.sessions)


async def _main_async(args: argparse.Namespace) -> int:
    if args.self_test:
        ready: asyncio.Event = asyncio.Event()
        port_box: list[int] = []
        server_task = asyncio.create_task(_reference_server(ready, port_box))
        await ready.wait()
        uri_base = f"ws://127.0.0.1:{port_box[0]}"
        print(f"[self-test] reference server on {uri_base}")
        try:
            summary = await _drive(uri_base + "/ws/{sid}".format(sid="load"), args)
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
    else:
        summary = await _drive(f"{args.host}/ws/load", args)

    _print_summary(summary)
    return 0 if summary["passed"] else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WebSocket load-test harness (Dev 4 / Sprint 4)")
    p.add_argument("--host", default="ws://localhost:8000", help="WS host base (default ws://localhost:8000)")
    p.add_argument("--sessions", type=int, default=50, help="concurrent sessions (default 50)")
    p.add_argument("--signals", type=int, default=60, help="attention_signals per session (default 60)")
    p.add_argument("--duration", type=float, default=300.0, help="seconds to spread signals over (default 300)")
    p.add_argument("--self-test", action="store_true", help="spin an in-process reference server")
    p.add_argument("--connect-timeout", type=float, default=10.0, help="connect timeout s (default 10)")
    p.add_argument("--ack-timeout", type=float, default=5.0, help="per-signal ack timeout s (default 5)")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main_async(parse_args())))
