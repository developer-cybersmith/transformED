---
baseline_commit: "2731109"
---

# Story 4-18: state_change WebSocket Broadcast on Real FSM Transitions

**Status:** done

---

## Story

As Dev 2 (frontend),
I need the server to push a `state_change` frame whenever the tutor FSM actually transitions
(from_state != to_state) so that the lesson player can react to state changes without polling,
unblocking S2-06 (CHECKING_IN UI on `segment_complete`).

---

## Context

- `dispatch_event()` in `graph.py` transitioned state and persisted to Redis but never broadcast
  anything over WebSocket.
- `sprint2/s2-4-session-restore` added a `state_change` send on reconnect-sync, but always with
  `from_state == to_state` — a sync frame, not a transition signal.
- `StateChangeMessage` (`ws.ts:71`) is already in the frozen contract; no interface change required.
- Dev 2 reported this as a 12-day blocker on 2026-07-20.

---

## Acceptance Criteria

- [ ] **AC1:** `dispatch_event` broadcasts `{"type": "state_change", "payload": {"session_id", "from_state", "to_state"}}` whenever `from_state != to_state`.
- [ ] **AC2:** No broadcast is sent when the state does not change (e.g. noop event from TEACHING).
- [ ] **AC3:** Payload keys exactly match the frozen `StateChangeMessage` in `ws.ts` (`session_id`, `from_state`, `to_state` — no extra fields).
- [ ] **AC4:** A tracing failure in `_trace_dispatch` never prevents the broadcast or the return value.
- [ ] **AC5:** All existing 41 graph tests remain green; 3 new tests cover AC1–AC3.

---

## Implementation Notes

- Lazy import `from app.core.websocket import manager` inside `dispatch_event` to avoid circular
  import (`websocket → service → graph → websocket`).
- `current_state_val` (pre-transition, line 444) and `result["current_state"]` (post-transition)
  are compared; both are `str`-compatible (`TutorState` is `StrEnum`).
- Wrapped `_trace_dispatch` call in `try/except` so a missing `langfuse` package never surfaces
  to the caller (defence-in-depth; `_trace_dispatch` already has its own guard).
- Fixed `_stub_langfuse` autouse fixture in `test_tutor_graph.py` to patch `_trace_dispatch`
  directly — avoids the uninstalled `langfuse` SDK import that was breaking all 41 tests.

---

## Files Changed

| File | Change |
|------|--------|
| `apps/api/app/modules/tutor/state_machine/graph.py` | Broadcast in `dispatch_event`; try/except around `_trace_dispatch` |
| `apps/api/tests/test_tutor_graph.py` | 3 new AC tests; autouse fixture fixed; 2 stale langfuse tests rewritten |

---

## Test Results

44/44 passing (`tests/test_tutor_graph.py`).
