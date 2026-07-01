---
baseline_commit: "c9920be"
---

# Story 4-15: WebSocket Load-Test Harness + Report (50 concurrent sessions)

**Status:** done

---

## Story

As Dev 4,
I want a runnable load-test harness that simulates N concurrent WebSocket sessions (each connect →
`session_start` → send M `attention_signal`s over a duration → disconnect) and aggregates connection
drops + ack-latency, plus a report doc,
so that the Sprint 4 `ws_load_test` task is satisfied: the tooling exists, is validated locally, and the
production 50-user/5-min run is documented + ready to execute against staging.

---

## Context

- AC target (tracker): "Use `locust` or `websockets` to simulate 50 concurrent WS sessions; each: connect →
  send 60 attention_signals over 5 minutes → disconnect. Target: 0 dropped connections, memory stable,
  Redis connections < pool max (20). Report in `docs/sprint4-ws-load-test.md`; 0 drops at 50 users."
- Inbound/outbound shapes are fixed (see `docs/ws-message-contract.md`): send nested `attention_signal`;
  the server replies `attention_ack` `{payload:{session_id, ces}}`. `session_start` gets no reply.
- `websockets` 15.0.1 is available in the dev venv (single-arg handler `async def handler(ws)`); it is NOT
  in `pyproject.toml` (same as `scripts/mock_ws_client.py` — a manual dev-env dep).

### Honesty constraint (important)

A **real** 50-user / 5-min run needs a running API + Redis. This environment has **no running server**
(`Settings` requires secrets; no India-region deploy yet — a Sprint-3 prerequisite per CLAUDE.md). So we do
**not fabricate** production numbers. Instead the harness has a `--self-test` mode that spins an in-process
reference WS server (mimicking `attention_ack`) so the harness + concurrency model are **validated with
real numbers at 50 concurrent connections locally**, and the report clearly separates "harness validated
locally" from "full production run — pending staging".

---

## Acceptance Criteria

- **AC 1:** `scripts/ws_load_test.py` simulates `--sessions N` concurrent sessions; each connects, sends
  `session_start`, sends `--signals M` `attention_signal`s spaced over `--duration S` seconds, awaits each
  `attention_ack`, then disconnects. Configurable `--host`, timeouts.
- **AC 2:** It aggregates and prints: sessions attempted / connected / **dropped**, signals sent, acks
  received / missed, and ack-latency p50/p95/max. Exit code `0` iff drops == 0 (so it's CI/gateable).
- **AC 3:** A `--self-test` flag spins an in-process reference server and runs the load against it (no
  external server needed), proving the harness end-to-end.
- **AC 4:** `summarize(results)` is a pure function (no I/O) returning the aggregate dict, unit-tested with
  synthetic results (drops, percentiles, ack-miss) — no sockets in the test (avoids flakiness).
- **AC 5:** `docs/sprint4-ws-load-test.md` documents methodology, targets, how-to-run (self-test + against
  staging), and a Results section populated with the **real** local self-test numbers (≥50 concurrent,
  0 drops), with the production 50-user/5-min run explicitly marked pending staging/India deploy.

---

## Tasks / Subtasks

- [ ] 1.1 `scripts/ws_load_test.py`: argparse (`--host`, `--sessions`, `--signals`, `--duration`,
  `--self-test`, `--connect-timeout`, `--ack-timeout`); `SessionResult` dataclass; `_run_session()`;
  `_reference_server()` (self-test); pure `summarize()`; `main()` that gathers all sessions, prints the
  summary, and exits non-zero on drops.
- [ ] 1.2 `apps/api/tests/test_ws_load_test.py`: load the script module by path (importlib) and test
  `summarize()` with synthetic `SessionResult`s — 0-drop case, drop case, latency percentiles, ack-miss.
- [ ] 1.3 Run the self-test live at 50 concurrent (short duration) to capture real numbers.
- [ ] 1.4 `docs/sprint4-ws-load-test.md` with methodology + the captured self-test results + pending-staging note.
- [ ] 1.5 Full regression.

---

## Dev Notes

### scripts/ws_load_test.py (core shape)

```python
import argparse, asyncio, json, statistics, sys, uuid
from dataclasses import dataclass, field
import websockets

@dataclass
class SessionResult:
    session_id: str
    connected: bool = False
    signals_sent: int = 0
    acks: int = 0
    missed_acks: int = 0
    latencies: list[float] = field(default_factory=list)
    error: str | None = None

def _signal(session_id: str) -> str:
    return json.dumps({"type": "attention_signal", "payload": {
        "session_id": session_id, "quiz_accuracy": 0.8, "teachback_score": None,
        "behavioral_score": 0.9, "head_pose_score": 0.75, "blink_rate": 0.3}})

async def _run_session(uri, session_id, signals, duration, connect_timeout, ack_timeout) -> SessionResult:
    res = SessionResult(session_id)
    interval = duration / signals if signals else 0
    loop = asyncio.get_event_loop()
    try:
        async with websockets.connect(uri, open_timeout=connect_timeout) as ws:
            res.connected = True
            await ws.send(json.dumps({"type": "session_start"}))
            for i in range(signals):
                t0 = loop.time()
                await ws.send(_signal(session_id))
                res.signals_sent += 1
                try:
                    # read until our ack arrives (skip other server frames)
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
    except Exception as exc:  # connection refused, handshake fail, mid-run drop
        res.error = repr(exc)
    return res

def summarize(results: list[SessionResult], sessions_requested: int) -> dict:
    connected = [r for r in results if r.connected]
    dropped = sessions_requested - len(connected)  # never-connected OR errored-before-connect
    errored = [r for r in results if r.error]
    lat = [x for r in results for x in r.latencies]
    def pct(p):
        if not lat: return None
        s = sorted(lat); k = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
        return round(s[k] * 1000, 2)  # ms
    return {
        "sessions_requested": sessions_requested,
        "sessions_connected": len(connected),
        "sessions_dropped": dropped,
        "sessions_errored": len(errored),
        "signals_sent": sum(r.signals_sent for r in results),
        "acks_received": sum(r.acks for r in results),
        "acks_missed": sum(r.missed_acks for r in results),
        "latency_ms_p50": pct(50), "latency_ms_p95": pct(95),
        "latency_ms_max": round(max(lat) * 1000, 2) if lat else None,
    }
```

`_reference_server` (self-test): `websockets.serve(handler, "127.0.0.1", port)`, handler replies
`attention_ack` to each `attention_signal` and `pong` to `ping`; ignores `session_start`. Use an
ephemeral port (bind 0 → read actual port from the server object) and an `asyncio.Event` ready-gate.

`main()`: if `--self-test`, start the reference server, point `uri` at it; else use `--host`. Build
`[_run_session(...) for _ in range(sessions)]`, `await asyncio.gather(*tasks)`, `summarize`, print JSON +
a human table, `sys.exit(0 if summary["sessions_dropped"] == 0 else 1)`.

### Test (pure summarize — no sockets)

Load the module by path so the script needn't be a package:
```python
import importlib.util, pathlib
_p = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ws_load_test.py"
spec = importlib.util.spec_from_file_location("ws_load_test", _p)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
```
Then build synthetic `mod.SessionResult`s and assert `mod.summarize(...)` for: all-connected-0-drops,
some-never-connected → drops, latency percentiles, ack-miss counting.

### Out of scope / flagged

- The full **50-user / 5-min production run** requires a running API + Redis (ideally the India-region
  deploy — Sprint-3 prerequisite). Documented as the remaining step; the harness is ready to point at it.
- Memory + Redis-connection-count observation are server-side metrics (Railway dashboards) captured during
  the staging run, not by this client harness — noted in the report.

---

## Review outcome (adversarial, 2026-06-30) — FIX-FIRST → fixed

The reviewer verified ack accounting, percentile math, self-test fidelity, report honesty, resource safety,
and the tests as sound — but found one genuine **HIGH false-green**:

- **[HIGH] Mid-run drops were not counted.** `_run_session` sets `connected=True` after the handshake; if
  the server killed the socket mid-run, `ws.recv()` raised `ConnectionClosed` → caught by the outer handler
  (sets `error`) but `connected` stayed `True`. The original `dropped = requested - connected` therefore
  **missed connect-then-die sessions** — the harness could exit 0 / report "0 drops" while connections
  dropped. **Fixed:** a drop is now any session that didn't cleanly complete (`connected and not error`);
  `dropped = requested - completed`. Added a `passed` gate (`0 drops AND 0 errors AND 0 missed acks`) that
  drives the exit code and the printed RESULT. New tests: `test_summarize_mid_run_death_counts_as_drop`,
  `test_summarize_passed_flag` (7 summarize tests total).
- **[MED] Happy-path stub not disclosed / errored-vs-dropped relationship unclear.** The report now states
  the reference server always acks (so the drop/missed-ack paths are pinned by unit tests, not the self-test)
  and that the AC gate is drops **and** errors **and** missed-acks == 0.

Re-ran: self-test 50/50 PASS (exit 0); full api suite **309 passed, 1 skipped**. Verified bugs found during
dev (Windows cp1252 box-char crash in `_print_summary`; importlib `parents[3]` + `sys.modules` registration)
also fixed.
