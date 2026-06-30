---
baseline_commit: "f12d8785077f9e8bd1a5abc33ee0aa0a7ee8bc75"
---

# Story 4-4: IDLE → TEACHING State Transition Live (graph topology fix)

**Status:** in-progress

---

## Story

As Dev 4,
I want `dispatch_event(session_id, "session_start")` to apply exactly one transition (IDLE → TEACHING),
persist the new state, and return — instead of recursing into a `teaching → teaching` self-loop —
and I want it proven end-to-end through the real graph,
so that the Sprint 1 `idle_to_teaching` task moves from **Partial** to **Completed** on verified runtime
behaviour.

---

## Context — cross-check finding (2026-06-29)

The wiring the tracker said was "missing" **already exists**: `websocket.py` handles the `session_start`
message → `_handle_session_start` → `dispatch_event(session_id, "session_start")`, and `graph.py` has the
`idle → teaching` edge. The stale tracker notes were wrong about that.

**But the transition is broken at runtime.** Measured: `dispatch_event(session_id, "session_start")` with a
neutralised Redis runs `idle_node` 1× then `teaching_node` 11× and raises **`GraphRecursionError`** (at
`recursion_limit=12`; ~24 at the default). Root cause: LangGraph runs the graph to completion every
`ainvoke`, but `route_from_teaching` returns `"teaching"` (default) for `session_start` and the edge maps
`"teaching" → "teaching"` — an infinite self-loop. It was never caught because **every existing test mocks
`dispatch_event`**; the real graph has zero coverage.

## Architect decision (Winston, 2026-06-29)

Convert the FSM to **one transition per dispatch**: a conditional **entry router** picks the target node
from `(current_state, event)`, that one node persists, then `→ END`. No self-loops. Existing guard logic
(`route_from_*`) is reused unchanged — relocated from post-node to entry, keyed by `current_state`.

---

## Acceptance Criteria

### Graph fix (production)

- **AC 1:** `dispatch_event(session_id, "session_start")` on a fresh session (Redis state absent → IDLE)
  returns a state whose `current_state == TutorState.TEACHING`, and does **not** raise `GraphRecursionError`.
- **AC 2:** The transition persists `tutor_state:{session_id} = "TEACHING"` to Redis (one `redis.set`).
- **AC 3:** An unrecognised event from TEACHING (e.g. `dispatch_event(sid, "noop")` with Redis state
  `TEACHING`) returns `current_state == TEACHING` and terminates (no recursion) — proving the self-loop is
  gone for the default/no-op path.
- **AC 4:** Routing uses the **live** `current_state` seeded from Redis, not a stale checkpoint: with Redis
  `tutor_state = "QUIZZING"`, `dispatch_event(sid, "quiz_complete")` routes per QUIZZING (→ TEACHING), and
  with an unrecognised event stays QUIZZING. (Verifies the MemorySaver channel-merge nuance.)
- **AC 5:** `config` passed to `graph.ainvoke` includes `recursion_limit` (small, e.g. 5) as a regression
  tripwire so any future self-loop fails fast instead of hanging.

### Service-layer caller (discipline §5 + tracker contract)

- **AC 6:** `tutor/service.py` exposes `async def start_session(session_id) -> None` that calls
  `dispatch_event(session_id, "session_start")`; `_handle_session_start` in `websocket.py` delegates to it
  (mirrors how `_handle_attention_signal` delegates to `process_attention_signal`). Errors are still
  swallowed at the websocket boundary.

### Coverage

- **AC 7:** New tests exercise the **real** graph (only Redis mocked) for AC 1–4; a unit test covers
  `start_session` dispatching `session_start` (mocked). No regression in existing suites.

---

## Tasks / Subtasks

- [ ] 1.1 `graph.py`: remove `set_entry_point("idle")`, `add_edge("idle","teaching")`,
  `add_edge("intervening","teaching")`, and all 5 `add_conditional_edges(...)`.
- [ ] 1.2 `graph.py`: add `route_from_idle` and `route_from_intervening`; add `_ROUTE_BY_STATE` map and
  async `route_entry`; `set_conditional_entry_point(route_entry, {<7 nodes> + END})`.
- [ ] 1.3 `graph.py`: `add_edge(node, END)` for all 7 nodes.
- [ ] 1.4 `graph.py` `dispatch_event`: add `"recursion_limit": 5` to `config`.
- [ ] 1.5 `service.py`: add `start_session(session_id)`.
- [ ] 1.6 `websocket.py` `_handle_session_start`: delegate to `service.start_session` (keep error swallow).
- [ ] 1.7 `tests/test_tutor_graph.py` (new): AC 1–4 against the real graph (mock Redis).
- [ ] 1.8 `tests/test_tutor_service.py` or new: `start_session` unit test (AC 6).
- [ ] 1.9 Run new tests + full regression.

---

## Dev Notes

### graph.py — exact shape (from Architect)

```python
from langgraph.graph import END, StateGraph

async def route_from_idle(state) -> str:
    return "teaching" if state.get("event") == "session_start" else "idle"

async def route_from_intervening(state) -> str:
    return "teaching" if state.get("event") == "intervention_complete" else "intervening"

_ROUTE_BY_STATE = {
    TutorState.IDLE: route_from_idle,
    TutorState.TEACHING: route_from_teaching,
    TutorState.INTERVENING: route_from_intervening,
    TutorState.CHECKING_IN: route_from_checking_in,
    TutorState.QUIZZING: route_from_quizzing,
    TutorState.TEACH_BACK: route_from_teach_back,
    TutorState.SESSION_END: route_from_session_end,
}

async def route_entry(state) -> str:
    current = state.get("current_state") or TutorState.IDLE
    router = _ROUTE_BY_STATE.get(TutorState(current), route_from_idle)
    return await router(state)
```

Graph build:
```python
graph.add_node(...)  # 7 nodes unchanged
graph.set_conditional_entry_point(
    route_entry,
    {"idle":"idle","teaching":"teaching","intervening":"intervening",
     "checking_in":"checking_in","quizzing":"quizzing","teach_back":"teach_back",
     "session_end":"session_end", END: END},
)
for node in ("idle","teaching","intervening","checking_in","quizzing","teach_back","session_end"):
    graph.add_edge(node, END)
```

`route_from_session_end` already returns `END` for non-reset events — keep as-is; `END` is in the path map.
Do NOT modify any guard function or node body. `TutorState(current)` — `current` may be a plain str from
Redis or a `TutorState`; `TutorState(...)` normalises both (StrEnum).

### dispatch_event

```python
config = {"configurable": {"thread_id": session_id}, "recursion_limit": 5}
```

### service.py — start_session

```python
async def start_session(session_id: str) -> None:
    """Drive the IDLE → TEACHING transition for a new session."""
    from app.modules.tutor.state_machine.graph import dispatch_event
    await dispatch_event(session_id, "session_start")
```

### websocket.py — delegate

`_handle_session_start` should call `from app.modules.tutor.service import start_session; await start_session(session_id)` inside its existing try/except (keep the error-swallow contract; existing tests patch
`app.modules.tutor.state_machine.graph.dispatch_event`, so B1/B2 still pass because `start_session`
calls that same `dispatch_event`). **Verify B1/B2 still pass** — if `start_session`'s lazy import breaks the
patch path, fall back to keeping the direct `dispatch_event` call in `_handle_session_start` and add
`start_session` to service.py as the canonical caller used elsewhere.

### Test patch targets (real-graph tests)

- `dispatch_event`/nodes lazy-import `get_redis` from `app.core.redis` → patch `app.core.redis.get_redis`
  with an `AsyncMock` whose `.get` returns the desired current state (or None for IDLE).
- For AC 2 persistence, assert `mock_redis.set` was awaited with `("tutor_state:{sid}", "TEACHING", ex=...)`.
- `@pytest.mark.unit`; `asyncio_mode = "auto"`.

### Out of scope

Filling the remaining Sprint 2 transitions/guards is NOT this story — only the topology fix that makes the
table work, plus the IDLE→TEACHING row, are in scope. The structure must leave the other `route_from_*`
intact so Sprint 2 extends the table.

---

## Review outcome (adversarial — Blind + Edge Case Hunter, 2026-06-29)

**Applied:**
- **[Major, both reviewers] Corrupt/stale Redis state crashed `dispatch_event`.** `route_entry` did
  `TutorState(current)` with no guard — a non-enum persisted value raised an uncaught `ValueError`
  (affecting the CES `distraction_detected` path too), and the `.get(..., route_from_idle)` fallback was
  dead. **Fixed:** wrapped in try/except → fall back to IDLE + log; added
  `test_corrupt_persisted_state_defaults_to_idle`.
- **[Major, Edge] `route_from_intervening` + non-IDLE/guarded transitions were untested** after the refactor
  changed their execution path. **Added** real-graph tests: INTERVENING→TEACHING, TEACHING+segment_complete
  →CHECKING_IN, TEACHING+distraction_detected (guarded)→INTERVENING, SESSION_END+session_reset→IDLE,
  SESSION_END+noop→END.
- **[Minor, Edge] `assert_any_call` didn't prove one transition.** **Added** `redis.set.call_count == 1`.

**AC4 deviation (intentional):** the story's literal "noop stays QUIZZING" is wrong against the existing
`route_from_quizzing` (defaults to `teaching`). Replaced with the stronger correct proof
`QUIZZING + quiz_failed → TEACH_BACK` (only reachable via the QUIZZING router).

**Flagged as follow-ups (not done here):**
- Full 14-transition matrix → Sprint 2 `all_transitions`.
- `_compiled_tutor_graph` is a module-global singleton sharing one `MemorySaver`; tests rely on distinct
  `session_id`s for isolation — latent hazard if a future test reuses an id.
