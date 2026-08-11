# Story 3-40 — WebSocket Resilience: Redis Fallback + Signal Gap + Abandonment

**Sprint:** Sprint 3 (CES v2 hardening)
**Dev:** Dev 3 (abandonment write + Redis try/except) + Dev 4 (WebSocket receive loop)
**Status:** ready-for-dev
**Branch:** `sprint3/s3-40-websocket-resilience`
**Depends on:** Story 3-35 (session finalization helper — abandonment reuses it)
**Depends on:** Story 3-39 (session_flags column — abandonment sets `{"abandoned": true}`)

---

## Background

Three gaps in the WebSocket signal processing path were confirmed by audit:

### Gap 1: Redis writes are not guarded

`process_attention_signal` in `apps/api/app/modules/tutor/service.py` executes several Redis
writes (`SET`, `LPUSH`, `LTRIM`, `EXPIRE`). None are wrapped in `try/except`. A Redis
connection failure (Railway Redis restart, transient network blip) raises an unhandled
exception that propagates out of `process_attention_signal`, likely crashing the WebSocket
session for that client with no graceful recovery.

### Gap 2: No signal gap detection

The WebSocket receive loop has no timeout. If a client stops sending
`AttentionSignalMessage` (browser tab backgrounded, network stall, device sleep), the server
waits indefinitely on the next message. There is no `asyncio.wait_for` guard and no
last-signal timestamp tracking. A silent gap is indistinguishable from a slow client.

### Gap 3: Session abandonment leaves DB in broken state

On `WebSocketDisconnect`, `apps/api/app/core/websocket.py:179-183` calls only
`manager.disconnect(session_id)` (in-memory registry cleanup). `sessions.ended_at` and
`sessions.ces_final` remain NULL forever — the session row is indistinguishable from a
session that is currently active, except that no WebSocket is connected. Downstream:
`dna_fusion.fuse_learner_dna()` can never run for abandoned sessions.

### Defect Record

| ID | Description | Status |
|----|-------------|--------|
| D69 | Redis writes in `process_attention_signal` unguarded — failure crashes WebSocket session | Opened by S3-40 |
| D70 | No signal gap detection — silent disconnect indistinguishable from slow client | Opened by S3-40 |
| D71 | Session abandonment leaves `sessions.ended_at = NULL` permanently | Opened by S3-40 |

---

## Acceptance Criteria

### AC 1 — Redis writes wrapped in try/except
All Redis write calls in `process_attention_signal` are wrapped in a single `try/except`
block. On `RedisError` (or the equivalent Redis client exception class for the library in
use): log at ERROR level with session_id, return the already-computed CES value to the
caller (signal processing continues; the in-memory CES value is not lost). The Redis
failure is non-fatal for the session.

### AC 2 — Exception type is verified executable premise
The `except` clause catches the correct base exception from the Redis client library in use
(not a broad `except Exception`). A test `test_redis_error_type_hierarchy` verifies that the
caught exception class is a subclass of the actual Redis client's error base class (per
CLAUDE.md binding rule 3: executable premise assertion for all `except SomeLib.Error` clauses).

### AC 3 — Signal gap detection: 10 s timeout
The WebSocket receive loop uses `asyncio.wait_for(ws.receive_json(), timeout=10.0)`. On
`asyncio.TimeoutError`:
1. If the session has any CES history (>= 1 window), the partial session finalization path
   from Story 3-35 is called (write whatever `ces_final` is available, mark `partial_session`).
2. The WebSocket connection is closed with a 1001 (Going Away) close code.
3. `session_flags` is updated with `{"signal_gap": true}`.
4. The client is NOT notified before close (the timeout implies the client is not responding).

### AC 4 — Session abandonment writes ended_at and ces_final
On `WebSocketDisconnect` (abnormal client close), `finalize_session()` from Story 3-35 is
called. This writes `ended_at = now()` and `ces_final` (NULL if < 5 windows) to `sessions`.
`session_flags` is updated with `{"abandoned": true}` if elapsed time < 180 s.

### AC 5 — Abandonment flag distinct from partial_session
A session can be `{"abandoned": true}` without being `{"partial_session": true}` (e.g.,
a 5-minute session with 60 windows that the user closed deliberately). A session can be
`{"partial_session": true}` without being `{"abandoned": true}` (e.g., an explicit
`SESSION_END` event with < 5 windows). The flags are independent JSONB keys.

### AC 6 — No ruff errors

### AC 7 — Unit tests: 20 minimum
At minimum 20 unit tests: Redis failure → CES returned, no propagation (AC 1), exception
type hierarchy verified (AC 2), 10 s timeout → partial finalization called (AC 3), timeout
→ session_flags has `signal_gap` (AC 3), `WebSocketDisconnect` → `finalize_session` called
(AC 4), `WebSocketDisconnect` short session → `abandoned = true` (AC 5), long session
disconnect → no `abandoned` flag, signal_gap and abandoned are independent flags.

---

## Tasks / Subtasks

- [ ] **T1** Write RED tests
- [ ] **T2** Wrap Redis writes in `process_attention_signal` in try/except (Dev 4 code — coordinate). Identify the correct exception class first (read the Redis client library in use).
- [ ] **T3** Add `test_redis_error_type_hierarchy` to verify exception class (AC 2)
- [ ] **T4** Add `asyncio.wait_for(timeout=10.0)` to WebSocket receive loop (Dev 4 code). Wire `finalize_session` and `session_flags` update on TimeoutError.
- [ ] **T5** Wire `finalize_session` and `session_flags` update in the `WebSocketDisconnect` handler (Dev 4 code). Dev 3 provides the helper; Dev 4 wires the call.
- [ ] **T6** Run `ruff check` + `pytest -m unit` — all pass
- [ ] **T7** 6-agent adversarial code review

---

## Scale & Load

**Q1 — Unit of work and range:**
One try/except per 5-second Redis write group per session. One asyncio.wait_for per receive
iteration per session. Both O(1) overhead. One finalization DB write per disconnect or
timeout per session.

**Q2 — Fixed budgets vs variable input:**
The 10 s timeout is a fixed constant (can be a `settings.ws_signal_timeout_s` env var for
calibration). The partial-session logic is bounded per AC 2 of S3-35 (< 5 windows or
< 180 s → NULL). No accumulation.

**Q3 — Scope of every limit:**
Per-session. The 10 s timeout applies independently to each WebSocket connection. Redis
failure is per-operation (one connection pool, but failure handling is per-call).

**Q4 — Unbounded reads/writes:**
The abandonment `finalize_session` call reads CES history from Redis (bounded by ltrim cap,
see S3-35 Q4). The `session_flags` UPDATE is a single row. No unbounded reads or writes.

**Q5 — Inherited caps re-derived:**
`asyncio.wait_for(timeout=10.0)` — 10 s is 2× the 5 s window interval, giving one missed
window before declaring a gap. Re-derived: a single missed window (5 s silence) is too
aggressive (normal browser jitter can cause 1–2 s delays). Two missed windows (10 s) is
a meaningful gap. This is consistent with standard WebSocket keepalive practice.

The `abandoned` flag threshold of < 180 s is inherited from the partial-session rule in
S3-35. Re-derived: a session < 3 min that disconnects is almost certainly abandoned (the
student left), not a normal completion; a session > 3 min that disconnects may have produced
useful CES data worth retaining. Consistent with S3-35.

**Q6 — Check-then-act under concurrency:**
If a WebSocket timeout and a `WebSocketDisconnect` event fire simultaneously (e.g., timeout
fires while disconnect is processing), both call `finalize_session`. The WHERE `ended_at IS
NULL` guard in the UPDATE (from S3-35 AC 4) makes the second write a no-op. Safe.

The `session_flags ||` JSONB merge in PostgreSQL is not transactional with itself — if two
concurrent UPDATE statements both do `session_flags = session_flags || '{"x": true}'::jsonb`,
one may overwrite the other's JSONB merge. For the two flags that matter here
(`abandoned`, `signal_gap`), only one of timeout or disconnect fires per session (they're
mutually exclusive in the receive loop — once timeout fires, the connection is closed before
disconnect can fire). Concurrent calls are not expected; document this as a known non-issue.

---

## Definition of Done

- [ ] Story file committed before any implementation code
- [ ] RED tests written and confirmed failing before implementation
- [ ] Implementation makes all tests GREEN (minimum 20 unit tests)
- [ ] Ruff: 0 errors in modified files
- [ ] 6-agent adversarial code review passed
- [ ] D69, D70, D71 marked CLOSED in `docs/DEFECT-REGISTER.md`
- [ ] `docs/dev3-assessment-tracker.md` updated
- [ ] PR merged to main

---

## Dev Notes

### Redis try/except pattern (Dev 4 change in tutor/service.py)

First, identify the Redis client exception class:
```python
# Verify the exception hierarchy before writing the except clause
# (CLAUDE.md binding rule 3 — executable premise assertion)
import redis.asyncio as aioredis
assert issubclass(aioredis.RedisError, Exception)

# In process_attention_signal:
try:
    await redis.set(f"session:{session_id}:ces_window", str(ces_value))
    await redis.lpush(f"session:{session_id}:ces_history", str(ces_value))
    await redis.ltrim(f"session:{session_id}:ces_history", 0, MAX_HISTORY - 1)
    await redis.expire(f"session:{session_id}:ces_history", SESSION_REDIS_TTL)
except aioredis.RedisError as exc:
    logger.error(
        "[ces_redis_write] session=%s failed: %s — continuing with in-memory CES value",
        session_id, type(exc).__name__,
    )
    # CES value already computed; return it regardless
```

### asyncio.wait_for pattern (Dev 4 change in websocket.py)

```python
try:
    data = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
except asyncio.TimeoutError:
    logger.warning("[ws_gap] session=%s: 10s signal gap — finalizing as partial", session_id)
    asyncio.create_task(finalize_session(session_id, supabase=supabase, redis=redis, settings=settings))
    asyncio.create_task(
        supabase.table("sessions")
        .update({"session_flags": {"signal_gap": True}})
        .eq("session_id", session_id)
        .execute()
    )
    await ws.close(code=1001)
    break
except WebSocketDisconnect:
    logger.info("[ws_disconnect] session=%s", session_id)
    asyncio.create_task(finalize_session(session_id, supabase=supabase, redis=redis, settings=settings))
    asyncio.create_task(
        supabase.table("sessions")
        .update({"session_flags": {"abandoned": True}})
        .eq("session_id", session_id)
        .is_("ended_at", None)
        .execute()
    )
    break
```

Note: the `abandoned` flag UPDATE carries `.is_("ended_at", None)` so it only fires for
sessions that weren't already finalized (e.g., if the student clicked "End session" in the
UI and then the browser closed — the explicit end already wrote `ended_at`).

### Files to modify

- `apps/api/app/modules/tutor/service.py` — Dev 4 wraps Redis writes in try/except
- `apps/api/app/core/websocket.py` — Dev 4 adds timeout + disconnect finalization
- `apps/api/tests/test_websocket_resilience.py` — new test file
