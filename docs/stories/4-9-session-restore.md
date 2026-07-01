---
baseline_commit: "baf7d0b8570de75af5dd2ff2f7e2a68cb0145e48"
---

# Story 4-9: Session State Restore on Reconnect

**Status:** in-progress

---

## Story

As Dev 4,
I want a WebSocket reconnect to restore the live tutor state (read `tutor_state:{session_id}` from Redis
and push it to the client) instead of resetting the session,
so that a student who drops and reconnects mid-session resumes where they were — the Sprint 2
`session_restore` task.

---

## Context

`ConnectionManager.connect()` currently calls `_init_session_state(session_id)` **unconditionally**, which
sets `tutor_state` to IDLE and clears `distraction_count` / `cooldown` / `fatigue_fired` / `segment_index`.
That's correct for a NEW session but **destroys** the state on a reconnect. Restore must distinguish the two:

- **Reconnect** (a `tutor_state:{sid}` already exists) → push the current state to the client, do NOT reset.
- **New session** (no `tutor_state`) → initialise fresh (today's behavior).

ws.ts has `state_change` (a transition) but no `state_sync`. `state_sync` is a new outbound control message
(like the other server→client messages); use the nested-payload shape for discriminated-union consistency and
flag it for `ws_message_types_final` (do NOT edit frozen ws.ts here).

---

## Acceptance Criteria

- **AC 1:** On connect, if `tutor_state:{session_id}` exists in Redis, the server sends the reconnecting
  client `{"type": "state_sync", "payload": {"session_id": <id>, "state": <current state>}}` and does NOT
  reset session state (no `_init_session_state`).
- **AC 2:** On connect with NO existing `tutor_state`, the server initialises a fresh session
  (`_init_session_state` as today) and does NOT send `state_sync`.
- **AC 3:** The restored state is read from Redis (`tutor_state:{sid}`) — no DB, only a Redis GET on connect.
- **AC 4:** A Redis failure while checking for prior state must not break the connection handshake — degrade
  to fresh init, never raise out of `connect()`.
- **AC 5:** `state_sync` carries the exact stored state string (e.g. `"QUIZZING"`, `"TEACHING"`).

---

## Tasks / Subtasks

- [ ] 1.1 Add `_restore_or_init_session(session_id) -> str | None` in `websocket.py`: GET `tutor_state:{sid}`;
  if present, return it (reconnect, no reset); else call `_init_session_state` and return `None`. Swallow
  Redis errors → init fresh, return `None`.
- [ ] 1.2 `ConnectionManager.connect`: after accept + register, call the helper; if it returns a state, send
  `state_sync` to the just-accepted `websocket` (`websocket.send_json`).
- [ ] 1.3 Tests in `test_websocket_session.py`: reconnect (existing state → state_sync, no reset),
  new session (no state → init, no state_sync), Redis-failure degrade.
- [ ] 1.4 Run new tests + full regression.

---

## Dev Notes

### websocket.py — helper + connect

```python
async def _restore_or_init_session(session_id: str) -> str | None:
    """Reconnect-aware: if a tutor_state already exists, return it (restore, no reset);
    otherwise initialise a fresh session and return None. Never raises (handshake must not fail)."""
    try:
        from app.core.redis import get_redis  # type: ignore[import]
        existing = await get_redis().get(f"tutor_state:{session_id}")
        if existing:
            state = existing.decode() if isinstance(existing, (bytes, bytearray)) else str(existing)
            logger.info("WS reconnect: session=%s restoring state=%s", session_id, state)
            return state
    except Exception:
        logger.warning("reconnect-state read failed for %s — initialising fresh", session_id)
    await _init_session_state(session_id)
    return None
```

```python
async def connect(self, websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    self._connections[session_id].append(websocket)
    restored = await _restore_or_init_session(session_id)
    if restored is not None:
        await websocket.send_json(
            {"type": "state_sync", "payload": {"session_id": session_id, "state": restored}}
        )
    logger.info("WS connected: session=%s  total_sessions=%d", session_id, len(self._connections))
```

Note: this replaces the unconditional `await _init_session_state(session_id)` in `connect`. The A-group
tests call `_init_session_state` directly (not via connect), so they're unaffected. `redis_mock.get` may
return a `str` (decode_responses) or `bytes` — handle both.

### state_sync shape decision

Tracker example was flat `{type, state}`; use the **nested** `{type, payload:{session_id, state}}` to match
every other server→client message (lesson_ready, tutor_intervene, attention_ack, ws.ts `WsMessage<T,P>`),
so Dev 2's discriminated-union client parses it uniformly. Flag for `ws_message_types_final`.

### Tests (mock websocket + redis; no TestClient — avoids the httpx2 collection issue)

- `test_reconnect_sends_state_sync`: `get_redis().get(tutor_state:sid)` → `"QUIZZING"`; build a mock
  `websocket` (AsyncMock: `accept`, `send_json`); `await manager.connect(ws, sid)`; assert
  `ws.send_json` called with `{"type":"state_sync","payload":{"session_id":sid,"state":"QUIZZING"}}`; assert
  `redis.set` NOT called (no reset).
- `test_new_session_inits_no_state_sync`: `get(tutor_state)` → `None`; connect; assert `redis.set` called
  (IDLE init) and `ws.send_json` NOT called with a state_sync (no restore).
- `test_reconnect_read_failure_degrades_to_init`: `get_redis` side_effect / `get` raises → connect still
  completes, falls back to `_init_session_state`, no `state_sync`, no raise.
- Use a fresh `ConnectionManager()` per test (or the singleton with a unique session id) to avoid connection-
  registry leakage; `manager.disconnect` cleanup not required for these assertions.

### Out of scope / flagged

- Reused-session-id ambiguity (a brand-new session reusing an id whose `tutor_state` hasn't expired would be
  treated as a reconnect) — acceptable given UUID session ids + 24h TTL; note it.

---

## Review outcome (adversarial — Blind + Edge Case Hunter, 2026-06-30)

Both reviewers converged on two HIGH findings; both fixed. 282 tests green.

**Applied:**
- **[HIGH] `state_sync` was off-contract.** ws.ts (frozen, §16) has no `state_sync` — a strict client can't
  narrow it. **Switched to the frozen `state_change` message** `{session_id, from_state, to_state}` with
  `from == to` (a sync, not a transition). The feature now works end-to-end with Dev 2's discriminated-union
  client without touching the frozen contract. (The frozen ws.ts outranks the tracker's suggested `state_sync`
  name; updated AC1/AC5 accordingly.)
- **[HIGH] Unguarded `send_json` in `connect()`** leaked the registry entry and escaped the endpoint's try
  (which awaits `manager.connect` outside its `try`). Now wrapped: on failure it logs + `disconnect`s the dead
  socket. Covered by `test_f6_reconnect_send_failure_does_not_break_connect`.
- **[Medium] bytes-decode + non-QUIZZING state untested** → `test_f5_reconnect_decodes_bytes_state`
  (`b"TEACH_BACK"`).

**Flagged — NOT changed (out of AC scope / need product input):**
- Stale-session-id reuse skips the guard-counter reset (distraction/cooldown/fatigue/segment) — documented;
  negligible with UUID ids; true fix needs a live-session signal/heartbeat.
- Reconnect to a terminal `SESSION_END` restores a dead session (product-edge).
- `segment_index` (player position) is not part of restore — `state_change` carries the FSM state name only;
  full position-resume is a follow-up.
- Concurrent first-connect double-init race — harmless (idempotent init).
