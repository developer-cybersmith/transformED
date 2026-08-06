---
id: "4-23"
title: "PATCH /api/auth/notifications — notification preference write endpoint"
status: "done"
sprint: 3
story_points: 3
baseline_commit: "dca9872f9cc60f2ff63f0d7502d762768da769df"
owner: Dev4
priority: P2
blocker_ref: D60
---

# Story 4-23 — PATCH /api/auth/notifications (S3-07 Dev 4 Contribution)

## Context & Scope Boundary

**Why this story exists:** D60 identified three missing pieces for S3-07 (Notifications UI).
Dev 3 delivered the read-helper (`get_notification_preference()`, Story 3-33, 2026-08-06).
Dev 1 delivered the migration (`20260806000000_user_notification_preferences.sql`, also 2026-08-06).
This story delivers the **write endpoint** Dev 4 owns: `PATCH /api/auth/notifications`.

Dev 2's frontend currently backs notification preferences with an in-memory mock that cannot
survive a page reload. Dev 2 is blocked on this endpoint to wire the real backend and remove
that mock. That makes this story the critical-path item for D60 closure.

**What this story does NOT do:**
- Create the DB table (already done — migration 20260806000000 applied to both Supabase projects)
- Implement Dev 3's read-helper (done — `notification_prefs.py`)
- Wire the frontend toggle UI (Dev 2, unblocked by this story)
- Send emails (no email provider in the locked stack — future scope)

**Scope boundary — this endpoint lives in `apps/api/app/modules/auth/router.py`.**
There is no `users` module. The `auth` module owns all user-account management routes
(`/api/auth/me`, `/api/auth/onboarding/complete`). Notification preferences are a user
account setting — they belong here.

---

## Story

**As a** user who wants to control which email notifications they receive,
**I want** a `PATCH /api/auth/notifications` endpoint that persists my preference choices,
**so that** my settings survive page reloads and Dev 3's email delivery path can respect
my opt-outs before sending session report emails.

---

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `PATCH /api/auth/notifications` is registered in
  `apps/api/app/modules/auth/router.py` and is discoverable in `/docs`.

- [ ] **AC 2.** Request without a `Authorization: Bearer <token>` header → 401/403.

- [ ] **AC 3.** Request with an expired or invalid JWT → 401.

- [ ] **AC 4.** Valid JWT + one or more preference fields → 200 response body containing
  `user_id`, `session_report_email`, `lesson_ready_email`, `weekly_progress_email`,
  `streak_reminders`, and `updated_at`.

- [ ] **AC 5.** `user_id` in both the DB write and the response is taken from the JWT `sub`
  claim only — never from the request body. Sending `user_id` in the body is silently ignored
  (extra fields rejected by Pydantic, not accepted).

- [ ] **AC 6.** Partial update: if only `session_report_email: false` is sent and the user
  already has `weekly_progress_email: false` stored, the returned row shows
  `weekly_progress_email: false` — the omitted field is preserved, not reset.

- [ ] **AC 7.** Empty request body (no preference fields provided) → 422.

- [ ] **AC 8.** `updated_at` in the response is strictly greater than the value stored before
  the call (refreshed on every successful PATCH).

### Non-functional / security

- [ ] **AC 9.** All Supabase calls are wrapped in `asyncio.to_thread` — the supabase-py v2
  client is synchronous and must not block the event loop.

- [ ] **AC 10.** No LLM call anywhere in this endpoint's code path — asserted by source
  inspection (no reference to any LLM identifier in `auth/router.py`'s notification handler).

- [ ] **AC 11.** DB upsert failure raises `HTTPException(status_code=500)` — failures are
  never silently swallowed.

- [ ] **AC 12.** The read query uses `.maybe_single()` — bounded by design; no
  unbounded SELECT added to a request path (Scale Contract Q4, `test_unbounded_queries.py`).

---

## Scale & Load

*Required per `docs/SCALE-CONTRACT.md`. "N/A" only with a reason.*

1. **One unit of work, and its range.**
   One PATCH reads ≤1 row and writes exactly 1 row in `user_notification_preferences`
   (PRIMARY KEY `user_id` — the table can hold at most one row per user by constraint).
   Range: 0 existing rows (first call, row is created) to 1 (update). Fixed shape; no
   fan-out regardless of account age or history.

2. **Fixed budgets while input varies.**
   Request body is a Pydantic model with 4 optional boolean fields — input is bounded at
   the schema layer before any DB call. No variable-size input reaches the DB.
   The read uses `.maybe_single()` (PostgREST enforces ≤1 row or 406 error).
   The upsert payload is a fixed-key dict (7 keys); no loops, no list expansion.

3. **Scope of every limit.**
   Per-user isolation enforced at two layers: (a) JWT `sub` is the only `user_id` source;
   (b) the read `.eq("user_id", user_id)` filter prevents cross-user reads.
   No per-instance or per-deployment cap is involved — single-row reads and writes are
   O(1) regardless of replica count.

4. **Unbounded reads and writes.**
   None. Read: `.maybe_single()` (bounded). Write: single `.upsert()` of a fixed-shape
   dict. The read query is in `auth/router.py` and is in scope for `test_unbounded_queries.py`;
   the `.maybe_single()` token satisfies the scanner's BOUNDED criteria.

5. **Inherited caps.**
   None — `user_notification_preferences` is a new table with no prior design. No cap is
   carried forward from an older unit of work.

6. **Check-then-act concurrency.**
   The read-then-upsert pattern has a TOCTOU window: two concurrent PATCHes from the same
   user could both read the existing row, merge independently, and both upsert. The PRIMARY
   KEY constraint prevents duplicate rows; last-writer-wins on `updated_at`. For notification
   preferences (low-frequency user action, no financial or safety consequence), last-writer-wins
   is the accepted behaviour. Noted in Dev Notes; no register entry needed (not a silent wrong).

---

## Dev Notes

### Module placement
`apps/api/app/modules/auth/router.py` at prefix `/api/auth`. No `users` module exists;
auth is the correct home for user-account settings.

### DB client pattern
Use the **service-role Supabase client** (`get_supabase()` from `app.core.db`) — same
pattern used across the entire codebase. The service-role key bypasses RLS; enforce
access control by filtering on `user_id` from the JWT. Never use the anon key on a
write path.

### asyncio.to_thread requirement
`supabase-py v2` is synchronous. Every Supabase call **must** be wrapped:
```python
resp = await asyncio.to_thread(lambda: supabase.table(...).select(...).execute())
```
Calling it directly from an `async def` handler blocks the event loop under any load.
This pattern is established across the assessment module — follow it exactly.

### Partial update strategy (read-merge-upsert)
A true PATCH endpoint must not overwrite unspecified fields. The table uses
`NOT NULL DEFAULT true` for all booleans — a bare upsert of only the provided fields
would silently reset the omitted fields to `true` on the second write.

**Correct pattern:**
1. `SELECT` existing row → `maybe_single()` → `row.data or _DEFAULT_PREFS`
2. `merge = {**existing, **provided_fields}` — only provided fields win
3. `UPSERT` the full merged dict with `updated_at` = `datetime.now(timezone.utc)`

On `SELECT` failure (rare, infrastructure): fail-open to defaults (same rationale as
Dev 3's `get_notification_preference()`). On `UPSERT` failure: raise HTTP 500 — the
user must know their preference was not saved.

### Lazy import (circular import prevention)
Follow the established pattern in `assessment/router.py`:
```python
from app.core.db import get_supabase  # lazy — prevents circular import at module load
```

### Response model
Return a Pydantic `BaseModel` with all 6 fields. Do NOT use `dict[str, Any]` for
responses — that loses the schema from `/docs` and loses OpenAPI contract visibility.

### Default preferences
```python
_DEFAULT_PREFS: dict[str, bool] = {
    "session_report_email": True,
    "lesson_ready_email": True,
    "weekly_progress_email": True,
    "streak_reminders": True,
}
```
These match the table's `DEFAULT true` columns. Used as fallback when no existing row
is found, ensuring the merge step always has a complete base to patch over.

### Empty-body 422 guard
Use a Pydantic `model_validator(mode="after")` that raises `ValueError` if all four
fields are `None`. FastAPI will surface this as a 422 Unprocessable Entity.

### `test_unbounded_queries.py` compatibility
The read query:
```python
supabase.table("user_notification_preferences").select("...").eq("user_id", uid).maybe_single().execute()
```
contains `.maybe_single()` — the scanner's BOUNDED token. No `# BOUNDED:` comment needed.
The upsert is a write, not a select; the scanner only checks reads.

---

## Tasks / Subtasks

### Task 1 — Story file (DONE — this commit)
- [x] 1.1 Create `docs/stories/4-23-notifications-endpoint.md`
- [x] 1.2 Commit story-only to `sprint3/s3-07-notifications-endpoint`
- [x] 1.3 Push to remote

### Task 2 — RED phase (failing tests)
- [x] 2.1 Create `apps/api/tests/test_notifications_endpoint.py`
- [x] 2.2 Test AC 1 (endpoint registered, reachable)
- [x] 2.3 Test AC 2 (no JWT → 401/403)
- [x] 2.4 Test AC 3 (expired/invalid JWT → 401)
- [x] 2.5 Test AC 4 (valid JWT + fields → 200 with full response)
- [x] 2.6 Test AC 5 (user_id from JWT only; body `user_id` ignored)
- [x] 2.7 Test AC 6 (partial update preserves omitted fields)
- [x] 2.8 Test AC 7 (empty body → 422)
- [x] 2.9 Test AC 8 (updated_at refreshed)
- [x] 2.10 Test AC 9 (asyncio.to_thread wraps DB calls — source inspection)
- [x] 2.11 Test AC 10 (no LLM call — source inspection)
- [x] 2.12 Test AC 11 (DB upsert failure → 500)
- [x] 2.13 Confirm all tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [x] 3.1 Add `NotificationPatchRequest` Pydantic model with 4 optional bool fields + empty-body validator
- [x] 3.2 Add `NotificationPreferencesResponse` Pydantic model (6 fields)
- [x] 3.3 Implement `patch_notifications()` handler in `auth/router.py`
     — `CurrentUser` dependency, lazy `get_supabase()` import, read-merge-upsert pattern
- [x] 3.4 Confirm all 13 tests PASS

### Task 4 — REFACTOR + validation
- [x] 4.1 `ruff check apps/api/app/modules/auth/router.py apps/api/tests/test_notifications_endpoint.py`
- [x] 4.2 `ruff format --check` on the same files
- [x] 4.3 Confirm all tests still pass after ruff fixes
- [x] 4.4 Run full Dev 4 regression suite (`pytest apps/api/tests/ -q --ignore=apps/api/tests/integration`)

### Task 5 — D60 progress note
- [x] 5.1 Add a note to `docs/DEFECT-REGISTER.md` D60 entry: Dev 4 scope complete (this story),
         remaining: Dev 2 frontend wiring

### Task 6 — 6-layer adversarial review
- [x] 6.1 Layer 1 — Story Quality
- [x] 6.2 Layer 2 — Blind Hunter (Security)
- [x] 6.3 Layer 3 — Test Coverage
- [x] 6.4 Layer 4 — AC Completeness
- [x] 6.5 Layer 5 — Process Integrity
- [x] 6.6 Layer 6 — Scale & Load

### Task 7 — Commit + handoff
- [ ] 7.1 Final commit on `sprint3/s3-07-notifications-endpoint`
- [ ] 7.2 Push to remote
- [ ] 7.3 Update `docs/dev4-tracker.md`

---

## Senior Developer Review (AI)

**Date:** 2026-08-06  
**Outcome:** Changes Requested → Applied → ✅ Approved  
**Review layers run:** Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter, Story Quality, Process Integrity

### Action Items (all resolved)

- [x] **[HIGH] AC 5 — Missing `ConfigDict(extra='forbid')`**  
  `NotificationPatchRequest` silently ignored extra fields (Pydantic default). AC 5 specifies "extra fields rejected by Pydantic." Fixed: `model_config = ConfigDict(extra='forbid')` added. New test: `test_patch_notifications_extra_body_fields_returns_422`.

- [x] **[HIGH] Read failure silently corrupts stored preferences**  
  The `except Exception` block fell back to `_NOTIF_DEFAULTS` and continued to upsert. A transient read failure would overwrite stored non-default values (e.g. `weekly_progress_email: False`) with `True`. Fixed: read failure now raises HTTP 503 so the caller retries; upsert is never called on a failed read. Test renamed to `test_patch_notifications_read_failure_raises_503`; asserts upsert not called.

- [x] **[HIGH] Unguarded `upsert_resp.data[0]`**  
  `IndexError` on empty list (Supabase `Prefer: return=minimal`) was caught and surfaced as "Failed to update notification preferences" even when the write succeeded. Fixed: `try/except` now wraps only the network call; empty-data check is a separate explicit guard with a distinct error message. New test: `test_patch_notifications_upsert_empty_response_raises_500`.

- [x] **[HIGH] AC 12 test mislabeled — wrong behavior tested**  
  Test labeled "AC 12" was testing the (now-removed) fail-open behavior, not `.maybe_single()` boundedness. Fixed: old test replaced with `test_patch_notifications_read_failure_raises_503`; new `test_patch_notifications_read_uses_maybe_single` uses source inspection to guard AC 12.

- [x] **[MED] AC 8 — test asserted upsert payload, not `result.updated_at`**  
  CLAUDE.md binding rule 2: "No test may assert only on a mock it constructed." Test checked the timestamp sent *to* the mock but never checked `result.updated_at`. Fixed: test now saves result and asserts `result.updated_at == new_ts`.

- [x] **[LOW] `str(row["updated_at"])` produces non-ISO 8601 format**  
  `supabase-py` returns `timestamptz` as a Python `datetime` object; `str()` gives `"2026-08-06 12:00:00+00:00"` (space-separated). Fixed: `updated_at_raw.isoformat()` used when the value has an `.isoformat()` method, falling back to `str()` otherwise.

### Final test count: 16 (was 13) — all pass.  
### Ruff: clean. Format: clean. Regression suite (106 auth-domain tests): all pass.

---

## Dev Agent Record

### Implementation Plan

1. Add two Pydantic models to `auth/router.py`:
   `NotificationPatchRequest` (4 optional bools + empty-body validator) and
   `NotificationPreferencesResponse` (user_id, 4 bools, updated_at).
2. Implement `patch_notifications()` handler:
   read (`.maybe_single()`) → merge → upsert → return response model.
3. Create `apps/api/tests/test_notifications_endpoint.py` — 13 tests covering all ACs.
4. Update `docs/DEFECT-REGISTER.md` D60: Dev 4 scope complete.
5. Update `docs/dev4-tracker.md`.

### Debug Log

*(populated during implementation)*

### Completion Notes

*(populated on completion)*

### File List

- `apps/api/app/modules/auth/router.py` — MODIFIED (endpoint + 2 models added)
- `apps/api/tests/test_notifications_endpoint.py` — NEW
- `docs/DEFECT-REGISTER.md` — MODIFIED (D60 Dev 4 progress note)
- `docs/stories/4-23-notifications-endpoint.md` — NEW (this file)
- `docs/dev4-tracker.md` — MODIFIED

### Change Log

- 2026-08-06: Story file created (story-first commit)
- 2026-08-06: Implementation complete — 16 tests, all AC covered, 6-layer review applied, all review findings resolved
