---
baseline_commit: "a35ede1"
---

# Story 4-21: Learner Mode — Include Tier in WebSocket session-start Message

**Status:** done
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

- [x] **AC1:** `websocket.py:_handle_session_start` is updated to accept the full `payload` dict (instead of just `session_id`). It extracts `payload.get("learner_tier")` (optional string).
- [x] **AC2:** If `learner_tier` is present and is one of `"T1"`, `"T2"`, `"T3"`, write `session:{session_id}:learner_tier` and `session:{session_id}:qa_phase_seconds` to Redis (same keys as Story 4-19, same TTL). This OVERWRITES 4-19's value.
- [x] **AC3:** If `learner_tier` is absent, `None`, or an unrecognised value, no Redis write is made for the tier keys (4-19's value, if present, is preserved).
- [x] **AC4:** `docs/ws-message-contract.md` is updated — the `session_start` inbound entry gains `learner_tier?: "T1" | "T2" | "T3"` as an optional field.
- [x] **AC5:** Unit tests: valid tier T1/T2/T3 → correct Redis write; absent tier → no write; invalid string → no write; Redis failure → no crash.
- [x] **AC6:** Existing tests for `session_start` dispatch (Story 4-4, 4-18 tests covering `dispatch_event` IDLE→TEACHING) remain green.

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

---

## Dev Agent Record

### Implementation Plan
Red-green-refactor on the tutor WS boundary:
1. **RED** — added `Group H` (16 cases) to `apps/api/tests/test_websocket_session.py` covering AC1–AC6; confirmed they fail on the old `_handle_session_start(session_id)` signature (`TypeError: unexpected keyword argument 'payload'`).
2. **GREEN** — widened `_handle_session_start` to `(session_id, payload=None)` and added a best-effort tier-override block that runs *before* the FSM dispatch; updated the `websocket_endpoint` call site to pass the already-decoded `payload`.
3. **REFACTOR** — reused the existing module-level `_VALID_TIERS` allowlist and the Story 4-19 `qa_phase_seconds()` helper; kept the never-raise error contract identical to `_handle_attention_signal` / `_seed_learner_tier`.

### Completion Notes
- **Precedence is guaranteed by lifecycle order, not locking:** 4-19 seeds on `connect()`; 4-21 runs on the later `session_start` message, so the WS-payload tier naturally overwrites the lesson-package tier (client is authoritative). Documented in the handler docstring.
- **Security:** tier is validated with `isinstance(tier, str) and tier in _VALID_TIERS` *before* any Redis write — a non-string (list/int) or unrecognised string writes nothing (tested in h5/h6). `session_id` is already UUID-validated at the route boundary (`_SESSION_ID_RE`), so no key-namespace traversal via this path.
- **Error contract:** a Redis failure during seeding is swallowed (logged `warning`) and the IDLE→TEACHING dispatch still fires (h7) — tier seeding can never break session start.
- **AC6 / backward compatibility:** the `payload` param defaults to `None`, so the original single-arg call sites (Story 4-4/4-18 tests b1/b2) keep working unchanged — verified green.
- **Implementation choice vs. Story 4-19 (updated post-review):** the initial draft used two plain `redis.set` calls per the story's prescribed snippet. Code review (2026-07-23) flagged this as a torn-write risk that contradicts 4-19's deliberate pipeline atomicity for these same keys. **Now aligned:** both tier keys are written via a single `redis.pipeline(transaction=False)` + `execute()`, matching `_seed_learner_tier`.
- **Multi-connection precedence (post-review):** the "WS tier always wins" guarantee holds only per-connection, not across concurrent connections (desktop+mobile) where a second connection's 4-19 re-seed can revert the override. Accepted as last-writer-wins (bounded impact — tier only tunes Q&A duration); docstring corrected and writer-coordination deferred.
- **Test suite:** `tests/test_websocket_session.py` → **58 passed** (42 pre-existing + 16 new). The wider `tests/` collection errors (`test_tutor_service.py`, endpoint tests) are **pre-existing environmental issues** — missing `langfuse_secret_key` env var and the `jsonschema` package — not caused by this change (which touches only `websocket.py`).

### File List
| File | Change |
|------|--------|
| `apps/api/app/core/websocket.py` | `_handle_session_start` now accepts `payload`; seeds learner tier (override path) before FSM dispatch; call site passes `payload` |
| `docs/ws-message-contract.md` | `session_start` inbound entry + example gain optional `learner_tier?`; gap (a) note; date bump |
| `apps/api/tests/test_websocket_session.py` | New Group H (16 tests) covering AC1–AC6 |

### Change Log
| Date | Change |
|------|--------|
| 2026-07-23 | Story 4-21 implemented — WS `session_start` learner-tier override path; 16 unit tests added; ws-message-contract doc updated. Status → review. |
| 2026-07-23 | Code review (3-layer adversarial + acceptance): 1 patch + 1 decision resolved, 2 deferred, 5 dismissed. Tier keys now written atomically via pipeline (torn-write fix); docstring corrected for multi-connection last-writer-wins; `test_h8` regression guard added (17 tests, 59 total green). |

---

## Senior Developer Review (AI)

**Reviewed:** 2026-07-23 · **Mode:** full (spec-backed) · **Layers:** Blind Hunter, Edge Case Hunter, Acceptance Auditor (5-agent gate: + Story Quality + Process Integrity via this workflow)
**Outcome:** Changes Requested — 1 patch, 1 decision, 2 deferred, 5 dismissed. All 6 ACs verified met by the Acceptance Auditor.

### Review Findings

- [x] [Review][Decision→Resolved] Concurrent-connection precedence race between 4-19 seed and 4-21 override [apps/api/app/core/websocket.py] — The docstring's "4-21 always runs after 4-19" holds per-connection (connect() is awaited before the receive loop), but NOT across the multi-connection model the manager supports (mobile+desktop). A second/reconnecting connection's `_seed_learner_tier` (4-19, from lesson package) can land after connection A's `session_start` override (4-21), silently reverting the client-authoritative tier. **Resolution (user, 2026-07-23): accept last-writer-wins** — impact is bounded (tier only tunes Q&A-phase duration, no data/access exposure) and drift self-heals on the next `session_start`. Applied: corrected the overstated docstring guarantee + added a multi-connection caveat comment; logged writer-coordination as deferred work.
- [x] [Review][Patch] Non-atomic two-key tier write (torn write) [apps/api/app/core/websocket.py] — **FIXED.** Both `session:{sid}:learner_tier` and `session:{sid}:qa_phase_seconds` are now written through a single `redis.pipeline(transaction=False)` + `await pipe.execute()`, matching Story 4-19's `_seed_learner_tier` atomicity invariant. Group H tests migrated to the pipeline assertion pattern; added `test_h8` as a regression guard proving a single atomic commit (no direct `redis.set`).
- [x] [Review][Defer] Repeated session_start re-overrides tier mid-session (no idempotency guard) [apps/api/app/core/websocket.py] — deferred, low severity
- [x] [Review][Defer] No observability when a present-but-invalid tier is rejected (silent fall-through) [apps/api/app/core/websocket.py:320] — deferred, low severity

### Dismissed (noise / by-design / pre-existing)
- Client-authoritative tier override (Blind Hunter, High) — explicitly by-design per Story Context; tier only tunes the Q&A window duration, not data access. No privilege escalation.
- Non-dict payload `AttributeError` at the new `.get()` — unreachable: the router's `payload.get("type")` crashes first for a non-dict body, and that teardown is already documented in `ws-message-contract.md`.
- Silent-swallow of Redis errors — this IS the required AC5 error contract (Redis failure must never crash session start); consistent with `_seed_learner_tier` / `_init_session_state`.
- Fixed 24h TTL with no refresh — consistent with 4-19 and the entire file (`ex=86400`); pre-existing design.
