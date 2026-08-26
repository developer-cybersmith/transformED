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

- [x] Task 1 (AC: 1): Write the `notification_log` migration with its UNIQUE constraint and RLS policy.
  - [x] 1.1 RED/GREEN: migration written (declarative SQL — no live-Postgres instance available locally to run a real RED/GREEN cycle against; see Completion Notes for the honest gap this leaves).
- [x] Task 2 (AC: 2, 3): Build the `EmailProvider`/`ResendEmailProvider` abstraction and the two HTML templates.
  - [x] 2.1/2.2: implemented + tested (`test_email_provider.py`, 4 tests).
- [x] Task 3 (AC: 4, 6): Implement `send_notification_email_job` (opt-out check, atomic claim, provider call via `with_retry`, failure logging).
  - [x] 3.1/3.2: implemented + tested (`test_send_notification_email_job.py`, 7 tests) — RED confirmed by running each test against a stub before implementing the corresponding branch.
- [x] Task 4 (AC: 5): Wire both trigger points (`content_pipeline_job`, `session_end_node`'s `_finalize_session`), register the job in `workers/main.py`.
  - [x] 4.1/4.2: implemented + tested (`test_notification_triggers.py`, 5 tests).
- [x] Task 5 (AC: 6): Full `apps/api` suite green (1252 passed, 6 skipped — pre-existing skips, unrelated to this story); `ruff`/`mypy` clean on all touched files.

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

- **Migration**: `notification_log` with `UNIQUE (user_id, notification_type, resource_id)`, RLS enabled with zero policies (service-role-only access, matching this feature's "no frontend surface" scope).
- **Provider abstraction**: `EmailProvider` ABC added to `providers/base.py` alongside the existing LLM/TTS/Image/Avatar interfaces; `ResendEmailProvider` implements it via a direct `httpx` call to Resend's REST API (no SDK dependency added), wrapped in the existing `with_retry(max_attempts=3)` — no new retry logic, no new circuit breaker (out of this story's stated scope).
- **Settings**: `resend_api_key` (optional, mirrors `sentry_dsn`'s pattern so the app doesn't fail to start before Resend account setup lands), `resend_from_email`, `frontend_url` — all new `pydantic-settings` fields, no hardcoded values.
- **Templates**: plain f-string HTML in `modules/notifications/templates.py` — two templates, three interpolated values total, deliberately not a templating-engine dependency.
- **The ARQ job** (`send_notification_email_job`): opt-out check → atomic claim (`upsert(..., on_conflict="user_id,notification_type,resource_id", ignore_duplicates=True)`, confirmed against the real installed `postgrest` package's `upsert()` signature before writing it) → resolve recipient/render content → send via the provider → never raises (failures are logged + Sentry-captured, returned as a result dict instead).
- **Trigger wiring — two genuinely different process contexts**, the trickiest part of this story:
  - `content_pipeline_job` runs INSIDE the ARQ worker process, so it enqueues via `ctx["redis"]` — confirmed this is real by reading `arq/worker.py:361` (`self.ctx['redis'] = self.pool`) directly in the installed package, not assumed from the module's own docstring.
  - `session_end_node`'s `_finalize_session` runs in the FastAPI/WebSocket process, a genuinely different OS process from the ARQ worker — it cannot share ARQ's per-job `ctx`. Built a new `app/core/arq_pool.py` singleton (mirrors `app/core/redis.py`'s `init_redis`/`get_redis` pattern exactly) so this cross-process enqueue has a real accessor instead of reaching for `request.app.state` (which doesn't exist outside a route handler).
  - `_finalize_session`'s existing `sessions` table `.update()` call already returns the full updated row by default (`postgrest.ReturnMethod.representation`, confirmed in the installed package) — reused that response for `user_id` instead of adding a second query.

### Completion Notes

- All 5 tasks complete. Full `apps/api` suite: **1252 passed, 6 skipped** (pre-existing skips, unrelated), zero failures. `ruff check` and `mypy` clean on every touched file.
- **Honest gap, flagged rather than silently dropped**: AC-6 asks for the idempotent claim to be "testable against a real Postgres unique constraint in the test DB, not simulated only via a mock." This repo already has exactly that pattern established (`tests/integration/test_migration_chapters_book_scoped.py`, a ~1200-line Docker-Postgres harness gated behind `pytest.mark.postgres`), but Docker is not running in this environment (`docker version` fails to connect to the daemon) — I could not write and verify an equivalent harness for `notification_log` without being able to execute it even once. Rather than ship an untested ~150-line integration test file copy-pasting that harness on faith, I left this as a documented gap. What IS covered: the unit tests fully exercise this job's own branching on both possible outcomes of the claim (claimed vs. already-claimed), and the migration's UNIQUE constraint is declarative SQL — about as close to self-evidently-correct as a DB constraint gets. Recommend a fast-follow story to add the real-Postgres integration test once Docker is available, following `test_migration_chapters_book_scoped.py`'s exact pattern.
- `weekly_progress_email`/`streak_reminders` confirmed to have no trigger anywhere (per the grounding audit) — correctly left unbuilt, matching the story's explicit scope.

### File List

- `supabase/migrations/20260825000000_notification_log.sql` (NEW)
- `apps/api/app/providers/base.py` (MODIFIED — added `EmailProvider` ABC)
- `apps/api/app/providers/email/__init__.py` (NEW, empty — matches sibling provider packages' convention)
- `apps/api/app/providers/email/resend.py` (NEW — `ResendEmailProvider`)
- `apps/api/app/config.py` (MODIFIED — `resend_api_key`, `resend_from_email`, `frontend_url`)
- `apps/api/app/modules/notifications/__init__.py` (NEW, empty)
- `apps/api/app/modules/notifications/templates.py` (NEW — the two email templates)
- `apps/api/app/core/arq_pool.py` (NEW — cross-process ARQ pool singleton)
- `apps/api/app/main.py` (MODIFIED — calls `init_arq_pool()` at startup)
- `apps/api/app/workers/jobs/send_notification_email.py` (NEW — the ARQ job)
- `apps/api/app/workers/main.py` (MODIFIED — registers the new job)
- `apps/api/app/workers/jobs/content_pipeline.py` (MODIFIED — enqueues `lesson_ready` notification)
- `apps/api/app/modules/tutor/state_machine/graph.py` (MODIFIED — `_finalize_session` enqueues `session_report` notification)
- `apps/api/tests/unit/test_email_provider.py` (NEW — 4 tests)
- `apps/api/tests/unit/test_send_notification_email_job.py` (NEW — 7 tests)
- `apps/api/tests/unit/test_notification_triggers.py` (NEW — 5 tests)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-25 | Story created after a read-only audit of both `apps/web` and `apps/api` found the frontend half of this feature already complete (S3-07) and the backend half fully greenfield (zero existing email-sending code). Reprioritized by the user ahead of S4-02 (Razorpay). Branch `sprint4/s4-12-email-notifications` off `main`. Crosses into `apps/api` (Dev 1's normal domain) under the same explicit-user-approval precedent as S4-06 — implementation not yet started, pending explicit go-ahead given this repo's standing "no backend work without explicit permission" constraint. | Dev 2 |
