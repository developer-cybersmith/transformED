# Story 3-41: Configurable WebSocket Signal-Gap Timeout (D77)

## Story

**As a** student (Priya) reading a complex slide,  
**I want** the WebSocket connection to remain open for at least 60 seconds without a signal,  
**so that** I am not disconnected mid-lesson simply because I paused to read or think.

## Context

**Defect:** D77 — `websocket.py` uses `await asyncio.wait_for(websocket.receive_text(), timeout=10.0)`. A student who pauses for more than 10 seconds (reading a dense slide, writing notes, context-switching) is disconnected with `TimeoutError → finalize(signal_gap=True)`. This produces spurious lesson abandonment events and incorrect CES finalization.

**Approved fix (Option a):** Move the timeout to `settings.ws_signal_gap_seconds` with a default of 60 seconds. The timeout behavior on expiry (finalize with `signal_gap=True`) stays unchanged.

**Locked constraint:** Do NOT invent new WS behavior. Only change the hardcoded `10.0` literal to `settings.ws_signal_gap_seconds`. The finalization-on-gap path and error handling remain exactly as-is.

## Acceptance Criteria

### AC1 — Config field added
`settings.ws_signal_gap_seconds` exists in `config.py` as a positive `float`, default `60.0`, sourced from env var `WS_SIGNAL_GAP_SECONDS`. Field validates that value > 0 (boot-time error if ≤ 0).

### AC2 — WebSocket endpoint uses config value
`websocket.py:websocket_endpoint` reads `settings.ws_signal_gap_seconds` and passes it to `asyncio.wait_for(…, timeout=settings.ws_signal_gap_seconds)`. The hardcoded `10.0` literal is removed.

### AC3 — Timeout behavior unchanged
A `TimeoutError` from `asyncio.wait_for` still triggers `_finalize_session_best_effort(…, flags={"signal_gap": True})` and `websocket.close(1001)`. No new code paths are introduced.

### AC4 — Configurable via env var
Setting `WS_SIGNAL_GAP_SECONDS=30` in environment produces a `settings.ws_signal_gap_seconds == 30.0`. Verified by unit test against `config.py`.

### AC5 — Zero/negative values rejected at boot
`ws_signal_gap_seconds=0` or `-1` raises `ValidationError` on `Settings()` construction. The server does not start with an invalid timeout.

### AC6 — Existing WebSocket resilience tests still pass
All tests in `tests/test_websocket_resilience.py` pass without modification. The timeout behavior being tested is driven from settings, which can be patched in tests.

### AC7 — DEFECT-REGISTER.md updated
D77 status updated to `FIXED` with story reference `S3-41` and the guard (`test_ws_signal_gap_timeout_configurable`, CI enforced).

## Scale & Load

1. **Unit of work and range:** One WebSocket connection per active student session. Typical: 1 active session per student. Range: 1–∞ concurrent sessions (Sprint 3 launch: 1 real student, load test Sprint 4).
2. **Fixed budget while input varies:** The timeout value is a fixed config per deployment. Changing it requires env var update + restart. No per-session budget concerns. A value of 60s means each idle slot holds a goroutine-equivalent coroutine open for up to 60s — at 1,000 concurrent sessions this is 1,000 open tasks; acceptable for Sprint 4 scale target.
3. **Scope of limit:** Per-deployment (all sessions share the same `settings.ws_signal_gap_seconds` value). Not per-user or per-session.
4. **Unbounded reads/writes:** None. This change touches no DB reads or writes. It only modifies the `asyncio.wait_for` call duration.
5. **Inherited caps re-derived:** The original 10.0s was never designed — it was a default. 60s is derived from: "a student reading a dense slide should not be disconnected." No prior cap reason justifies 10s; 60s is the new derived value. Value is now configurable, so no re-derivation needed in future — tune via env var.
6. **Check-then-act safety:** No check-then-act sequence involved. `asyncio.wait_for` is atomic. `TimeoutError` handling remains unchanged.

## Dev Notes

- File to change: `apps/api/app/config.py` (add field) and `apps/api/app/core/websocket.py` (remove hardcoded `10.0`)
- The exact call site: `websocket.py` near line 185 — `await asyncio.wait_for(websocket.receive_text(), timeout=10.0)`
- Pydantic validator for `ws_signal_gap_seconds > 0`: use `@field_validator('ws_signal_gap_seconds')` or a `@model_validator`. Keep it consistent with the existing config validator style.
- Test approach: unit test on `Settings(ws_signal_gap_seconds=60.0)` succeeds; `Settings(ws_signal_gap_seconds=0)` raises `ValidationError`. Test that the websocket endpoint patches `settings.ws_signal_gap_seconds` and that `asyncio.wait_for` receives the correct value.
- Do NOT add retry logic, heartbeat pings, or any other WS behavior — only the timeout value changes.
- Guard: `test_ws_signal_gap_timeout_configurable` in `tests/test_websocket_resilience.py` or a new file verifies the setting is used. Must be in CI.

## BMAD Process Gate

- [ ] Story file committed first: `git commit -m "docs(story-first): Story 3-41 — configurable WS signal-gap timeout"`
- [ ] Story commit pushed to `sprint3/s3-41-ws-signal-gap-timeout` before any implementation
- [ ] RED tests written and failing before implementation
- [ ] GREEN implementation makes tests pass
- [ ] REFACTOR pass (no logic changes)
- [ ] DEFECT-REGISTER.md D77 updated to FIXED + guard name

## Status

Draft
