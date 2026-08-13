# Story 4-26 — Implement Tutor Router Endpoints (GET state + POST intervene)

**Status:** in-progress  
**Branch:** `sprint4/s4-26-tutor-router-impl`  
**Owner:** Dev 4  
**Sprint:** Sprint 4 (Weeks 8–9)  
**Priority:** High — demo-critical

---

## Context

`apps/api/app/modules/tutor/router.py` has two REST endpoints that have returned HTTP 501
since Sprint 0:

- `GET /api/tutor/session/{session_id}/state` — read the current FSM state and session
  counters from Redis.
- `POST /api/tutor/session/{session_id}/intervene` — dispatch a tutor intervention event
  through the LangGraph FSM (admin / test harness / demo use).

Both endpoints were scaffolded as deliberate stubs with "TODO Sprint 2" comments that were
never resolved through Sprints 2, 3, or 4.

**Demo impact:**  
`POST /intervene` is the only way to trigger a visible intervention overlay during a
scripted demo without live MediaPipe attention data (Dev 2 Sprint 3 — not yet built). It
makes the core HIE "intervention" feature demonstrable on demand. `GET /state` gives
admin visibility into the live FSM during a demo session.

---

## Acceptance Criteria

### GET /api/tutor/session/{session_id}/state

**AC1** — `GET /api/tutor/session/{session_id}/state` returns HTTP 200 with a
`TutorSessionState` JSON body when the session exists in Redis. All fields are populated
from Redis (not invented). Fields: `session_id`, `state`, `ces_score`,
`distraction_count`, `intervention_cooldown_remaining_seconds`, `fatigue_fired`.

**AC2** — When `tutor_state:{session_id}` does not exist in Redis, the endpoint returns
HTTP 404 with a clear `detail` message (not 200 with a null state or a 500).

**AC3** — The endpoint enforces JWT authentication via `CurrentUser`. An unauthenticated
request returns HTTP 401 (unchanged from the scaffold).

**AC4** — All Redis reads in the GET handler are individually fault-tolerant: a missing
key returns the field's zero-value (0 for counts, False for flags, 0.0 for CES), not a
500. A full Redis failure degrades to HTTP 503.

**AC5** — The `intervention_cooldown_remaining_seconds` field is computed as the Redis TTL
of `tutor_cooldown:{session_id}` (returns 0 when the key is absent — meaning no cooldown
active).

### POST /api/tutor/session/{session_id}/intervene

**AC6** — `POST /api/tutor/session/{session_id}/intervene` with a valid
`InterventionRequest` body dispatches the appropriate FSM event:
- `"distraction"` → dispatches `distraction_detected`
- `"fatigue"` → dispatches `fatigue_detected`
- `"confusion"` → dispatches `teachback_failed`

**AC7** — With `force=false` (default), the endpoint respects all guard rules from
`dispatch_event`: the cooldown, the distraction cap, and the fatigue-once flag. If a guard
blocks the dispatch, the endpoint returns HTTP 200 with `{"dispatched": false,
"reason": "<guard name>"}` — NOT a 4xx error (a blocked dispatch is not a client error).

**AC8** — With `force=true`, the endpoint bypasses the cooldown ONLY (not the distraction
cap or the fatigue-once flag). It does this by deleting `tutor_cooldown:{session_id}`
from Redis before calling `dispatch_event`. It does NOT bypass the distraction cap or
fatigue-once guard; those are safety invariants even in admin/demo mode.

**AC9** — The endpoint returns HTTP 404 when `tutor_state:{session_id}` does not exist in
Redis (no session to intervene in).

**AC10** — The endpoint returns HTTP 422 when `intervention_type` is not one of
`"distraction"`, `"fatigue"`, `"confusion"`. The `InterventionRequest` model enforces
this via a `Literal` type, not runtime string comparison.

**AC11** — The `POST /intervene` endpoint enforces JWT authentication via `CurrentUser`.

**AC12** — Both endpoints are exercised by unit tests using mocked Redis (no live Redis
required for CI). Tests use the real Pydantic models and real FastAPI test client — no
mocked HTTP responses.

---

## Dev Notes

### Implementation approach

**GET /state** — read six Redis keys in a pipeline:
```python
tutor_state:{session_id}            → str  (state name)
tutor_ces:{session_id}              → float (ces_score)
tutor_distraction_count:{session_id}→ int
tutor_fatigue_fired:{session_id}    → bool (exists = True)
tutor_cooldown:{session_id} TTL     → int seconds remaining
```
If `tutor_state:{session_id}` is missing → 404.

**POST /intervene** — dispatch map:
```python
_INTERVENTION_EVENT = {
    "distraction": "distraction_detected",
    "fatigue":     "fatigue_detected",
    "confusion":   "teachback_failed",
}
```

`dispatch_event` already handles all guard logic. The `force=true` path only removes the
TTL key before calling `dispatch_event` — it does not bypass the FSM's own routing guards.

**Intervention message delivery:** `dispatch_event` → `intervening_node` → sets
`intervention_message` on state → `process_attention_signal` delivers via WS. The REST
endpoint itself does NOT send a WS message — it delegates fully to the FSM and existing
delivery path. For the demo, calling `POST /intervene` will cause the `tutor_intervene` WS
message to be sent to the client automatically through the existing `service.py` delivery
path in `process_attention_signal`. However, this only works if the session is actively
sending attention signals. If no attention signals are coming in (no MediaPipe), the
delivery does NOT happen via this path — the FSM transitions but the WS message is not
sent. This is a known limitation for demo use: for a fully scripted demo, Dev 2 should
still send a synthetic attention signal after calling `POST /intervene`, OR the endpoint
should deliver the WS message directly (see Trade-off note below).

**Trade-off — WS delivery from POST /intervene:** To make the intervention visible in the
demo without attention signals, `POST /intervene` should also check if the FSM transitioned
to INTERVENING and directly call `manager.send(session_id, {type: "tutor_intervene", ...})`
after the dispatch. This mirrors what `process_attention_signal` does and is safe since
`manager.send` is fire-and-forget. Include this in AC6's implementation: if the result
state is INTERVENING and `intervention_message` is set, send the WS message.

**`InterventionRequest` validation:** change `intervention_type: str` to
`intervention_type: Literal["distraction", "fatigue", "confusion"]` — this closes a
pre-existing gap flagged in Story 4-14 (intervention_routing task notes, stored in tracker
as "⚠️ Flagged (pre-existing): admin `InterventionRequest.intervention_type` is an
unvalidated `str`").

**Lesson package for intervention_messages:** `dispatch_event` receives an
`intervention_messages` payload so `intervening_node` can select the message.
`POST /intervene` must fetch the cached lesson package from
`lesson_package:{session_id}` (Redis) and pass the current segment's
`interventions` in the payload, exactly as `process_attention_signal` does.
If the cache is missing (no lesson loaded), dispatch without messages — the intervention
still fires (FSM transitions to INTERVENING), but no overlay message is delivered. This
is a graceful degrade, not an error.

---

## Scale & Load

**Q1 — Unit of work and range:**  
One REST request reads 5 Redis keys (GET) or reads 1–2 keys + 1 optional delete +
1 `dispatch_event` call (POST). `dispatch_event` is one `MemorySaver` LangGraph run
(in-process, ~1–5 ms) plus 5–6 Redis writes. Upper bound: one request per demo trigger,
not per attention signal. Volume: negligible — admin/demo use only, not a hot path.

**Q2 — Fixed budgets vs variable input:**  
No variable-length inputs. Redis reads are all point lookups (O(1)). `dispatch_event`
is bounded by the FSM's `recursion_limit=5`. No silent truncation possible.

**Q3 — Scope of limits:**  
All Redis keys are per-session (scoped to `session_id`). No shared state across users.
`intervention_cooldown_remaining_seconds` reads a TTL — naturally bounded to
[0, `intervention_cooldown_seconds`] (default 120). Force-bypass deletes exactly one key.

**Q4 — Unbounded reads/writes:**  
None. GET reads 5 fixed keys. POST reads 1–2 fixed keys. All are `O(1)`.
`BOUNDED:` all reads are point lookups on known key patterns; no scans, no LRANGE.

**Q5 — Inherited caps:**  
`dispatch_event` already has `recursion_limit=5` (tripwire from Story 4-4). No new caps
introduced. `MemorySaver` is process-local and never evicted — the existing
per-attempt `thread_id` nonce in `dispatch_event` prevents cross-retry contamination.

**Q6 — Concurrent requests:**  
`GET /state` is read-only — fully concurrent-safe.  
`POST /intervene` with `force=true` deletes `tutor_cooldown:{session_id}` before
dispatching. Two concurrent `force=true` calls: both delete the same key (idempotent),
both call `dispatch_event`. `dispatch_event` itself is not atomic — two concurrent calls
could both dispatch `distraction_detected`, incrementing the distraction count twice. This
is acceptable for an admin/demo endpoint: the distraction cap (default 3) still bounds
total firings per session. A double-fire from concurrent admin calls is a documented
limitation, not a safety violation. `# BOUNDED:` distraction count capped at
`max_distraction_per_session` by the FSM guard.

---

## Out of scope

- WebSocket JWT authentication (separate security story, tracked in `fix/4-17-jwt-es256-verification`)
- Session ownership validation (verifying the JWT `sub` matches the session — deferred, same WS security story)
- `current_slide_index` and `last_intervention_type` fields in `TutorSessionState` — not persisted in Redis; return `None` (already in the model as optional)
