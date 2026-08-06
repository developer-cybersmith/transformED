---
id: "3-33"
title: "Notification Preference Guard — session_report_email read-helper"
status: "done"
sprint: 3
story_points: 2
baseline_commit: ""
owner: Dev3
priority: P2
blocker_ref: S3-07
---

# Story 3-33 — Notification Preference Guard (S3-07 Dev 3 Contribution)

## Context & Scope Boundary

**Why this story exists:** S3-07 (Notifications UI) requires `PATCH /api/users/notifications`
and a `user_notification_preferences` DB table. Both are **Dev 1 / Dev 4 responsibilities**
(infrastructure migration + users/auth module endpoint). Dev 3 owns `session_report_email`
*consumption* — when session report email delivery is added to the assessment module, the
delivery code must respect the user's opt-out preference.

This story delivers the **read-helper** Dev 3 needs before that delivery path is built:
a safe, independently-testable `get_notification_preference()` function that:
- reads a named boolean column from the `user_notification_preferences` table (future schema)
- **fails open** (returns `True`) on any DB error, missing table, missing row, or `NULL` value
- has no LLM calls, no writes, no side effects

**What this story does NOT do:**
- Create the `user_notification_preferences` table (Dev 1)
- Implement `PATCH /api/users/notifications` (Dev 4)
- Implement session report email sending (future scope, no email provider in stack)
- Wire the frontend (Dev 2)

## Story

**As a** session report delivery path (future),
**I want** a `get_notification_preference(*, user_id, preference_key, supabase) → bool`
helper that safely reads a user's boolean notification preference from the DB,
**so that** when email delivery is implemented, Dev 3 can respect opt-outs without
taking on ownership of the preference storage infrastructure.

## Acceptance Criteria

### Functional
- [x] **AC 1.** `get_notification_preference(user_id, "session_report_email", supabase)`
  exists in `apps/api/app/modules/assessment/notification_prefs.py` and is importable.
- [x] **AC 2.** Returns `True` (fail-open) when the DB raises any exception
  (e.g. table not found, connection error). Non-fatal: logs WARNING, never raises.
- [x] **AC 3.** Returns `True` when the DB returns an empty result set
  (user has no preference row yet — default opt-in).
- [x] **AC 4.** Returns `True` when the stored value is `None` / `NULL`
  (partial row — default opt-in).
- [x] **AC 5.** Returns the stored `bool` value when a row exists and the column is
  non-null: `True` → `True`; `False` → `False`.
- [x] **AC 6.** The DB query filters by `user_id` — no cross-user data leak.

### Non-functional / security
- [x] **AC 7.** No LLM call anywhere in this module — asserted by patching
  `OpenAILLMProvider` and asserting `assert_not_called()`.
- [x] **AC 8.** The DB call is wrapped in `asyncio.to_thread` (Supabase client is sync).
- [x] **AC 9.** `get_notification_preference` is `async` — confirmed by
  `inspect.iscoroutinefunction`.
- [x] **AC 10.** The function reads from `user_notification_preferences` table,
  NOT from `users` (no bleed into the auth-owned table).
- [x] **AC 11.** `user_id` parameter is the only access gate — function never
  reads a user ID from a request body or any other mutable input.

### Defect registration
- [x] **AC 12.** Defect D60 registered in `docs/DEFECT-REGISTER.md` documenting
  the missing `PATCH /api/users/notifications` endpoint, missing DB schema,
  and mock-only frontend state with correct owners and trigger.

## Scale & Load

1. **One unit of work:** single `SELECT` of one row from `user_notification_preferences`
   by `user_id`. Range: 0–1 rows always (one row per user). No fan-out.
2. **Fixed budgets while input varies:** none. Single-row read, no page/limit needed
   (one user → at most one row). `.maybe_single()` enforces this at the PostgREST level.
3. **Scope of limits:** per-user read. No rate limit applies to a single read.
4. **Unbounded reads/writes:** none. `.maybe_single()` is the bound.
5. **Inherited caps:** none inherited — new function, new table.
6. **Check-then-act safety:** read-only, no mutations. No TOCTOU risk.

## Dev Notes

### Module placement
`apps/api/app/modules/assessment/notification_prefs.py` — assessment module owns session
reports, so this helper belongs there. Keeps analytics/service.py clean.

### Future schema (for Dev 1 / Dev 4 reference)
```sql
-- Dev 3 expects this table to exist before session report email delivery is added:
-- CREATE TABLE public.user_notification_preferences (
--   user_id              uuid REFERENCES public.users(id) ON DELETE CASCADE,
--   session_report_email boolean DEFAULT true,
--   lesson_ready_email   boolean DEFAULT true,
--   weekly_progress_email boolean DEFAULT true,
--   streak_reminders     boolean DEFAULT true,
--   updated_at           timestamptz DEFAULT now(),
--   PRIMARY KEY (user_id)
-- );
-- RLS: users can SELECT and UPDATE only their own row.
```

### Fail-open rationale
New users have no preference row. An opt-in default is correct: they signed up to learn
and should receive session reports. Only an explicit `False` means opt-out. `NULL` means
"not configured yet" → treat as opt-in.

### `asyncio.to_thread` requirement
Supabase-py v2 is a synchronous client. Every call must be wrapped in `asyncio.to_thread`
to avoid blocking the event loop (CLAUDE.md and established pattern from all Dev 3 service
functions).

## Tasks / Subtasks

### Task 1 — Story file (DONE — this commit)
- [x] 1.1 Create `docs/stories/3-33-notification-preference-guard.md`
- [x] 1.2 Commit story-only to `sprint3/s3-07-dev3-notification-prefs`
- [x] 1.3 Push to remote

### Task 2 — RED phase (failing tests)
- [x] 2.1 Create `apps/api/tests/test_notification_prefs.py`
- [x] 2.2 Test AC 1 (module importable, function exists)
- [x] 2.3 Test AC 2 (DB exception → True)
- [x] 2.4 Test AC 3 (empty result → True)
- [x] 2.5 Test AC 4 (NULL value → True)
- [x] 2.6 Test AC 5 (True stored → True; False stored → False)
- [x] 2.7 Test AC 6 (user_id used as filter)
- [x] 2.8 Test AC 7 (no LLM calls)
- [x] 2.9 Test AC 8 (asyncio.to_thread wrapper)
- [x] 2.10 Test AC 9 (iscoroutinefunction)
- [x] 2.11 Test AC 10 (reads user_notification_preferences, not users)
- [x] 2.12 Confirm all tests FAIL before implementation

### Task 3 — GREEN phase (implementation)
- [x] 3.1 Create `apps/api/app/modules/assessment/notification_prefs.py`
- [x] 3.2 Implement `get_notification_preference()`
- [x] 3.3 Confirm all tests PASS

### Task 4 — REFACTOR + validation
- [x] 4.1 Ruff check
- [x] 4.2 Ruff format check
- [x] 4.3 Confirm all tests still pass
- [x] 4.4 Run full Dev 3 regression suite

### Task 5 — Defect registration
- [x] 5.1 Register D60 in `docs/DEFECT-REGISTER.md`
- [x] 5.2 Update `docs/dev3-assessment-tracker.md` Sprint 4 section

### Task 6 — 5-agent adversarial review
- [x] 6.1 Layer 1 — Story Quality
- [x] 6.2 Layer 2 — Blind Hunter (Security)
- [x] 6.3 Layer 3 — Test Coverage
- [x] 6.4 Layer 4 — AC Completeness
- [x] 6.5 Layer 5 — Process Integrity
- [x] 6.6 Layer 6 — Scale & Load (new mandatory layer per CLAUDE.md update)

### Task 7 — Commit + handoff
- [x] 7.1 Final commit on `sprint3/s3-07-dev3-notification-prefs`
- [x] 7.2 Push to remote
- [x] 7.3 Update `docs/dev3-assessment-tracker.md`

## Senior Developer Review (AI)

**Review date:** 2026-08-06
**Outcome:** APPROVE WITH CHANGES — two findings resolved before final commit.

### Action Items

**Layer 1 — Story Quality**
- [x] **HIGH** AC 12 referenced D58, which was already allocated to the eval-harness defect. Corrected to D60 (next available ID). D60 registered in `docs/DEFECT-REGISTER.md`. Story-first gate PASS.

**Layer 2 — Blind Hunter (Security)**
- [x] **LOW/PLAUSIBLE** Log line at `notification_prefs.py:83-86` passes `user_id` and `preference_key` to `%s` without newline sanitization — accepted: `user_id` is a UUID from JWT sub (no newlines), `preference_key` is an internal constant. No change required.

**Layer 3 — Test Coverage**
- [x] **MED** `test_no_llm_calls` was vacuously true — it patched `app.providers.llm.openai.OpenAILLMProvider`, a symbol the module never imports, so `assert_not_called()` was trivially satisfied. Replaced with source inspection via `inspect.getsource()` asserting no LLM identifier appears in `notification_prefs.py`.

**Layer 4 — AC Completeness**
- [x] All 11 functional ACs covered by tests after Layer 3 fix. AC 12 verified as D60 registration task.

**Layer 5 — Process Integrity**
- [x] No hardcoded model strings. No cross-module imports. `__all__` correct. Keyword-only args. No LLM calls.

**Layer 6 — Scale & Load**
- [x] `.maybe_single()` enforces single-row bound. `notification_prefs.py` is outside `test_unbounded_queries.py` scan scope; no new entries required in `_KNOWN_UNBOUNDED`. All 6 Scale & Load questions answered in story.

## Dev Agent Record

### Implementation Plan

1. `notification_prefs.py` — `get_notification_preference()` only. Reads
   `user_notification_preferences`, fail-open on any error.
2. `test_notification_prefs.py` — 11 tests covering all ACs.
3. `docs/DEFECT-REGISTER.md` — D58 entry documenting S3-07 missing infrastructure.
4. `docs/dev3-assessment-tracker.md` — Sprint 4 task for future email guard.

### Debug Log

*(populated during implementation)*

### Completion Notes

Implemented `get_notification_preference()` as a fail-open read-helper. D60 registered in `docs/DEFECT-REGISTER.md` documenting the three missing S3-07 pieces with named owners. `test_no_llm_calls` rewritten from a vacuously-true mock-patch to a source-inspection assertion (5-agent review Finding 2). 12/12 tests pass, 0 ruff errors. Story-first gate satisfied: story committed in `cfef29c` before all implementation. Branch: `sprint3/s3-07-dev3-notification-prefs`.

### File List

- `apps/api/app/modules/assessment/notification_prefs.py` — NEW
- `apps/api/tests/test_notification_prefs.py` — NEW
- `docs/stories/3-33-notification-preference-guard.md` — NEW (this file)
- `docs/DEFECT-REGISTER.md` — MODIFIED (D58 added)
- `docs/dev3-assessment-tracker.md` — MODIFIED (Sprint 4 task added)

### Change Log

- 2026-08-06: Story file created (story-first commit `cfef29c`)
- 2026-08-06: RED phase — 12 failing tests in `test_notification_prefs.py`
- 2026-08-06: GREEN phase — `notification_prefs.py` implemented; 12/12 pass
- 2026-08-06: REFACTOR — ruff clean, `asyncio.run()` event-loop fix applied
- 2026-08-06: 5-agent review — Finding 1: D58 ID taken → corrected to D60; Finding 2: vacuous test_no_llm_calls → source inspection
- 2026-08-06: D60 registered in `docs/DEFECT-REGISTER.md`
- 2026-08-06: `docs/dev3-assessment-tracker.md` Sprint 4 task added
