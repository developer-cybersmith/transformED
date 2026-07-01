# Sprint 4 — WebSocket Load-Test Report

**Owner:** Dev 4 · **Task:** `ws_load_test` (Sprint 4) · **Date:** 2026-06-30
**Harness:** `scripts/ws_load_test.py` · **Status:** harness built + locally validated; **production 50-user/5-min run pending staging**

---

## Objective (AC)

Simulate **50 concurrent WebSocket sessions**, each: connect → `session_start` → send **60
`attention_signal`s over 5 minutes** → disconnect. Targets: **0 dropped connections**, memory stable,
Redis connection count < pool max (20).

---

## Harness

`scripts/ws_load_test.py` spawns N concurrent asyncio sessions against a target WS endpoint. Each session:

1. connects to `/ws/{session_id}`,
2. sends `session_start`,
3. sends `--signals` `attention_signal`s (nested envelope per `docs/ws-message-contract.md`) spaced evenly
   over `--duration` seconds, awaiting each `attention_ack` (bounded by `--ack-timeout`, skipping any other
   server frames),
4. disconnects.

It aggregates: sessions attempted / connected / completed / **dropped** / errored, signals sent, acks
received / missed, and ack-latency **p50 / p95 / max**. A **drop** = any requested session that did not
cleanly complete — never connected **or** connected then died mid-run (a connect-then-die session is *not*
counted as healthy). **Exit code is `0` iff the run PASSES: `sessions_dropped == 0` AND
`sessions_errored == 0` AND `acks_missed == 0`** — so a half-completed run cannot read green. Gateable in
CI / a staging smoke job.

### How to run

```bash
# Manual dev dep (not in pyproject, same as scripts/mock_ws_client.py):
pip install websockets

# Against a running server (the production-shaped run — 50 users, 60 signals over 5 min):
python scripts/ws_load_test.py --host ws://<staging-host> --sessions 50 --signals 60 --duration 300

# Self-validation (in-process reference server; no external server needed):
python scripts/ws_load_test.py --self-test --sessions 50 --signals 3 --duration 1.5
```

Flags: `--host`, `--sessions` (50), `--signals` (60), `--duration` (300s), `--self-test`,
`--connect-timeout` (10s), `--ack-timeout` (5s).

---

## Results

### 1. Harness self-validation — 50 concurrent (local, in-process reference server) ✅

`--self-test` spins an in-process reference server that mirrors the production reply contract
(`attention_ack` per signal, `pong` per `ping`, no reply to `session_start`) and runs the full concurrent
client fleet against it. This validates the **harness + the 50-way concurrency model** end-to-end with real
measured numbers (it does **not** exercise the real FastAPI app / Redis — see §2).

Command: `--self-test --sessions 50 --signals 3 --duration 1.0 --ack-timeout 3`

| Metric | Result |
|--------|--------|
| sessions requested | 50 |
| sessions connected | **50** |
| sessions completed | **50** |
| **sessions dropped** | **0** ✅ |
| sessions errored | 0 |
| signals sent | 150 |
| acks received | **150** (0 missed) |
| ack latency p50 / p95 / max | **3.44 / 4.28 / 7.23 ms** |
| RESULT | **PASS** (0 drops + 0 errors + 0 missed acks) |
| process exit code | `0` |

*(Latency is loopback floor and varies slightly run-to-run; an earlier run measured 3.83 / 7.12 / 9.32 ms.)*

**Reading:** 50 concurrent connections, every signal acknowledged, zero drops, single-digit-ms ack latency
against a no-op reference server. This confirms the client harness, the concurrency model, and the
message/ack contract are correct. The latency figures are a **harness/loopback floor**, not representative
of production CES computation + Redis I/O.

**Stub caveat:** the reference server is a **happy-path stub** — it always acks and never drops, so the
self-test does not exercise the harness's drop / missed-ack accounting end-to-end. Those paths are pinned by
the unit tests instead (`test_summarize_mid_run_death_counts_as_drop`, `test_summarize_passed_flag`,
`test_summarize_counts_missed_acks`), which assert that a connect-then-die session counts as a **drop** and
fails the run. So the false-green ("connected then killed mid-run" silently passing) is guarded in code.

### 2. Production run — 50 users × 60 signals over 5 min — ⏳ PENDING

**Not yet executed.** A representative run requires a running API + Redis under realistic conditions, ideally
the **India-region deployment** (a Sprint-3 prerequisite per `CLAUDE.md` — Railway has no India region; the
FastAPI/ARQ stack must migrate to Fly.io Mumbai / Render Singapore / AWS ap-south-1 before real-student load).
The harness is ready to point at that host unchanged:

```bash
python scripts/ws_load_test.py --host ws://<staging-host> --sessions 50 --signals 60 --duration 300
```

To populate this section, run the command against staging and record the same metrics table, plus the
**server-side** observations below (not captured by the client harness):

- **Memory stability** — Railway/host metrics dashboard across the 5-minute run (flat, no leak).
- **Redis connection count < 20** — confirm the shared pool stays under `pool max` while 50 sessions push
  the CES buffer (`LPUSH/LTRIM` + `tutor_ces`/`ces_window` writes per signal).
- **0 dropped connections** at the application layer (the harness reports client-observed drops; cross-check
  with server WS-disconnect logs).

---

## Notes / follow-ups

- The harness measures **client-observed** drops + ack latency. Memory and Redis-pool metrics are server-side
  (host dashboards), captured during the staging run.
- `websockets` is a manual dev dependency (not in `apps/api/pyproject.toml`), consistent with
  `scripts/mock_ws_client.py`.
- The pure aggregation (`summarize()`) is unit-tested in `apps/api/tests/test_ws_load_test.py` (5 cases,
  socket-free); the end-to-end path is validated by the `--self-test` run above.
