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

### AC 3a — Reserved `_client_ts_ms` key overwrite behavior
If the incoming `payload` dict already contains the key `"_client_ts_ms"`, the value from the `client_timestamp_ms` field MUST overwrite it. The client-supplied `_client_ts_ms` value in payload is silently discarded; no error is raised. This ensures the server-authoritative timestamp always wins.

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

- [x] Task 2: Fix broken stub test (AC 16)
  - [x] 2.1 Rename `test_onboarding_endpoint_returns_501` → `test_onboarding_endpoint_is_live_not_501`
  - [x] 2.2 Update docstring and assertion to match `test_report_endpoint_is_live_not_501` pattern
  - [x] 2.3 Run: `pytest tests/test_assessment_stub_contracts.py -v` — 9/9 PASS

- [x] Task 3: Update `AnalyticsEvent` schema in router.py (ACs 6, 11)
  - [x] 3.1 Add `Field(ge=0)` to `client_timestamp_ms`
  - [x] 3.2 Update `event_type` Field description to list 9 known types (AC 11)
  - [x] 3.3 Update router docstring (removed "head_pose/blink_rate" references)

- [x] Task 4: Write failing tests (RED phase) — new file `apps/api/tests/test_analytics_events_endpoint.py`
  - [x] 4.1 Test fixture: `_build_events_supabase()` mock factory using call-order capture pattern
  - [x] 4.2 `test_202_single_event_returns_ingested_1` — AC 1
  - [x] 4.3 `test_202_batch_of_three_returns_ingested_3` — AC 1
  - [x] 4.4 `test_jargon_hover_event_payload_correct` — AC 2
  - [x] 4.5 `test_client_timestamp_stored_as_client_ts_ms_in_payload` — AC 3
  - [x] 4.6 `test_empty_events_list_returns_422` — AC 4
  - [x] 4.7 `test_101_events_returns_422` — AC 5
  - [x] 4.8 `test_negative_client_timestamp_returns_422` — AC 6
  - [x] 4.9 `test_403_when_session_belongs_to_different_user` — AC 7
  - [x] 4.10 `test_403_when_session_does_not_exist` — AC 8
  - [x] 4.11 `test_403_detail_is_identical_for_missing_and_wrong_user_sessions` — AC 8 (no enumeration oracle)
  - [x] 4.12 `test_single_bulk_insert_call_not_per_event` — AC 9
  - [x] 4.13 `test_unknown_event_type_accepted_returns_202` — AC 10
  - [x] 4.14 `test_unknown_event_type_logs_warning` — AC 10
  - [x] 4.15 `test_500_on_insert_error` — AC 12
  - [x] 4.16 `test_all_9_known_event_types_accepted` — AC 10/11
  - [x] 4.17 `test_client_ts_ms_merged_alongside_existing_payload_keys` — AC 3
  - [x] 4.18 `test_mixed_valid_invalid_session_batch_fully_rejected` — AC 7 (partial batch still fails)
  - [x] 4.19 `test_ownership_check_uses_asyncio_to_thread` — AC 13
  - [x] 4.20 `test_insert_uses_asyncio_to_thread` — AC 13
  - [x] 4.21 `test_analytics_events_endpoint_is_live_not_501` — AC 17

- [x] Task 5: Create `apps/api/app/modules/analytics/service.py` (GREEN phase)
  - [x] 5.1 `KNOWN_EVENT_TYPES = frozenset({9 types})`
  - [x] 5.2 `async def ingest_events(*, events, user_id, supabase) -> dict[str, int]`
  - [x] 5.3 Ownership check: single `.in_("session_id", session_ids).eq("user_id", user_id)` query via `asyncio.to_thread`
  - [x] 5.4 Raise HTTP 403 if `authorized_ids != requested_ids` (both missing and wrong-user paths)
  - [x] 5.5 Log WARNING for each event with unknown event_type
  - [x] 5.6 Build rows: `{"session_id": e.session_id, "event_type": e.event_type, "payload": {**e.payload, "_client_ts_ms": e.client_timestamp_ms}}`
  - [x] 5.7 Single bulk insert via `asyncio.to_thread`
  - [x] 5.8 Raise HTTP 500 with sanitized log if `insert_resp.error` is truthy
  - [x] 5.9 Return `{"ingested": len(rows)}`

- [x] Task 6: Update `apps/api/app/modules/analytics/router.py` to call service (GREEN phase)
  - [x] 6.1 Replace 501 stub in `ingest_events` with lazy imports and call to `_ingest_events`
  - [x] 6.2 Updated docstring — removed "analytics_events" reference (table is `session_events`)

- [x] Task 7: Run full test suite (verify GREEN + no regressions)
  - [x] 7.1 `pytest tests/test_analytics_events_endpoint.py -v` — 26/26 PASS
  - [x] 7.2 `pytest tests/test_assessment_stub_contracts.py -v` — 9/9 PASS (AC 16 fix confirmed)
  - [x] 7.3 `pytest -m unit --ignore=test_tutor_*.py -v` — 357 pass, 0 Dev 3 regressions

- [x] Task 8: Tracker update
  - [x] 8.1 Mark Sprint 2 Task 3 done in `docs/dev3-assessment-tracker.md`
  - [x] 8.2 Update Quick Status Dashboard (Sprint 2: Done 2→4; Total: 21→23)

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

**Reviewer layers run:** 5 parallel adversarial agents (Story Quality, Blind Hunter, Test Coverage, AC Completeness, Process Integrity)
**Review date:** 2026-07-03
**Outcome:** Changes Requested → All BLOCKERs fixed before commit

---

### Agent 1 — Story Quality

**Verdict:** PASS (after fixes)

**Findings resolved before commit:**
- [x] B1: AC 15 ("No LLM calls") had no test → added `test_no_llm_calls_in_analytics_ingest_flow`
- [x] B2: Missing AC for `_client_ts_ms` key collision → added AC 3a + test
- [x] B3: AC 14 (unauthenticated) had no test → added `test_unauthenticated_request_is_rejected`
- [x] I1: AC 12 log sanitization half-tested → added `test_500_on_insert_error_logs_error_with_sanitized_message` with caplog
- [x] I2: AC 17 stub contract test in wrong file → added `test_analytics_events_endpoint_is_live_not_501` to `test_assessment_stub_contracts.py`
- [x] N1: Story-first gate satisfied — commit `5cfe2a1` is first, implementation committed after review

**Deferred:** N/A — no deferred story quality items

---

### Agent 2 — Blind Hunter (Security)

**Verdict:** PASS (after fixes)

**Findings resolved before commit:**
- [x] I1: Log injection — `%s` for `session_id`/`user_id` changed to `%r` in both `logger.warning` and `logger.error` calls in `service.py`

**Dismissed:**
- B-1 (false positive): Blind Hunter flagged "no batch count upper bound" — `BatchEventsRequest` already has `max_length=100`; diff did not show unchanged field so agent missed it
- I-3 (by design): Unknown event_type accepted and stored — this is AC 10 intentional soft validation

**Deferred:**
- I-2 (payload size unbounded): Global request-size middleware concern, out of Sprint 2 scope. Deferred to Sprint 4 hardening.
- N-1 (session_id not UUID-typed): Established pattern across all assessment endpoints. Deferred to global schema hardening.

**Confirmed secure:**
- IDOR via mixed-owner batch: SET comparison `authorized_ids != requested_ids` correctly catches partial-match batches — no bypass found
- Session enumeration oracle: both "missing" and "wrong-user" paths return identical HTTP 403 + identical detail string
- `_client_ts_ms` collision: server value (`client_timestamp_ms`) correctly overwrites any client-supplied `_client_ts_ms` key in payload (Python dict trailing-key semantics). AC 3a added.

---

### Agent 3 — Test Coverage

**Verdict:** PASS (after fixes)

**Findings resolved before commit:**
- [x] B1: AC 14 unauthenticated test added (separate `_unauthed_app` without auth override)
- [x] I1: AC 7 IDOR — user_id argument to `.eq()` now asserted in `test_ownership_query_passes_correct_user_id_to_eq`
- [x] I2: 100-event boundary test added (`test_100_events_returns_202`)
- [x] I3: Payload field omitted from body tested (`test_event_without_payload_field_uses_empty_dict_default`)
- [x] I4: `ownership_resp.data=None` path tested (`test_403_when_ownership_resp_data_is_none`)
- [x] I5: AC 15 LLM structural guard added
- [x] I7: Duplicate session_ids tested (`test_50_events_same_session_id_single_ownership_query`)

**Deferred:**
- I6 (`_captured_mocks` positional-index fragility): Pattern matches `test_session_report_endpoint.py`; refactoring wide. Deferred to test infrastructure sprint.
- N1 (AC 13 assertions weak): `len(to_thread_calls) >= 2` is sufficient for regression detection; exact count not required.
- N3 (asyncio.get_event_loop() deprecated): Python 3.12 compat; test passes. Deferred.

---

### Agent 4 — AC Completeness

**Verdict:** PASS (after fixes)

**Full AC-to-test mapping (17 ACs + AC 3a):**

| AC | Test(s) | Status |
|----|---------|--------|
| 1 | test_202_single_event_returns_ingested_1, test_202_batch_of_three_returns_ingested_3 | COVERED |
| 2 | test_jargon_hover_event_payload_correct | COVERED |
| 3 | test_client_timestamp_stored_as_client_ts_ms_in_payload, test_client_ts_ms_merged_alongside_existing_payload_keys | COVERED |
| 3a | test_reserved_client_ts_ms_key_in_payload_is_overwritten_by_server_value | COVERED |
| 4 | test_empty_events_list_returns_422 | COVERED |
| 5 | test_101_events_returns_422, test_100_events_returns_202 | COVERED |
| 6 | test_negative_client_timestamp_returns_422 | COVERED |
| 7 | test_403_when_session_belongs_to_different_user, test_mixed_valid_invalid_session_batch_fully_rejected, test_ownership_query_passes_correct_user_id_to_eq | COVERED |
| 8 | test_403_when_session_does_not_exist, test_403_detail_identical_for_missing_and_wrong_user_sessions | COVERED |
| 9 | test_single_bulk_insert_call_not_per_event, test_50_events_same_session_id_single_ownership_query | COVERED |
| 10 | test_unknown_event_type_accepted_returns_202, test_unknown_event_type_logs_warning, test_all_9_known_event_types_accepted[*] | COVERED |
| 11 | test_all_9_known_event_types_accepted[*], test_event_type_field_description_lists_all_9_known_types, test_event_type_field_description_states_unknown_types_accepted | COVERED |
| 12 | test_500_on_insert_error, test_500_on_insert_error_logs_error_with_sanitized_message | COVERED |
| 13 | test_ownership_check_uses_asyncio_to_thread, test_insert_uses_asyncio_to_thread | COVERED |
| 14 | test_unauthenticated_request_is_rejected | COVERED |
| 15 | test_no_llm_calls_in_analytics_ingest_flow | COVERED |
| 16 | test_onboarding_endpoint_is_live_not_501 (test_assessment_stub_contracts.py) | COVERED |
| 17 | test_analytics_events_endpoint_is_live_not_501 (both files) | COVERED |

---

### Agent 5 — Process Integrity

**Verdict:** PASS

**All checks passed:**
- Zero LLM imports in `service.py` or `router.py` — pure DB write
- Zero hardcoded model strings
- Both supabase calls wrapped in `asyncio.to_thread` (ownership query + bulk insert)
- Router delegates to service only — no direct DB calls in router layer
- BMAD story-first gate: story commit `5cfe2a1` is first on branch
- No `cost_tracker` required (no LLM calls, rule correctly exempts pure DB writes)

**Deferred:**
- Module boundary: analytics service queries `sessions` table directly — established pattern in `assessment/service.py` (3 identical queries); deferred to shared session ownership utility extraction sprint.

**Branch naming:** `dev3-sprint2-task3` — intentional Dev 3 naming convention (confirmed in memory `feedback_branching_strategy.md`); not a violation.

---

### Action Items Summary

| ID | Severity | Status | Description |
|----|----------|--------|-------------|
| B1 | BLOCKER | [x] Fixed | AC 14 unauthenticated test added |
| B2 | BLOCKER | [x] Fixed | AC 15 LLM structural guard test added |
| B3 | BLOCKER | [x] Fixed | AC 3a added — _client_ts_ms collision specified + tested |
| B4 | BLOCKER | [x] Fixed | AC 12 logging + sanitization verified with caplog |
| B5 | BLOCKER | [x] Fixed | AC 11 field description content verified in test |
| B6 | BLOCKER | [x] Fixed | AC 17 stub contract test added to test_assessment_stub_contracts.py |
| I1 | IMPROVEMENT | [x] Fixed | %r for session_id/user_id in logger calls |
| I2 | IMPROVEMENT | [x] Fixed | user_id arg asserted in ownership mock |
| I3 | IMPROVEMENT | [x] Fixed | 100-event boundary test added |
| I4 | IMPROVEMENT | [x] Fixed | payload omitted from body tested |
| I5 | IMPROVEMENT | [x] Fixed | ownership_resp.data=None path tested |
| I6 | IMPROVEMENT | [x] Fixed | duplicate session_ids in batch tested |
| D1 | DEFERRED | [x] | Module boundary — sessions table query direct |
| D2 | DEFERRED | [x] | Payload size unbounded |
| D3 | DEFERRED | [x] | _captured_mocks indexing fragility |
