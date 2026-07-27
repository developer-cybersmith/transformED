---
baseline_commit: "a35ede1"
---

# Story 4-20: Learner Mode — Q&A Phase Length Enforced in State Machine

**Status:** ready-for-dev
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

- [ ] **AC1:** When the FSM enters QUIZZING state, `quizzing_node` writes `session:{session_id}:quiz_deadline_at` as a Unix timestamp string (`int(time.time()) + qa_phase_seconds`, 24 h TTL). `qa_phase_seconds` is read from `session:{session_id}:qa_phase_seconds` (fallback: 300 — T2 default).
- [ ] **AC2:** `advance_tutor_state` (in `service.py`) checks the deadline before dispatching any event while in QUIZZING state. If `time.time() > quiz_deadline_at`, it auto-dispatches `quiz_complete` instead of the client event, then returns.
- [ ] **AC3:** `process_attention_signal` (in `service.py`) performs the same deadline check when `tutor_state:{session_id}` == `"QUIZZING"`. On deadline expiry, dispatches `quiz_complete` once (guarded by `redis.delete` on `quiz_deadline_at` before dispatch to prevent double-fire).
- [ ] **AC4:** T1 (600 s), T2 (300 s), T3 (150 s) mappings are enforced end-to-end: unit test drives the REAL FSM with a synthetic Redis `qa_phase_seconds` value and a backdated `quiz_deadline_at`, confirms auto-`quiz_complete` fires.
- [ ] **AC5:** A student who sends `quiz_complete` before the deadline is processed normally — no conflict with the auto-advance logic.
- [ ] **AC6:** All 44 existing `test_tutor_graph.py` tests remain green. New tests: deadline-expired auto-advance; not-yet-expired no-op; missing `quiz_deadline_at` graceful fallback (no crash).

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
