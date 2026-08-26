---
baseline_commit: b169c21fdc1330c476edecda3f8b57a2a17913eb
---

# Story 2.52: Email Notifications — Lesson Ready + Session Report (S4-12)

Status: ready-for-dev

## Story

As a student,
I want an email when my lesson finishes generating and another when my session report is ready,
so that I don't have to keep a browser tab open or manually refresh the dashboard to know either is done.

**Source:** `docs/master-tracker.md`'s Sprint 4 Dev 2 list ("Email notifications (lesson ready, session report)") — reprioritized by the user 2026-08-25 to be completed **before** S4-02 (Razorpay). Had no story or S4-number before now. Assigned **S4-12**.

**Scope note — this crosses into `apps/api` (Dev 1's normal domain), same as S4-06's library/books merge did.** A grounding audit (read-only, both `apps/web` and `apps/api`) found the **frontend half of this feature is already 100% complete** (S3-07, `NotificationsTab.tsx` + `useNotificationPreferences.ts`) — the entire remaining scope is backend. This is a genuinely greenfield backend feature: **zero email-sending code exists anywhere in the repo today.**

## Current State, Confirmed By Reading Every File This Story Touches

**Frontend — done, not touched by this story:**
- `apps/web/src/components/settings/tabs/NotificationsTab.tsx` renders 4 toggles: `session_report_email`, `lesson_ready_email`, `weekly_progress_email`, `streak_reminders`.
- `apps/web/src/hooks/useNotificationPreferences.ts` reads `user_notification_preferences` directly from Supabase (own-row, RLS-scoped) and writes via the real `PATCH /api/auth/notifications`.
- Only `session_report_email` and `lesson_ready_email` have a real trigger anywhere in the system (see below) — `weekly_progress_email`/`streak_reminders` have no corresponding event or cron job. This story's title ("lesson ready, session report") already correctly excludes those two; they are explicitly **out of scope** here.
- No "email sent" / delivery-status UI exists on the frontend, and none is needed — preference-toggling is the entire frontend surface for this feature.

**Backend — genuinely greenfield, confirmed by repo-wide search:**
- No match anywhere in `apps/api` for `resend`, `Resend`, `notification_worker`, `send_email`, or `email_template`. No `RESEND_API_KEY` in `apps/api/app/config.py`.
- `docs/bmad/epics/epic-5-platform-core.md`'s `backend/workers/notification_worker.py` and `backend/notifications/templates/*.html` paths **do not exist** — that doc predates the current repo structure. Real ARQ jobs live in `apps/api/app/workers/jobs/`; this story uses that real structure, not the epic doc's aspirational one.

**Trigger points, confirmed by reading the real code:**
- **Lesson ready:** `content_pipeline_job` (`apps/api/app/workers/jobs/content_pipeline.py:23`) publishes to Redis pub/sub at `content_pipeline.py:179` (`channel = f"lesson_ready:{lesson_id}"`) once `package_builder_node` completes. This runs inside the ARQ worker process — the natural place to also enqueue the notification job.
- **Session report:** `session_end_node` (`apps/api/app/modules/tutor/state_machine/graph.py:353`) fire-and-forgets `_finalize_session` (`graph.py:724`, via `asyncio.create_task`), which writes `ces_final`/`ended_at`. **This runs in the FastAPI/WebSocket process, not the ARQ worker** — sending the email from here means enqueuing a job *across* processes (`await redis.enqueue_job('send_notification_email', ...)`), not calling a function directly. Getting this process boundary wrong is the most likely place a first implementation attempt goes wrong.

**DB state:**
- `user_notification_preferences` (`supabase/migrations/20260806000000_user_notification_preferences.sql`): PK `user_id`, the 4 boolean columns above, RLS with standard own-row policies.
- **No idempotency/sent-tracking table or column exists anywhere.** Without one, an ARQ retry of `content_pipeline_job`, or any duplicate enqueue of the notification job, would send the same "lesson ready" email twice. This is exactly the check-then-act class of bug this project has already registered once (**D45** — a pre-check with no UNIQUE constraint behind it let concurrent duplicates both bill) — this story must not repeat it.

**Existing conventions to reuse, not reinvent:**
- ARQ job registration is a plain list: `apps/api/app/workers/main.py:103-109`'s `functions = [content_pipeline_job, book_ingest_job, # Add future jobs here:]`. A new `send_notification_email_job` follows the same `(ctx: dict, ...) -> dict[str, Any]` shape and gets added to this list.
- Retry/backoff is already built: `apps/api/app/core/retry.py:208`'s `with_retry(max_attempts=3)` decorator already implements CLAUDE.md §14's exact spec (`_RETRYABLE_STATUS_CODES = {429,500,502,503,504}`, `_NON_RETRYABLE_STATUS_CODES = {400,401,403,404,422}`). The Resend API call must use this decorator directly, not a new hand-rolled retry loop.
- CLAUDE.md principle 5 ("Provider abstraction everywhere — no direct provider client calls in business logic") applies here exactly as it does to LLM/TTS/Image providers — the ARQ job must not call the Resend SDK/HTTP API directly; it goes through a new `providers/email/` abstraction.

## Acceptance Criteria

1. **AC-1 (migration)** — a new Supabase migration adds a `notification_log` table: `id` (uuid, pk), `user_id` (uuid, fk → users), `notification_type` (text, `'lesson_ready'` | `'session_report'`), `resource_id` (text — the `lesson_id` or `session_id`), `sent_at` (timestamptz, default now()). A **UNIQUE constraint on `(user_id, notification_type, resource_id)`** is the actual idempotency guard — not an app-level pre-check alone (per the D45 precedent in Dev Notes). RLS denies all direct client access (service-role only; no frontend ever reads this table).
2. **AC-2 (provider abstraction)** — a new `apps/api/app/providers/email/` module defines an `EmailProvider` interface and a `ResendEmailProvider` implementation, matching the shape of this repo's existing LLM/TTS/Image provider abstractions. `RESEND_API_KEY` is a new `pydantic-settings` field in `config.py` — never hardcoded, never read via a bare `os.environ` call outside `config.py`.
3. **AC-3 (templates)** — two HTML email templates (lesson ready, session report), matching the copy already specified in `docs/bmad/epics/epic-5-platform-core.md` §"Email Notifications" ("Your lesson is ready! [Open Lesson]", "Here's how you did — [View Report]"), linking to the real frontend routes (`/lesson/{lesson_id}`, `/reports/{session_id}`) via a `FRONTEND_URL` setting (reuse if one already exists in `config.py`; add it if not).
4. **AC-4 (the ARQ job)** — `send_notification_email_job(ctx, user_id, notification_type, resource_id)`:
   - Reads `user_notification_preferences` for the relevant boolean flag; if the student has opted out, exit early — this is a normal no-op, not an error or a retry.
   - Attempts to **claim** the send via `INSERT INTO notification_log (...) ON CONFLICT (user_id, notification_type, resource_id) DO NOTHING RETURNING id`. If no row is returned (conflict — already sent or already claimed by a concurrent invocation), exit early without calling the email provider. This claim-before-send ordering, not a separate SELECT-then-INSERT, is what makes AC-4 safe under concurrent enqueues (Scale & Load Q6).
   - Only after successfully claiming, calls `ResendEmailProvider` (via the AC-2 abstraction) wrapped in the existing `with_retry(max_attempts=3)` decorator.
   - On final failure after retries exhausted: log the failure clearly (structured log, and/or Sentry capture per this repo's existing Sentry wiring) so it is discoverable — never silently swallowed (CLAUDE.md's "silent truncation is never acceptable" applies to delivery failures too) — but never crash the ARQ worker process or block the pipeline/session-end flow that triggered it, since that flow already completed successfully on its own.
5. **AC-5 (wiring)** — both trigger points enqueue the job:
   - `content_pipeline_job` (`content_pipeline.py`, alongside the existing `lesson_ready:{lesson_id}` pub/sub publish) enqueues `send_notification_email_job` with `notification_type='lesson_ready'`.
   - `session_end_node`'s `_finalize_session` (`graph.py:724`) enqueues the same job with `notification_type='session_report'`, via the ARQ redis pool's `enqueue_job()` call — explicitly across the FastAPI-process → ARQ-worker-process boundary, not a direct function call (see Dev Notes' warning above).
6. **AC-6 (tests)** — pytest coverage for: the opt-out skip path, the idempotent-claim behavior (two concurrent/duplicate invocations for the same `(user_id, notification_type, resource_id)` result in exactly one real provider call — testable against a real Postgres unique constraint in the test DB, not simulated only via a mock), the `with_retry` integration (retryable vs. non-retryable status codes), and — per `docs/DEFECT-REGISTER.md` binding rule 3 — an executable premise test proving the Resend SDK's exception type hierarchy is what the failure-handling code assumes, if it catches any Resend-specific exception type.

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** one email send, per (user, notification_type, resource) triple. Volume is bounded by real usage — one lesson-ready email per lesson generated, one session-report email per completed session. At current expected launch volume (a handful of students), this is tens to low hundreds of emails/month, nowhere near any provider's rate limits.
2. **Fixed budgets vs. variable input:** `with_retry(max_attempts=3)` is the only fixed budget in this story, already established and justified elsewhere in the codebase (CLAUDE.md §14) — not newly invented here. Past 3 attempts, the job fails explicitly (logged/Sentry-captured per AC-4), never silently.
3. **Scope of every limit:** the `notification_log` UNIQUE constraint is scoped per `(user_id, notification_type, resource_id)` — i.e., per specific email, not a broader per-user or per-instance limit. No rate limiting is introduced by this story; Resend's own account-level sending limits are out of scope (an ops/account concern, not a code concern).
4. **Unbounded reads/writes:** none introduced. Every read/write in this story's job is a single-row operation keyed by a specific ID (the preference lookup, the `notification_log` claim, the email send itself) — no list/range queries.
5. **Inherited caps re-derived:** N/A — no cap is inherited from an earlier design; the retry cap is a fresh application of an already-correct existing utility (`with_retry`).
6. **Concurrent check-then-act safety:** this is the load-bearing question for this story. AC-4's claim-via-`INSERT...ON CONFLICT...RETURNING` pattern is deliberately NOT a `SELECT` followed by a conditional `INSERT` — that shape is exactly what produced **D45** (duplicate billing under concurrent requests) elsewhere in this codebase. The atomic insert-with-conflict-check is the fix, and it must be verified under an actual concurrent-call test (AC-6), not just unit-tested in isolation.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1): Write the `notification_log` migration with its UNIQUE constraint and RLS policy.
  - [ ] 1.1 RED: a test asserting the UNIQUE constraint actually rejects a duplicate `(user_id, notification_type, resource_id)` insert at the DB level.
  - [ ] 1.2 GREEN: write and apply the migration.
- [ ] Task 2 (AC: 2, 3): Build the `EmailProvider`/`ResendEmailProvider` abstraction and the two HTML templates.
  - [ ] 2.1 RED: a test proving business logic never imports the Resend SDK directly (only through the abstraction).
  - [ ] 2.2 GREEN: implement.
- [ ] Task 3 (AC: 4, 6): Implement `send_notification_email_job` (opt-out check, atomic claim, provider call via `with_retry`, failure logging).
  - [ ] 3.1 RED: write failing tests for the opt-out skip, the idempotent claim under concurrency, the retry integration, and the exception-hierarchy premise test.
  - [ ] 3.2 GREEN: implement.
- [ ] Task 4 (AC: 5): Wire both trigger points (`content_pipeline_job`, `session_end_node`'s `_finalize_session`), register the job in `workers/main.py`.
  - [ ] 4.1 RED: tests asserting each trigger point enqueues the job with the correct `notification_type`/`resource_id`/`user_id`.
  - [ ] 4.2 GREEN: implement.
- [ ] Task 5 (AC: 6): Full `apps/api` suite green; premise/exception-hierarchy test included per DEFECT-REGISTER binding rule 3.

## Dev Notes

### What NOT to do

- Do NOT build `weekly_progress_email`/`streak_reminders` sending — no trigger/cron exists for either, and this story's title explicitly scopes to lesson-ready and session-report only. Building a send path with nothing to call it would be dead code.
- Do NOT call the Resend SDK/HTTP API directly from `content_pipeline.py`, `graph.py`, or the ARQ job itself — always through the AC-2 provider abstraction, matching CLAUDE.md principle 5.
- Do NOT implement idempotency as an app-level `SELECT ... WHERE ...` followed by a conditional `INSERT` — that exact shape is **D45**, already a registered defect elsewhere in this codebase. Use the atomic `INSERT ... ON CONFLICT ... RETURNING` claim pattern from AC-4.
- Do NOT call `_finalize_session`'s email enqueue as a direct Python function call across the process boundary — `session_end_node` runs in the FastAPI/WebSocket process; the ARQ job runs in a separate worker process. Use the ARQ redis pool's `enqueue_job()`, not an in-process call.
- Do NOT add a frontend delivery-status UI ("email sent ✓") — not asked for, and the frontend half of this feature is explicitly complete and out of scope for this story.

### Testing standards

Pytest, matching this repo's existing `apps/api/tests/unit/` conventions. The concurrency test for AC-4's idempotent claim should run against a real (test) Postgres instance to actually exercise the UNIQUE constraint — a mocked DB layer cannot disconfirm a race condition, per `docs/DEFECT-REGISTER.md`'s binding rule 2 ("no test may assert only on a mock it constructed").

### References

- [Source: docs/master-tracker.md, Dev 2 Sprint 4 section] — origin of this task, assigned S4-12 here since it had no story or tracker number before, and reprioritized ahead of S4-02 by the user on 2026-08-25.
- [Source: apps/api/app/core/retry.py:208] — the `with_retry` decorator this story's provider call must reuse, not reimplement.
- [Source: apps/api/app/workers/main.py:103-109] — the real ARQ job registration pattern this story's new job follows.
- [Source: docs/DEFECT-REGISTER.md, D45] — the check-then-act-without-a-UNIQUE-constraint defect class this story's AC-4 is explicitly designed to avoid repeating.
- [Source: docs/bmad/epics/epic-5-platform-core.md, "Email Notifications" section] — the original copy/trigger spec this story implements against, with its stale `backend/` paths corrected to the real `apps/api/app/` structure.

## Dev Agent Record

### Implementation Plan

_(filled in during implementation)_

### Completion Notes

_(filled in during implementation)_

### File List

_(filled in during implementation)_

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-25 | Story created after a read-only audit of both `apps/web` and `apps/api` found the frontend half of this feature already complete (S3-07) and the backend half fully greenfield (zero existing email-sending code). Reprioritized by the user ahead of S4-02 (Razorpay). Branch `sprint4/s4-12-email-notifications` off `main`. Crosses into `apps/api` (Dev 1's normal domain) under the same explicit-user-approval precedent as S4-06 — implementation not yet started, pending explicit go-ahead given this repo's standing "no backend work without explicit permission" constraint. | Dev 2 |
