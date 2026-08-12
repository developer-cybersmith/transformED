---
id: "S3-41"
title: "WebSocket signal-gap timeout — asyncio.wait_for(30s) + 60s inactivity finalize (D9)"
status: "Draft"
sprint: 3
story_points: 3
owner: Dev4
decisions: D9
depends_on: []
migration: "NO"
---

# Story S3-41 — WebSocket Signal-Gap Timeout: asyncio.wait_for(30s) + 60s Inactivity Finalize (D9)

## User Story

**As a** student in an active lesson session,
**I want** the WebSocket server to tolerate short reading pauses (up to 30 seconds) without
disconnecting me, but detect genuine 60-second silences and cleanly finalize my session,
**so that** I am never falsely disconnected while reading a dense slide, and abandoned sessions
never hang open without CES finalization.

**As the system,**
**I want** a `missed_windows` counter and a WARNING log emitted on every 30-second signal gap,
**so that** operations can observe signal-gap events in real time without a database read.

## Context

**Decision D9** — The WebSocket receive loop currently blocks indefinitely on
`await websocket.receive_text()`. If a student's browser crashes, the network drops silently,
or MediaPipe stops delivering signals, the server coroutine hangs — no cleanup, no CES
finalization, no session record.

**D9 two-level design:**

1. **Per-window timeout (30 s):** Wrap each `receive_text()` call in
   `asyncio.wait_for(..., timeout=30.0)`. A 30-second pause is the expected upper bound for
   reading a dense slide; a single missed window should not trigger finalization.
2. **Inactivity finalize threshold (60 s):** Maintain a `missed_windows: int = 0` counter
   local to the WebSocket coroutine. Each consecutive `asyncio.TimeoutError` increments it;
   any received message resets it to 0. When `missed_windows == 2` (60 s total silence),
   call `finalize_session(session_id, flags={"signal_gap": True})` and close the WebSocket
   with code 1001 (Going Away).
3. **Heartbeat observability (interim):** Log a structured WARNING on every missed window so
   operations can observe gaps without a DB query.

**Why 30 s per window / 60 s total:**
- 30 s: students routinely pause for up to 30 s reading dense slides; a single missed window
  should not finalize.
- 60 s (2 windows): two consecutive missed windows strongly indicate the client is genuinely
  disconnected or the session is abandoned. Two-window hysteresis cannot be provided by a
  single-timeout approach.

**Relationship to other decisions:**
- D11 provides the canonical `finalize_session` that writes `ces_final` and `ended_at`.
  D9 calls that finalize. If D11 is not yet merged, use `_finalize_session_best_effort`.
- D77 (downstream) makes `ws_signal_gap_seconds` configurable via settings — it replaces the
  hardcoded `30.0` with an env var. D9 establishes the mechanism; D77 must not precede D9.

## Acceptance Criteria

### AC1 — asyncio.wait_for wraps receive_text with a 30-second timeout
`websocket_endpoint` in `apps/api/app/core/websocket.py` wraps every
`await websocket.receive_text()` call in `asyncio.wait_for(..., timeout=30.0)`.

The timeout value must be the Python `float` literal `30.0` or a module-level named constant
`_WS_RECEIVE_TIMEOUT_SECONDS = 30.0`. No other numeric literal for the timeout is permitted
at the call site.

Verified by unit test: mock `websocket.receive_text` to raise `asyncio.TimeoutError`; the
endpoint handles it without crashing and routes to the `missed_windows` path.

### AC2 — missed_windows counter is coroutine-local, initialised to 0, resets on message
A `missed_windows: int = 0` integer is declared inside the `websocket_endpoint` coroutine,
before the receive loop. It is NOT stored in Redis (process-local to the receive coroutine
is correct — it tracks the current connection's silence, not cross-process state).

The counter increments by exactly 1 on each consecutive `asyncio.TimeoutError` and resets to
exactly 0 on any successfully received message (regardless of message type).

Verified by two unit tests:
- 1 `TimeoutError` → `missed_windows == 1`; then a valid message arrives → `missed_windows == 0`.
- 2 consecutive `TimeoutError`s → `missed_windows` reaches 2 before finalize fires.

### AC3 — After missed_windows reaches 2, finalize_session is called once with signal_gap=True and socket is closed 1001
When `missed_windows == 2` (second consecutive `asyncio.TimeoutError`), the endpoint:
1. Calls `finalize_session(session_id, flags={"signal_gap": True})` (or
   `_finalize_session_best_effort` if D11 is not yet merged).
2. Awaits `websocket.close(code=1001)`.
3. Exits the receive loop.

The finalize call is made exactly once — not duplicated if `close()` also raises.

Verified by unit test: mock `receive_text` to raise `TimeoutError` twice consecutively →
assert `finalize_session` called exactly once with `{"signal_gap": True}` → assert
`websocket.close` called with `code=1001`.

### AC4 — One missed window (missed_windows == 1) does not finalize
When exactly 1 consecutive `asyncio.TimeoutError` has occurred (`missed_windows == 1`),
neither `finalize_session` nor `websocket.close(code=1001)` is called. The receive loop
continues waiting for the next message.

Verified by unit test: 1 `TimeoutError` → assert `finalize_session` NOT called → mock next
`receive_text` to return a valid JSON payload → assert `missed_windows` resets to 0 →
assert `finalize_session` still NOT called.

### AC5 — WARNING log emitted on each missed window with session_id and missed_windows count
On every `asyncio.TimeoutError` (regardless of `missed_windows` value), `logger.warning()`
is called with a message that contains:
- The `session_id` string (exact UUID value, not redacted).
- The current `missed_windows` integer value (the value AFTER incrementing).

Exact minimum log pattern:
```
"WS signal gap: session=%s missed_windows=%d"
```
or a structurally equivalent format.

Verified by unit test using `caplog.at_level(logging.WARNING)`: assert the captured log
records contain at least one WARNING record that includes both the `session_id` string and the
`missed_windows` integer value as substrings.

### AC6 — Non-TimeoutError exceptions do not increment missed_windows or call finalize
If `receive_text()` raises any exception other than `asyncio.TimeoutError` or
`WebSocketDisconnect` (for example `ConnectionResetError` or `RuntimeError`), the existing
`except Exception` handler in the endpoint fires. This path must NOT:
- Increment `missed_windows`.
- Call `finalize_session` from the timeout path.

The exception handling behaviour for non-timeout errors is unchanged from the pre-D9 code.

Verified by unit test: inject a non-timeout exception → assert `missed_windows == 0` →
assert `finalize_session` NOT called.

### AC7 — WebSocketDisconnect bypasses the missed_windows path and does not double-finalize
`WebSocketDisconnect` (client-side close) still routes to `manager.disconnect(websocket, session_id)`
as before D9. It does NOT increment `missed_windows` and does NOT trigger the signal-gap
`finalize_session` call.

Verified by unit test: `WebSocketDisconnect` raised during `receive_text` →
`manager.disconnect` called → `finalize_session` NOT called from the `missed_windows` branch.

## Tasks / Subtasks

### Task 1 — Story file (this commit)
- [ ] 1.1 Create `docs/stories/S3-41-websocket-signal-gap-timeout-asyncio-wai.md`
- [ ] 1.2 Commit story-only to `sprint3/s3-41-ws-signal-gap-timeout`
- [ ] 1.3 Push story commit to remote

### Task 2 — RED phase (failing tests before implementation)
- [ ] 2.1 Create `apps/api/tests/test_websocket_signal_gap.py`
- [ ] 2.2 Write `test_receive_wrapped_in_wait_for_30s` — AC1
- [ ] 2.3 Write `test_missed_windows_increments_on_timeout` — AC2
- [ ] 2.4 Write `test_missed_windows_resets_on_message` — AC2
- [ ] 2.5 Write `test_finalize_called_after_two_timeouts` — AC3
- [ ] 2.6 Write `test_finalize_flags_signal_gap_true` — AC3
- [ ] 2.7 Write `test_close_1001_called_after_two_timeouts` — AC3
- [ ] 2.8 Write `test_finalize_called_exactly_once_not_twice` — AC3
- [ ] 2.9 Write `test_no_finalize_after_one_timeout` — AC4
- [ ] 2.10 Write `test_missed_windows_resets_after_one_timeout_then_message` — AC4
- [ ] 2.11 Write `test_warning_logged_on_each_timeout` — AC5
- [ ] 2.12 Write `test_warning_log_contains_session_id` — AC5
- [ ] 2.13 Write `test_warning_log_contains_missed_windows_count` — AC5
- [ ] 2.14 Write `test_non_timeout_exception_no_missed_window_increment` — AC6
- [ ] 2.15 Write `test_non_timeout_exception_no_finalize` — AC6
- [ ] 2.16 Write `test_disconnect_does_not_trigger_signal_gap_finalize` — AC7
- [ ] 2.17 Confirm all 16 tests FAIL before any implementation

### Task 3 — GREEN phase (implementation)
- [ ] 3.1 Add `_WS_RECEIVE_TIMEOUT_SECONDS: float = 30.0` constant to `websocket.py`
- [ ] 3.2 Wrap `await websocket.receive_text()` in `asyncio.wait_for(..., timeout=_WS_RECEIVE_TIMEOUT_SECONDS)`
- [ ] 3.3 Add `missed_windows: int = 0` before the receive loop in `websocket_endpoint`
- [ ] 3.4 Add `except asyncio.TimeoutError` branch: increment `missed_windows`, emit WARNING log
- [ ] 3.5 After `missed_windows == 2`: call finalize, close socket with 1001, break loop
- [ ] 3.6 On any successful receive: reset `missed_windows = 0` immediately
- [ ] 3.7 Confirm all 16 tests PASS

### Task 4 — REFACTOR pass
- [ ] 4.1 Run `ruff check apps/api/app/core/websocket.py`
- [ ] 4.2 Run `ruff format --check apps/api/app/core/websocket.py`
- [ ] 4.3 Confirm no logic changes during refactor
- [ ] 4.4 Full regression suite: `pytest apps/api/tests/ -m unit` — 0 failures

### Task 5 — 6-agent adversarial review
- [ ] 5.1 Layer 1 — Story Quality
- [ ] 5.2 Layer 2 — Blind Hunter (Security)
- [ ] 5.3 Layer 3 — Test Coverage
- [ ] 5.4 Layer 4 — AC Completeness
- [ ] 5.5 Layer 5 — Process Integrity
- [ ] 5.6 Layer 6 — Scale & Load

### Task 6 — Completion
- [ ] 6.1 Update `docs/dev4-tracker.md` — mark task complete
- [ ] 6.2 Final commit + push to remote

## Scale & Load

### Q1 — One unit of work and its range
One `asyncio.wait_for` call per 30-second inactivity window, per active WebSocket connection.
A 30-minute lesson generates at most 60 such calls per session (nearly all resolve in < 5 s
when signals arrive from MediaPipe). Gap windows exhaust the 30-second timeout only when
the client is genuinely silent.

Min: 0 gap windows (fully active session). Typical: 0–1 (occasional reading pause).
Maximum before finalize: exactly 2 (60 s total silence then finalize fires and the loop exits).

### Q2 — Fixed budgets while input varies
- `_WS_RECEIVE_TIMEOUT_SECONDS = 30.0` — fixed per deployment (pre-D77). One timeout per 30-s
  silence window, capped at 2 windows before finalize. Beyond 60 s the connection is always
  closed — no WebSocket coroutine stays open indefinitely.
- `missed_windows` cap: implicitly 2 — finalize fires at exactly 2, after which the loop
  exits. No unbounded counter growth.
- Memory: `missed_windows` is one Python `int` (28 bytes). No growth per session or per call.
- At the explicit-error boundary: session finalized with `{"signal_gap": True}` flag, socket
  closed with code 1001. Not a silent truncation.

### Q3 — Scope of every limit
- `_WS_RECEIVE_TIMEOUT_SECONDS = 30.0` — **per-deployment** (same value for all sessions on
  all replicas). Changing it requires an env var update + restart (post-D77) or a code deploy
  (pre-D77).
- `missed_windows` counter — **per WebSocket coroutine** (process-local, not shared across
  replicas). Each connection starts at 0. A reconnect starts a fresh coroutine with a fresh
  counter.
- The 2-window (60 s) finalize threshold — **per connection** (not per session across
  reconnects; the previous connection's counter does not carry forward).

### Q4 — Unbounded reads and writes
None introduced by D9. `missed_windows` is a local integer. No Redis key added. No DB reads.
The finalize call writes to DB (existing behavior from D11, not new to D9). The
`asyncio.wait_for` itself holds no resources beyond the pending `receive_text` coroutine.

At 1,000 concurrent sessions each idle: 1,000 sleeping `wait_for` tasks, each holding only
a coroutine frame reference. This is well within asyncio's scheduling capacity.

### Q5 — Inherited caps re-derived
No prior receive timeout existed — the pre-D9 code blocked indefinitely. D9 introduces the
first cap: 30 s per window, 2 windows before finalize. These values are derived from observed
student behavior:
- 30 s: upper bound for realistic single-slide reading pause (longer pauses indicate a network
  event, tab switch, or session abandonment).
- 60 s (2 windows): two consecutive 30-s silences are a definitive disconnection signal; one
  may be a legitimate reading pause.

No prior cap was sized against a different unit, so there is no inherited cap to re-derive.
After D77 the values become env-var tunable for post-calibration adjustment.

### Q6 — Check-then-act safety under concurrent requests
`missed_windows` is a local integer in a single asyncio coroutine. Incrementing and checking
it are synchronous operations in a single-threaded event loop within that coroutine; no
concurrent access is possible.

The finalize call (D11) uses a Redis NX lock (`finalize_lock:{session_id}`) to prevent
double-finalization across concurrent invocations (reconnect race). D9 does not need its own
lock; D11's lock handles it.

No check-then-act sequence in D9's counter logic: the increment and threshold check are both
synchronous in the same coroutine iteration.

## Security

**IDOR (session scope):** `session_id` is validated against the UUID regex at the route
boundary before the receive loop starts. D9 adds no new session-id-keyed reads or writes
beyond what the finalize call (D11) already does.

**Denial of service (forced finalize):** A malicious client can trigger finalize by going
silent for 60 s. This is accepted — the finalize path is already exercised by legitimate
network drops; no new code is reachable from this vector, and no additional billing or data
change occurs beyond what a normal disconnect would cause.

**Log injection:** `session_id` in the WARNING log is a pre-validated UUID (route boundary
enforces `[0-9a-f\-]` characters only). `missed_windows` is a Python `int`. Neither field
can carry injection sequences. No sanitization required.

**Missing WebSocket JWT authentication:** The `/ws/{session_id}` endpoint does not enforce
JWT authentication (flagged in Story 4-6 as a known follow-up, deferred). D9 does not change
or worsen this posture — the timeout mechanism is orthogonal to authentication.

## Test Requirements

All tests live in the new file `apps/api/tests/test_websocket_signal_gap.py`.

| Test name | AC | What it verifies |
|-----------|----|-----------------|
| `test_receive_wrapped_in_wait_for_30s` | AC1 | `asyncio.wait_for` called with `timeout=30.0` on each receive |
| `test_missed_windows_increments_on_timeout` | AC2 | Counter increments by 1 on `TimeoutError` |
| `test_missed_windows_resets_on_message` | AC2 | Counter resets to 0 on successful receive |
| `test_finalize_called_after_two_timeouts` | AC3 | `finalize_session` called after 2nd consecutive `TimeoutError` |
| `test_finalize_flags_signal_gap_true` | AC3 | `finalize_session` called with `flags={"signal_gap": True}` |
| `test_close_1001_called_after_two_timeouts` | AC3 | `websocket.close(code=1001)` called on 2nd timeout |
| `test_finalize_called_exactly_once_not_twice` | AC3 | `finalize_session` call count is exactly 1 |
| `test_no_finalize_after_one_timeout` | AC4 | After 1 `TimeoutError`, `finalize_session` NOT called |
| `test_missed_windows_resets_after_one_timeout_then_message` | AC4 | Counter resets after 1 gap then a valid message |
| `test_warning_logged_on_each_timeout` | AC5 | `logger.warning` emitted on each `TimeoutError` |
| `test_warning_log_contains_session_id` | AC5 | Log record contains the `session_id` string |
| `test_warning_log_contains_missed_windows_count` | AC5 | Log record contains the `missed_windows` integer |
| `test_non_timeout_exception_no_missed_window_increment` | AC6 | Non-timeout exception does not increment counter |
| `test_non_timeout_exception_no_finalize` | AC6 | Non-timeout exception does not call `finalize_session` |
| `test_disconnect_does_not_trigger_signal_gap_finalize` | AC7 | `WebSocketDisconnect` routes to `manager.disconnect`, not finalize |

## Decision References

| Decision | Role |
|----------|------|
| **D9** | This story — `asyncio.wait_for(30.0)` + `missed_windows` counter + 60 s finalize + WARNING log |
| **D11** | Provides `finalize_session(session_id, flags)` with `ces_final + ended_at` writes + Redis NX double-finalize lock |
| **D77** | Downstream — replaces hardcoded `30.0` with `settings.ws_signal_gap_seconds`; must not precede D9 |

## Dependencies

**No blocking story dependency** for the D9 mechanism itself — the `asyncio.wait_for` change
and `missed_windows` counter are self-contained in the WebSocket coroutine.

**Soft dependency on D11 (S3-35):** `finalize_session` must exist at call time. If Story S3-35
(canonical `finalize_session` with `ces_final + ended_at` writes) is not yet merged, use
`_finalize_session_best_effort` as a stub and update to the canonical call when S3-35 lands.

## Migration

**NO migration required.** This story modifies only `apps/api/app/core/websocket.py`. No
schema changes, no new tables, no new migration file.
