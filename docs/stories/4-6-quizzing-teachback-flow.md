---
baseline_commit: "47e1d004ce826ee8b8849b4c63c3426f783ef4f3"
---

# Story 4-6: CHECKING_IN → QUIZZING → TEACH_BACK → TEACHING Flow + TEACH_BACK Guard Fix

**Status:** in-progress

---

## Story

As Dev 4,
I want the WebSocket layer to drive the comprehension flow (segment_complete → low_checkin_score →
quiz_failed → teachback_complete) into the tutor FSM, AND the "NEVER interrupt mid-TEACH_BACK" guard to be
actually enforced,
so that the Sprint 2 `quizzing_teachback_flow` task is complete and the HIGH bug found in s2-2 review
(interventions leaking the FSM out of TEACH_BACK) is fixed.

---

## Context

Two pieces:

1. **Flow triggers (the task).** The WS endpoint currently dispatches only `attention_signal`,
   `session_start`, `ping`. The comprehension flow needs the client (or server-driven lifecycle) to advance
   the FSM via `segment_complete`, `low_checkin_score`, `quiz_failed`, `teachback_complete` (and the sibling
   lifecycle events). These are **control messages** — the same category as the already-handled `ping` /
   `session_start`, which are NOT in `ws.ts` `ClientMessage` either. (See contract note below.)

2. **HIGH bug from s2-2 review.** `route_from_teach_back` returns `"teaching"` by default, so ANY non-
   `teachback_failed` event — including `distraction_detected` / `fatigue_detected` — drops the FSM out of
   TEACH_BACK into TEACHING. This violates CLAUDE.md §10 "NEVER interrupt mid-TEACH_BACK". The
   `_is_in_teachback` helper exists but is dead code in routing.

---

## Acceptance Criteria

### TEACH_BACK guard (HIGH bug fix)

- **AC 1:** `dispatch_event(sid, "distraction_detected")` while state == TEACH_BACK → stays **TEACH_BACK**
  (intervention suppressed). Same for `fatigue_detected` and any other non-teachback event.
- **AC 2:** Legitimate teach-back transitions still work: `teachback_complete` → TEACHING;
  `teachback_failed` → INTERVENING.

### Flow triggers

- **AC 3:** The WS endpoint dispatches these client-drivable lifecycle events to the FSM via the service
  layer: `segment_complete`, `checkin_complete`, `low_checkin_score`, `quiz_trigger`, `quiz_complete`,
  `quiz_failed`, `teachback_complete`, `teachback_failed`, `lesson_complete`. Each maps 1:1 to the event of
  the same name. Errors are swallowed at the WS boundary (mirrors `_handle_session_start`).
- **AC 4:** A non-whitelisted event a client must NOT be able to drive (e.g. `distraction_detected`,
  `fatigue_detected`, `session_reset`) is rejected (`unknown message type` path) — these are server/engine
  or admin-driven, not client-driven.
- **AC 5:** The full step-through is proven end-to-end through the REAL graph: starting at TEACHING,
  `segment_complete` → CHECKING_IN, `low_checkin_score` → QUIZZING, `quiz_failed` → TEACH_BACK,
  `teachback_complete` → TEACHING. (Stateful Redis mock so each dispatch reads the persisted prior state.)

### No regressions

- **AC 6:** Existing graph + websocket tests stay green (esp. test_tutor_graph all_transitions and
  test_websocket_session B1/B2). Full suite green.

---

## Tasks / Subtasks

- [ ] 1.1 `graph.py` `route_from_teach_back`: keep `teachback_complete`→teaching, `teachback_failed`→
  intervening; change the default from `"teaching"` to `"teach_back"` (stay — guard enforced). Add a comment
  citing §10.
- [ ] 1.2 `service.py`: add `advance_tutor_state(session_id, event)` that validates `event` against a
  `_CLIENT_DRIVABLE_EVENTS` allow-list and calls `dispatch_event(session_id, event)`; raise `ValueError`
  for non-whitelisted events.
- [ ] 1.3 `websocket.py`: route the whitelisted control message types to `_handle_tutor_event(session_id,
  msg_type)` which delegates to `service.advance_tutor_state` inside a try/except (swallow).
- [ ] 1.4 Tests in `test_tutor_graph.py`: AC1 (distraction + fatigue suppressed in TEACH_BACK), AC5
  (step-through with stateful Redis). Tests in `test_websocket_session.py`: AC3 (a flow event dispatches),
  AC4 (server-only event rejected).
- [ ] 1.5 Run new tests + full regression.

---

## Dev Notes

### graph.py — the guard fix (exact)

```python
async def route_from_teach_back(state: TutorMachineState) -> str:
    """Route out of TEACH_BACK.

    CLAUDE.md §10 — NEVER interrupt mid-TEACH_BACK: only an explicit teach-back outcome leaves this
    state. Any other event (incl. distraction_detected / fatigue_detected) is suppressed → stay.
    """
    event = state.get("event", "")
    if event == "teachback_complete":
        return "teaching"
    if event == "teachback_failed":
        return "intervening"
    return "teach_back"  # guard: interventions blocked during teach-back
```

This is the authoritative enforcement (routing-level). It is safe for existing tests — only
`teachback_complete` and `teachback_failed` from TEACH_BACK are currently tested; no test relies on the old
default→teaching.

### service.py — advance_tutor_state

```python
_CLIENT_DRIVABLE_EVENTS = frozenset({
    "segment_complete", "checkin_complete", "low_checkin_score",
    "quiz_trigger", "quiz_complete", "quiz_failed",
    "teachback_complete", "teachback_failed", "lesson_complete",
})

async def advance_tutor_state(session_id: str, event: str) -> None:
    """Dispatch a client-driven lifecycle event into the tutor FSM (allow-listed)."""
    if event not in _CLIENT_DRIVABLE_EVENTS:
        raise ValueError(f"event not client-drivable: {event!r}")
    from app.modules.tutor.state_machine.graph import dispatch_event
    await dispatch_event(session_id, event)
```

`distraction_detected` / `fatigue_detected` are deliberately EXCLUDED — those come from the server-side CES
engine, not the client. `session_start` keeps its own handler; `session_reset` is admin-only.

### websocket.py — routing

Add a module-level `_TUTOR_CLIENT_EVENTS = frozenset({...same 9...})` for endpoint routing, and:

```python
elif msg_type in _TUTOR_CLIENT_EVENTS:
    await _handle_tutor_event(session_id, msg_type)
```

```python
async def _handle_tutor_event(session_id: str, event: str) -> None:
    try:
        from app.modules.tutor.service import advance_tutor_state
        await advance_tutor_state(session_id, event)
    except Exception:
        logger.exception("tutor event %s failed for %s", event, session_id)
```

Keep lazy imports (core ↔ tutor cycle avoidance), consistent with `_handle_session_start`.

### Step-through test (AC5) — stateful Redis

```python
def _stateful_redis(initial: str):
    store = {"tutor_state": initial}
    redis = AsyncMock()
    async def _get(key):
        return store.get("tutor_state") if key.startswith("tutor_state:") else None
    async def _set(key, value, **kw):
        if key.startswith("tutor_state:"): store["tutor_state"] = value
    redis.get = AsyncMock(side_effect=_get)
    redis.set = AsyncMock(side_effect=_set)
    redis.exists = AsyncMock(return_value=0)
    return redis
```
Seed initial="TEACHING", patch get_settings (intervening_node not hit on this happy path, but quiz_failed→
teach_back and teachback_complete→teaching don't need it; segment_complete/low_checkin_score don't either —
add _patch_settings only if a path reaches intervening_node). Then dispatch the 4 events in order, asserting
state after each: CHECKING_IN, QUIZZING, TEACH_BACK, TEACHING. Use distinct thread_id (session_id) so the
MemorySaver checkpoint doesn't collide with other tests; the stateful mock makes `current_state` authoritative.

### Contract note (flag, do not change)

`ws.ts` `ClientMessage` only lists `attention_signal`; `ping`/`session_start`/these flow events are flat
control messages handled by the backend but not in the frozen union. Document them in
`docs/ws-message-contract.md` under the `ws_message_types_final` task (4-dev contract). Do NOT edit `ws.ts`
here.

### Out of scope

- The MED fatigue bug (intervention_type not propagated for `fatigue_detected` → `tutor_fatigue_fired` never
  set) → `full_state_machine`.
- Real intervention message selection / Langfuse spans → `full_state_machine`.

---

## Review outcome (adversarial — Blind + Edge Case Hunter, 2026-06-30)

Guard fix confirmed runtime-safe (`teach_back` is in the entry path map), pins correctly (would fail without
the fix), no behavior lost; ws.ts untouched. 256 tests green. ACs 1–6 met.

**Applied:**
- **[Major] Duplicated allow-list, no equality test.** Added `test_e4_client_event_allowlists_match`
  asserting `_TUTOR_CLIENT_EVENTS == _CLIENT_DRIVABLE_EVENTS` (the duplication is kept for the core↔tutor
  lazy-import discipline; the test guarantees no silent drift).
- **[Major] WS swallow path untested.** Added `test_e3_tutor_event_failure_does_not_raise` (B2 analog:
  a transient FSM error during a flow event is swallowed, not propagated).
- **[Low] AC4 partial.** Parametrized E2 to reject `distraction_detected`, `fatigue_detected`, `session_reset`.

**⚠️ Flagged — NOT changed here:**
- **[SECURITY] Client can self-certify lifecycle outcomes over an unauthenticated WS.** `/ws/{session_id}`
  has no JWT auth (pre-existing, WS-auth is a separate not-yet-done concern), and the allow-list lets a
  client drive `lesson_complete` / `quiz_complete` / `teachback_complete` — i.e. assert outcomes the server
  never verified. Implemented client-driven flow **per the task spec (MVP)**; recommend a hardening
  follow-up: WS JWT auth + route quiz/teach-back outcomes server-side via the assessment API. The allow-list
  already blocks `distraction_detected`/`fatigue_detected`/`session_reset`.
- **[Coverage] Endpoint-level WS routing untested.** All tests call helpers directly; the
  `elif msg_type in _TUTOR_CLIENT_EVENTS` branch isn't driven via `TestClient.websocket_connect` (blocked by
  the repo's `httpx2`/`filterwarnings` collection issue — same limitation as `attention_signal`/`ping`).
- **[Docs] `docs/ws-message-contract.md` still absent** — documenting `ping`/`session_start`/the 9 flow
  control messages is the `ws_message_types_final` deliverable; noted on that task.
