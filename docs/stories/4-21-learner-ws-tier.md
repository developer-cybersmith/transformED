---
baseline_commit: "a35ede1"
---

# Story 4-21: Learner Mode — Include Tier in WebSocket session-start Message

**Status:** ready-for-dev
**Priority:** Medium
**Sprint:** Learner Mode (Feature Sprint)

---

## Story

As the lesson player (frontend),
I need to send the student's learner tier in the `session_start` WebSocket message,
so that the backend can use the tier immediately even if the lesson package cache has not yet been populated (race condition between lesson generation and session start).

---

## Context

- `session_start` is a flat inbound control message currently handled in `websocket.py:_handle_session_start(session_id)`. The handler ignores the full payload — it only receives `session_id`.
- Today `ws.ts:ClientMessage` only contains `AttentionSignalMessage`. The `session_start` control message is intentionally outside the formal union (documented in `docs/ws-message-contract.md` as a "flat control message"). Adding `learner_tier` to the payload does NOT require amending the frozen `ws.ts ClientMessage` union — it is already off-contract. However, the team should document this in the next 4-dev `ws.ts` PR (the gaps (a)–(e) already flagged in Story 4-10).
- Story 4-19 seeds `session:{session_id}:learner_tier` from the lesson package cache. Story 4-21 is the WS-based override: if the client sends `learner_tier` in `session_start`, it OVERWRITES whatever 4-19 wrote. This is correct because the client has fresher student-profile data.
- Priority: this is a fallback/override path. Story 4-19 is primary; Story 4-21 handles the race where the lesson package cache isn't ready yet or the client has a more up-to-date tier.

---

## Acceptance Criteria

- [ ] **AC1:** `websocket.py:_handle_session_start` is updated to accept the full `payload` dict (instead of just `session_id`). It extracts `payload.get("learner_tier")` (optional string).
- [ ] **AC2:** If `learner_tier` is present and is one of `"T1"`, `"T2"`, `"T3"`, write `session:{session_id}:learner_tier` and `session:{session_id}:qa_phase_seconds` to Redis (same keys as Story 4-19, same TTL). This OVERWRITES 4-19's value.
- [ ] **AC3:** If `learner_tier` is absent, `None`, or an unrecognised value, no Redis write is made for the tier keys (4-19's value, if present, is preserved).
- [ ] **AC4:** `docs/ws-message-contract.md` is updated — the `session_start` inbound entry gains `learner_tier?: "T1" | "T2" | "T3"` as an optional field.
- [ ] **AC5:** Unit tests: valid tier T1/T2/T3 → correct Redis write; absent tier → no write; invalid string → no write; Redis failure → no crash.
- [ ] **AC6:** Existing tests for `session_start` dispatch (Story 4-4, 4-18 tests covering `dispatch_event` IDLE→TEACHING) remain green.

---

## Implementation Notes

### 1. Change to `_handle_session_start` (`websocket.py`)

**Current signature:**
```python
async def _handle_session_start(session_id: str) -> None:
```

**New signature + body addition:**

```python
async def _handle_session_start(session_id: str, payload: dict[str, Any] | None = None) -> None:
    """Dispatch session_start event and optionally seed learner tier from WS payload."""
    # Tier seeding from WS payload (override path — 4-19 seeds from lesson package)
    tier = (payload or {}).get("learner_tier")
    if isinstance(tier, str) and tier in {"T1", "T2", "T3"}:
        try:
            from app.core.redis import get_redis
            from app.modules.tutor.service import qa_phase_seconds as _qa
            redis = get_redis()
            await redis.set(f"session:{session_id}:learner_tier", tier, ex=86400)
            await redis.set(f"session:{session_id}:qa_phase_seconds", str(_qa(tier)), ex=86400)
            logger.info("[tutor:%s] learner_tier=%s from session_start WS message", session_id, tier)
        except Exception:
            logger.warning("learner tier WS seeding failed for %s", session_id)

    # Existing: drive IDLE → TEACHING
    try:
        from app.modules.tutor.service import start_session
        await start_session(session_id)
        logger.info("[tutor:%s] session_start dispatched → TEACHING", session_id)
    except Exception:
        logger.exception("session_start dispatch failed for %s", session_id)
```

### 2. Update the call site in `websocket_endpoint` (`websocket.py`)

**Current:**
```python
elif msg_type == "session_start":
    await _handle_session_start(session_id)
```

**New:**
```python
elif msg_type == "session_start":
    await _handle_session_start(session_id, payload=payload)
```

`payload` is the already-decoded dict from `json.loads(raw)` — no re-parse needed.

### 3. `docs/ws-message-contract.md` update

Add `learner_tier` to the `session_start` inbound message section:

```
| session_start | Control | { type: "session_start", learner_tier?: "T1" | "T2" | "T3" } |
```

Note: "Off-contract (not in ws.ts ClientMessage union). Tier is optional — absent means 'use lesson package value or T2 default'."

### 4. What NOT to change

- `packages/shared/types/ws.ts` — `session_start` is NOT in `ClientMessage`. No change needed here for this story. When the team opens the gaps (a)–(e) PR from Story 4-10, the proposer can add `session_start` to a `ControlMessage` union at that time.
- `app/modules/tutor/service.py::start_session` — no change; it still just dispatches `session_start` event to the FSM.
- `app/modules/tutor/state_machine/graph.py` — not touched.

### 5. Redis precedence rule (document in code comment)

Story 4-19 runs in `_init_session_state` (on `connect()`). Story 4-21 runs in `_handle_session_start` (on `session_start` message, which arrives after the connection is established). Therefore 4-21 always runs AFTER 4-19 for a given session — the WS-payload tier naturally overwrites the lesson-package tier, which is the desired behaviour (client is authoritative for the student's tier).

---

## Files to Change

| File | Change |
|------|--------|
| `apps/api/app/core/websocket.py` | `_handle_session_start` signature + tier seeding; call site passes `payload` |
| `docs/ws-message-contract.md` | Add `learner_tier?` to `session_start` entry |
| `apps/api/tests/test_websocket_session.py` | New AC1–AC5 tests |

---

## Dependencies

- **Depends on (runtime):** Story 4-19 — `qa_phase_seconds()` helper must exist in `service.py`.
- **Can be tested independently:** seed `session:{session_id}:qa_phase_seconds` directly in Redis mock if 4-19 is not yet merged.
- **Does NOT block:** Story 4-20 — the FSM tier enforcement only reads the Redis key; it doesn't care which story wrote it.
