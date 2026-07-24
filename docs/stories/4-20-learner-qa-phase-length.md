---
baseline_commit: "a35ede1"
---

# Story 4-20: Learner Mode — Q&A Phase Length Enforced in State Machine

**Status:** done
**Priority:** Medium
**Sprint:** Learner Mode (Feature Sprint)

---

## Story

As the tutor state machine,
I need to enforce the tier-specific Q&A time limit (T1: 10 min, T2: 5 min, T3: 2.5 min) when the session is in QUIZZING state,
so that a student's quiz window is automatically bounded and the FSM auto-advances when the deadline passes.

---

## Context

- Story 4-19 seeds `session:{session_id}:qa_phase_seconds` in Redis on session start.
- The QUIZZING state (`quizzing_node` in `graph.py:214`) currently just persists the QUIZZING state — no time-bounding.
- There is no server-side periodic timer in this architecture (no Celery, no async background task per session). The natural trigger points for a deadline check are:
  - Each `advance_tutor_state` call from the client while in QUIZZING state.
  - Each `process_attention_signal` call (arrives every ~5 s from the client).
- The approach: `quizzing_node` records a `quiz_deadline_at` Unix timestamp in Redis. Any subsequent call that touches the session while it is QUIZZING checks whether the deadline has passed and, if so, auto-dispatches `quiz_complete` (timed-out, no penalty — never gate lesson progress on quiz score in MVP).
- **Do NOT** auto-dispatch `quiz_failed` on timeout — CLAUDE.md forbids gating progress. A timed-out quiz == `quiz_complete` with `quiz_accuracy = None`.

---

## Acceptance Criteria

- [x] **AC1:** When the FSM enters QUIZZING state, `quizzing_node` writes `session:{session_id}:quiz_deadline_at` as a Unix timestamp string (`int(time.time()) + qa_phase_seconds`, 24 h TTL). `qa_phase_seconds` is read from `session:{session_id}:qa_phase_seconds` (fallback: 300 — T2 default).
- [x] **AC2:** `advance_tutor_state` (in `service.py`) checks the deadline before dispatching any event while in QUIZZING state. If `time.time() > quiz_deadline_at`, it auto-dispatches `quiz_complete` instead of the client event, then returns.
- [x] **AC3:** `process_attention_signal` (in `service.py`) performs the same deadline check when `tutor_state:{session_id}` == `"QUIZZING"`. On deadline expiry, dispatches `quiz_complete` once (guarded by `redis.delete` on `quiz_deadline_at` before dispatch to prevent double-fire).
- [x] **AC4:** T1 (600 s), T2 (300 s), T3 (150 s) mappings are enforced end-to-end: unit test drives the REAL FSM with a synthetic Redis `qa_phase_seconds` value and a backdated `quiz_deadline_at`, confirms auto-`quiz_complete` fires.
- [x] **AC5:** A student who sends `quiz_complete` before the deadline is processed normally — no conflict with the auto-advance logic.
- [x] **AC6:** All 44 existing `test_tutor_graph.py` tests remain green. New tests: deadline-expired auto-advance; not-yet-expired no-op; missing `quiz_deadline_at` graceful fallback (no crash).

---

## Implementation Notes

### 1. `quizzing_node` — record deadline (`graph.py`)

```python
async def quizzing_node(state: TutorMachineState) -> TutorMachineState:
    session_id = state.get("session_id", "")
    logger.debug("[tutor:%s] → QUIZZING", session_id)
    await _persist_state(session_id, TutorState.QUIZZING)

    # Record tier-based Q&A deadline (best-effort; never crash the transition)
    try:
        import time as _time
        from app.core.redis import get_redis
        redis = get_redis()
        qa_raw = await redis.get(f"session:{session_id}:qa_phase_seconds")
        qa_secs = int(qa_raw) if qa_raw else 300  # T2 default
        deadline = int(_time.time()) + qa_secs
        await redis.set(f"session:{session_id}:quiz_deadline_at", str(deadline), ex=86400)
        logger.info("[tutor:%s] QUIZZING deadline set: +%ds", session_id, qa_secs)
    except Exception:
        logger.warning("[tutor:%s] quiz_deadline_at write failed — proceeding without deadline", session_id)

    return {**state, "current_state": TutorState.QUIZZING}
```

### 2. Deadline check helper (`service.py`)

```python
async def _quiz_deadline_expired(session_id: str, redis: Any) -> bool:
    """Return True if QUIZZING time limit has elapsed for this session."""
    import time as _time
    try:
        raw = await redis.get(f"session:{session_id}:quiz_deadline_at")
        if not raw:
            return False
        return _time.time() > float(raw)
    except Exception:
        return False  # degrade safely — never auto-advance on error
```

### 3. `advance_tutor_state` — deadline pre-check (`service.py`)

```python
async def advance_tutor_state(session_id: str, event: str) -> None:
    if event not in _CLIENT_DRIVABLE_EVENTS:
        raise ValueError(f"event not client-drivable: {event!r}")

    # NEW: deadline guard for QUIZZING sessions
    from app.core.redis import get_redis
    redis = get_redis()
    state_raw = await redis.get(f"tutor_state:{session_id}")
    if state_raw == "QUIZZING" and await _quiz_deadline_expired(session_id, redis):
        # Use delete-before-dispatch to prevent double-fire (atomic guard)
        deleted = await redis.delete(f"session:{session_id}:quiz_deadline_at")
        if deleted:
            logger.info("[tutor:%s] Q&A deadline expired — auto quiz_complete", session_id)
            from app.modules.tutor.state_machine.graph import dispatch_event
            await dispatch_event(session_id, "quiz_complete")
        return

    if event == "segment_complete":
        ...
```

### 4. `process_attention_signal` — deadline check (`service.py`)

Add after the CES history check block (before the `return CesResult`):

```python
# Learner Mode: auto-advance QUIZZING session on deadline expiry
from app.core.redis import get_redis as _get_redis
_redis = _get_redis()
_state = await _redis.get(f"tutor_state:{session_id}")
if _state == "QUIZZING" and await _quiz_deadline_expired(session_id, _redis):
    deleted = await _redis.delete(f"session:{session_id}:quiz_deadline_at")
    if deleted:
        logger.info("[tutor:%s] Q&A deadline expired via attention signal — auto quiz_complete", session_id)
        await dispatch_event(session_id, "quiz_complete")
```

### 5. Important constraints

- `time.time()` is used inside node/service functions (NOT in graph module-level scope — workflow scripts ban `Date.now()` but Python service code is fine).
- `redis.delete` before `dispatch_event` is the double-fire guard. Without it, two concurrent attention signals could both see an expired deadline and dispatch twice.
- Do NOT call `redis.get(f"tutor_state:{session_id}")` inside `quizzing_node` — the node already knows it's QUIZZING.

---

## Files to Change

| File | Change |
|------|--------|
| `apps/api/app/modules/tutor/state_machine/graph.py` | `quizzing_node` — record `quiz_deadline_at` |
| `apps/api/app/modules/tutor/service.py` | `_quiz_deadline_expired` helper; deadline pre-check in `advance_tutor_state`; deadline check in `process_attention_signal` |
| `apps/api/tests/test_tutor_graph.py` | New deadline tests (AC4, AC6) |
| `apps/api/tests/test_tutor_service.py` | Deadline-via-attention-signal tests (AC3, AC6) |

---

## Dependencies

- **Depends on:** Story 4-19 (`learner-tier-runtime`) — needs `session:{session_id}:qa_phase_seconds` in Redis.
- **Does NOT depend on:** Story 4-21 (`learner-ws-tier`) — tier already in Redis from 4-19.
- In tests: seed `session:{session_id}:qa_phase_seconds` directly in the Redis mock (do not depend on 4-19 running first in tests).

---

## Dev Agent Record

### Implementation Notes

- `quizzing_node` deadline write is wrapped in a bare `except Exception` so any Redis failure is silently absorbed and the FSM transition still completes.
- `_quiz_deadline_expired` similarly returns `False` on any error — ensures auto-advance degrades safely, never fires on a Redis blip.
- `advance_tutor_state` was restructured to call `get_redis()` unconditionally at the top (previously only called inside `if event == "segment_complete":"`). This is a behaviour change that required patching `get_redis` in `test_e1_flow_event_dispatches_to_fsm` (test_websocket_session.py) to avoid `RuntimeError: Redis pool is not initialised`.
- Double-fire guard: `redis.delete(quiz_deadline_at_key)` is atomic. Only the coroutine whose `delete` returns 1 dispatches `quiz_complete`. The second concurrent caller gets 0 and returns silently.
- `_attention_deadline_setup` test helper explicitly sets numeric `ces_weight_*` values on `mock_settings` to avoid Python 3.13 `TypeError: '<=' not supported between instances of 'MagicMock' and 'int'` inside `compute_ces`. The 13 pre-existing failures in `test_tutor_service.py` (from the older `_setup` helper) are **not** caused by this story and were left unchanged.
- `test_advance_tutor_state_expired_deadline_auto_quiz_complete` drives the **real** FSM (no `dispatch_event` mock), using a stateful Redis dict mock that updates `store[f"tutor_state:{sid}"]` on every `redis.set` call. After auto-dispatch of `quiz_complete`, `teaching_node` persists `TEACHING`, so the assertion checks `store["tutor_state:…"] == "TEACHING"`.

### Completion Notes

All 6 ACs satisfied. Test counts: `test_tutor_graph.py` 50/50 (44 original + 6 new), `test_websocket_session.py` 59/59, `test_tutor_service.py` 11 new tests green (13 pre-existing failures are out of scope and pre-date this story).

---

## File List

| File | Change |
|------|--------|
| `apps/api/app/modules/tutor/state_machine/graph.py` | `quizzing_node` — added `quiz_deadline_at` deadline write (best-effort, try/except) |
| `apps/api/app/modules/tutor/service.py` | Added `_quiz_deadline_expired` helper; added deadline pre-check in `advance_tutor_state`; added deadline check + double-fire guard in `process_attention_signal` |
| `apps/api/tests/test_tutor_graph.py` | Added `_deadline_redis` helper + 6 new deadline tests (AC1–AC5, AC6) |
| `apps/api/tests/test_tutor_service.py` | Added `_attention_deadline_setup` helper + 11 new tests for `_quiz_deadline_expired`, `advance_tutor_state` deadline, and `process_attention_signal` deadline paths |
| `apps/api/tests/test_websocket_session.py` | Patched `get_redis` in `test_e1_flow_event_dispatches_to_fsm` to unblock non-QUIZZING path (regression fix) |
| `docs/stories/4-20-learner-qa-phase-length.md` | Status → review; all AC checkboxes → [x]; Dev Agent Record + File List + Change Log added |

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-07-23 | Dev 4 (AI) | Initial implementation of Story 4-20 — all 6 ACs complete |
| 2026-07-23 | Dev 4 (AI) | 5-agent adversarial code review — 8 patches, 9 deferred, 5 dismissed |

---

## Senior Developer Review (AI)

**Date:** 2026-07-23
**Outcome:** Changes Requested — 8 patches required before merge

### Review Findings

**Patches (8 — must be resolved before merge):**

- [x] [Review][Patch] `quizzing_node` — add bounds check on `qa_phase_seconds` (clamp 30–3600 s) to prevent deadline backdating via a malicious Redis write setting it to 0 or negative [`apps/api/app/modules/tutor/state_machine/graph.py:228`]
- [x] [Review][Patch] Fix flawed mock in `test_advance_tutor_state_non_quizzing_state_normal_dispatch` — `redis.get = AsyncMock(return_value="TEACHING")` returns `"TEACHING"` for ALL keys including `quiz_deadline_at`, causing `float("TEACHING")` to raise inside `_quiz_deadline_expired` whose bare `except` then returns `False` — test passes for the wrong reason; replace with key-aware side_effect [`apps/api/tests/test_tutor_service.py`]
- [x] [Review][Patch] Add T3 (150 s) test for `quizzing_node` deadline write — AC1 explicitly names T1/T2/T3 but no test exercises `qa_secs="150"` [`apps/api/tests/test_tutor_graph.py`]
- [x] [Review][Patch] Add test: non-`quiz_complete` client event (e.g. `segment_complete`) submitted while QUIZZING + expired deadline → verifies `quiz_complete` is dispatched instead and original event is dropped (AC2 substitution guarantee is currently unproven) [`apps/api/tests/test_tutor_service.py`]
- [x] [Review][Patch] Add test: corrupt (non-numeric) `quiz_deadline_at` value in Redis → `_quiz_deadline_expired` returns `False` without raising [`apps/api/tests/test_tutor_service.py`]
- [x] [Review][Patch] Add assertion `result.intervention_dispatched is False` to `test_process_attention_quizzing_expired_deadline_dispatches_quiz_complete` [`apps/api/tests/test_tutor_service.py`]
- [x] [Review][Patch] Add test: QUIZZING + expired deadline + two consecutive below-threshold CES values simultaneously → only `quiz_complete` dispatched, not also `distraction_detected` (double-dispatch scenario) [`apps/api/tests/test_tutor_service.py`]
- [x] [Review][Patch] Add test: `quizzing_node` Redis failure during `quiz_deadline_at` write → exception caught, node still returns `current_state == QUIZZING` (best-effort branch) [`apps/api/tests/test_tutor_graph.py`]

**Deferred (pre-existing or deliberate MVP trade-offs):**

- [x] [Review][Defer] IDOR: `session_id` in Redis keys has no ownership check beyond JWT auth at WebSocket boundary [`service.py`] — deferred, pre-existing architecture
- [x] [Review][Defer] Forced state transition via Redis key injection (writing `quiz_deadline_at = 0`) — pre-existing Redis trust model; same exposure exists for all `session:*` keys [`service.py`] — deferred, pre-existing
- [x] [Review][Defer] TOCTOU cross-function race between `advance_tutor_state` and `process_attention_signal` — delete-before-dispatch is the intended atomic guard; inherent in async event-driven architecture — deferred, architectural
- [x] [Review][Defer] DoS via attention signal flooding deadline check — no new unauthenticated surface vs pre-existing pattern — deferred, pre-existing
- [x] [Review][Defer] Log injection via unescaped `session_id` in logger calls — JWT validates session_id at auth boundary; pre-existing log pattern throughout service — deferred, pre-existing
- [x] [Review][Defer] `quiz_deadline_at` 24h TTL does not couple to actual session lifetime — session_id reuse is a broader architecture question — deferred, pre-existing
- [x] [Review][Defer] 13 pre-existing `test_tutor_service.py` failures — documented in Dev Agent Record, out of scope — deferred, pre-existing
- [x] [Review][Defer] `baseline_commit` SHA retroactively set inside implementation commit — cannot retroactively fix; document in PR — deferred, acknowledged
- [x] [Review][Defer] Timed-out quiz (`quiz_accuracy=None`) indistinguishable from completed quiz in data layer — deliberate MVP trade-off per story Context section — deferred, deliberate MVP decision
