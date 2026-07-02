---
status: in-progress
baseline_commit: 9d2e480
---

# Story 3-20 — Analytics Events Ingestion Live (POST /api/analytics/events)

**Epic:** 3 — Assessment, CES & Analytics  
**Sprint:** 2 (Week 4–5)  
**Story number:** 3-20  
**Dev:** Dev 3 (tannmayygupta)  
**Priority:** High  

---

## User Story

As a **student using the TransformED lesson player**, I want **my in-session behavioral events (jargon lookups, tab switches, lesson segments completed, etc.) to be persisted automatically**, so that **my tutor state machine and post-session reports have accurate behavioral data**.

---

## Background & Context

The analytics router (`apps/api/app/modules/analytics/router.py`) has a `POST /events` endpoint that was scaffolded in Sprint 0 as a 501 stub. The `session_events` table already exists in the applied migration `20260611000000_initial_schema.sql` with columns: `id uuid PK`, `session_id uuid FK`, `event_type text`, `payload jsonb`, `created_at timestamptz`. There is no `client_timestamp_ms` or `user_id` column — the client timestamp must be merged into the `payload` JSONB under key `"_client_ts_ms"`.

Dev 4's tutor state machine fires events like `jargon_hover`, `tab_switch`, `segment_complete` to this endpoint. Dev 2's player fires `session_start`, `session_end`, `quiz_skip`, `teachback_skip`. All must be persisted in a single bulk insert per batch request.

An unrelated regression was introduced when Story 3-18 (Onboarding) was implemented: `test_onboarding_endpoint_returns_501` in `test_assessment_stub_contracts.py` now fails because the onboarding endpoint is live (returns 422 on bad input, not 501). That test must be fixed as part of this story.

---

## Acceptance Criteria

### AC 1 — HTTP 202 with ingested count
`POST /api/analytics/events` with a valid authenticated batch of N events returns HTTP 202 with body `{"ingested": N}`.

### AC 2 — jargon_hover event persisted correctly
A `jargon_hover` event with `payload: {"term": "homeostasis", "segment_id": "s-01"}` writes a row to `session_events` with:
- `event_type = "jargon_hover"`
- `payload.term = "homeostasis"` and `payload.segment_id = "s-01"`

### AC 3 — client_timestamp_ms stored in payload JSONB
`client_timestamp_ms` from each event is merged into the stored row's `payload` JSONB under key `"_client_ts_ms"`. No separate DB column is used. The original event-specific payload keys are preserved alongside `"_client_ts_ms"`.

### AC 4 — Empty events list rejected
`POST /api/analytics/events` with `events: []` returns HTTP 422 (Pydantic `min_length=1`). No DB call is made.

### AC 5 — Oversized batch rejected
`POST /api/analytics/events` with `events` containing 101 or more items returns HTTP 422 (Pydantic `max_length=100`). No DB call is made.

### AC 6 — Negative client_timestamp_ms rejected
`POST /api/analytics/events` with `client_timestamp_ms: -1` returns HTTP 422 (Pydantic `Field(ge=0)`). No DB call is made.

### AC 7 — Cross-user session rejected (403)
If ANY event in the batch references a `session_id` that belongs to a DIFFERENT authenticated user, the entire batch is rejected with HTTP 403 and zero rows are written to `session_events`. The 403 detail must be `"One or more sessions not found or access denied."`.

### AC 8 — Non-existent session rejected (403)
If ANY event in the batch references a `session_id` that does NOT exist in the `sessions` table, the entire batch is rejected with HTTP 403. The detail must be identical to AC 7: `"One or more sessions not found or access denied."`. This prevents session ID enumeration (an attacker cannot distinguish "session not found" from "session owned by another user").

### AC 9 — Single bulk insert for entire batch
All N events in a valid, authorized batch are written via a SINGLE bulk insert call to `session_events` (one `supabase.table("session_events").insert(rows)` call). There must NOT be N separate insert calls.

### AC 10 — Unknown event_type accepted (soft validation)
An event with an unrecognised `event_type` (e.g., `"custom_event_xyz"`) is accepted, written to `session_events`, and the service logs a `WARNING` containing the unknown type. The response is still HTTP 202. The endpoint NEVER rejects unknown event types.

### AC 11 — 9 known event types documented in Field description
`AnalyticsEvent.event_type` Field description lists the 9 known types: `tab_switch`, `retry_after_fail`, `jargon_hover`, `quiz_skip`, `teachback_skip`, `intervention_acknowledged`, `segment_complete`, `session_start`, `session_end`. The description also states that unknown types are accepted (not rejected).

### AC 12 — HTTP 500 on insert failure
If the bulk insert returns a truthy `.error` attribute (simulating a DB failure), the endpoint returns HTTP 500 with detail `"Failed to persist analytics events."` and logs the error with safe sanitisation (newlines stripped from the error string).

### AC 13 — All Supabase calls wrapped in asyncio.to_thread
All synchronous supabase-py v2 calls in the service layer (`sessions` ownership query and `session_events` bulk insert) must be wrapped in `asyncio.to_thread`. Direct synchronous calls in an async function are prohibited.

### AC 14 — Unauthenticated requests rejected
A request without a valid JWT returns HTTP 401 or 403 (handled by the `CurrentUser` dependency, consistent with all other assessment endpoints). No business logic is executed.

### AC 15 — No LLM calls
There are zero LLM calls in the analytics event ingest flow. This endpoint is a pure DB write operation.

### AC 16 — Broken stub test fixed
`test_onboarding_endpoint_returns_501` in `apps/api/tests/test_assessment_stub_contracts.py` is renamed to `test_onboarding_endpoint_is_live_not_501` and updated to assert that the onboarding endpoint does NOT return 501 (mirroring the pattern of `test_teachback_endpoint_is_live_not_501` and `test_report_endpoint_is_live_not_501`). The docstring must explain why: onboarding was implemented in Story 3-18.

### AC 17 — Analytics stub contract test added
A new test `test_analytics_events_endpoint_is_live_not_501` is added to `test_assessment_stub_contracts.py` (or a new `test_analytics_stub_contracts.py`) that verifies `POST /api/analytics/events` does NOT return 501 after this story is implemented.

---

## Tasks / Subtasks

- [x] Task 0: Branch created (`dev3-sprint2-task3` from `9d2e480`)
- [x] Task 1: Story file created and committed before any code (BMAD gate)

- [ ] Task 2: Fix broken stub test (AC 16)
  - [ ] 2.1 Rename `test_onboarding_endpoint_returns_501` → `test_onboarding_endpoint_is_live_not_501`
  - [ ] 2.2 Update docstring and assertion to match `test_report_endpoint_is_live_not_501` pattern
  - [ ] 2.3 Run: `pytest tests/test_assessment_stub_contracts.py -v` — confirm 0 failures

- [ ] Task 3: Update `AnalyticsEvent` schema in router.py (ACs 6, 11)
  - [ ] 3.1 Add `Field(ge=0)` to `client_timestamp_ms`
  - [ ] 3.2 Update `event_type` Field description to list 9 known types (AC 11)
  - [ ] 3.3 Update router docstring (remove "head_pose/blink_rate" references — those are the old stub description)

- [ ] Task 4: Write failing tests (RED phase) — new file `apps/api/tests/test_analytics_events_endpoint.py`
  - [ ] 4.1 Test fixture: `_build_events_supabase()` mock factory using call-order capture pattern
  - [ ] 4.2 `test_202_single_event_returns_ingested_1` — AC 1
  - [ ] 4.3 `test_202_batch_of_three_returns_ingested_3` — AC 1
  - [ ] 4.4 `test_jargon_hover_event_payload_correct` — AC 2
  - [ ] 4.5 `test_client_timestamp_stored_as_client_ts_ms_in_payload` — AC 3
  - [ ] 4.6 `test_empty_events_list_returns_422` — AC 4
  - [ ] 4.7 `test_101_events_returns_422` — AC 5
  - [ ] 4.8 `test_negative_client_timestamp_returns_422` — AC 6
  - [ ] 4.9 `test_403_when_session_belongs_to_different_user` — AC 7
  - [ ] 4.10 `test_403_when_session_does_not_exist` — AC 8
  - [ ] 4.11 `test_403_detail_is_identical_for_missing_and_wrong_user_sessions` — AC 8 (no enumeration oracle)
  - [ ] 4.12 `test_single_bulk_insert_call_not_per_event` — AC 9
  - [ ] 4.13 `test_unknown_event_type_accepted_returns_202` — AC 10
  - [ ] 4.14 `test_unknown_event_type_logs_warning` — AC 10
  - [ ] 4.15 `test_500_on_insert_error` — AC 12
  - [ ] 4.16 `test_all_9_known_event_types_accepted` — AC 10/11
  - [ ] 4.17 `test_client_ts_ms_merged_alongside_existing_payload_keys` — AC 3
  - [ ] 4.18 `test_mixed_valid_invalid_session_batch_fully_rejected` — AC 7 (partial batch still fails)
  - [ ] 4.19 `test_ownership_check_uses_asyncio_to_thread` — AC 13
  - [ ] 4.20 `test_insert_uses_asyncio_to_thread` — AC 13
  - [ ] 4.21 `test_analytics_events_endpoint_is_live_not_501` — AC 17

- [ ] Task 5: Create `apps/api/app/modules/analytics/service.py` (GREEN phase)
  - [ ] 5.1 `KNOWN_EVENT_TYPES = frozenset({9 types})`
  - [ ] 5.2 `async def ingest_events(*, events, user_id, supabase) -> dict[str, int]`
  - [ ] 5.3 Ownership check: single `.in_("session_id", session_ids).eq("user_id", user_id)` query via `asyncio.to_thread`
  - [ ] 5.4 Raise HTTP 403 if `authorized_ids != requested_ids` (both missing and wrong-user paths)
  - [ ] 5.5 Log WARNING for each event with unknown event_type
  - [ ] 5.6 Build rows: `{"session_id": e.session_id, "event_type": e.event_type, "payload": {**e.payload, "_client_ts_ms": e.client_timestamp_ms}}`
  - [ ] 5.7 Single bulk insert via `asyncio.to_thread`
  - [ ] 5.8 Raise HTTP 500 with sanitized log if `insert_resp.error` is truthy
  - [ ] 5.9 Return `{"ingested": len(rows)}`

- [ ] Task 6: Update `apps/api/app/modules/analytics/router.py` to call service (GREEN phase)
  - [ ] 6.1 Replace 501 stub in `ingest_events` with lazy imports and call to `_ingest_events`
  - [ ] 6.2 Update docstring to remove "analytics_events" reference (table is `session_events`)

- [ ] Task 7: Run full test suite (verify GREEN + no regressions)
  - [ ] 7.1 `pytest tests/test_analytics_events_endpoint.py -v` — all pass
  - [ ] 7.2 `pytest tests/test_assessment_stub_contracts.py -v` — all pass (AC 16 fix confirmed)
  - [ ] 7.3 `pytest -m unit -v` — 0 failures, 0 regressions

- [ ] Task 8: Tracker update
  - [ ] 8.1 Mark Sprint 2 Task 3 done in `docs/dev3-assessment-tracker.md`
  - [ ] 8.2 Update Quick Status Dashboard

---

## Technical Notes

### session_events table (from applied migration `20260611000000_initial_schema.sql`)
```sql
CREATE TABLE public.session_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  uuid NOT NULL REFERENCES public.sessions(session_id) ON DELETE CASCADE,
  event_type  text NOT NULL,
  payload     jsonb NOT NULL DEFAULT '{}',
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON public.session_events(session_id);
CREATE INDEX ON public.session_events(event_type);
```
There is no `client_timestamp_ms` or `user_id` column. Client timestamp MUST go into payload JSONB as `"_client_ts_ms"`. No migration needed.

### sessions table (ownership check)
```sql
CREATE TABLE public.sessions (
  session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES public.users(id),
  lesson_id   uuid NOT NULL REFERENCES public.lessons(id),
  ces_final   numeric(5,2),
  started_at  timestamptz NOT NULL DEFAULT now(),
  ended_at    timestamptz
);
```

### Ownership check query pattern
```python
session_ids = list({e.session_id for e in events})
resp = await asyncio.to_thread(
    lambda: supabase.table("sessions")
    .select("session_id")
    .in_("session_id", session_ids)
    .eq("user_id", user_id)
    .execute()
)
authorized_ids = {str(r["session_id"]) for r in (resp.data or [])}
if authorized_ids != {str(s) for s in session_ids}:
    raise HTTPException(status_code=403, detail="One or more sessions not found or access denied.")
```

### Test mock factory pattern (from test_session_report_endpoint.py)
Use call-order capture (`mock._captured_mocks[n]`) to verify arguments passed to supabase table calls:
```python
def _build_events_supabase(*, sessions_data, insert_error=None):
    mock = MagicMock()
    captured = {}
    call_count = 0
    def table_side_effect(name):
        nonlocal call_count
        t = MagicMock()
        captured[call_count] = {"table": name, "mock": t}
        call_count += 1
        # wire up chain for sessions query
        # wire up chain for session_events insert
        ...
    mock.table.side_effect = table_side_effect
    mock._captured_mocks = captured
    return mock
```

### Soft validation pattern
Log WARNING for unknown event types — never reject them:
```python
for event in events:
    if event.event_type not in KNOWN_EVENT_TYPES:
        logger.warning(
            "analytics: unknown event_type=%r session=%s user=%s",
            event.event_type, event.session_id, user_id
        )
```

### SEC pattern — identical 403 detail for missing and wrong-user sessions
Both "session not found" and "session owned by another user" return the same HTTP 403 with detail `"One or more sessions not found or access denied."`. This prevents an enumeration oracle where an attacker could determine if a session_id exists by observing different response messages.

### Lazy import pattern (no circular import)
```python
@router.post("/events", status_code=202)
async def ingest_events(body: BatchEventsRequest, current_user: CurrentUser):
    from app.core.db import get_supabase
    from app.modules.analytics.service import ingest_events as _ingest_events
    return await _ingest_events(
        events=body.events,
        user_id=current_user["sub"],
        supabase=get_supabase(),
    )
```

### Files to modify/create
| File | Action |
|------|--------|
| `apps/api/app/modules/analytics/service.py` | CREATE (new) |
| `apps/api/app/modules/analytics/router.py` | UPDATE (replace stub, update schema) |
| `apps/api/tests/test_analytics_events_endpoint.py` | CREATE (new, ~21 tests) |
| `apps/api/tests/test_assessment_stub_contracts.py` | UPDATE (fix broken test, add analytics contract test) |
| `docs/dev3-assessment-tracker.md` | UPDATE (mark Task 3 done) |

No new migrations required. No changes to `packages/shared/`. No changes to `supabase/migrations/`.

---

## Dev Agent Record

### Debug Log
_To be filled during implementation_

### Completion Notes
_To be filled on completion_

### File List
_To be filled on completion_

### Change Log
- 2026-07-02: Story created (story-first BMAD gate)

---

## Senior Developer Review (AI)

_To be filled after bmad-code-review_
