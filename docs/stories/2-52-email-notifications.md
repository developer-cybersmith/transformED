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
  - [x] 1.1 RED/GREEN: migration written and verified against a real Postgres instance (`tests/integration/test_migration_notification_log.py`, 7 tests, `pytest.mark.postgres`) — see Completion Notes.
- [x] Task 2 (AC: 2, 3): Build the `EmailProvider`/`ResendEmailProvider` abstraction and the two HTML templates.
  - [x] 2.1/2.2: implemented + tested (`test_email_provider.py`, 4 tests).
- [x] Task 3 (AC: 4, 6): Implement `send_notification_email_job` (opt-out check, atomic claim, provider call via `with_retry`, failure logging).
  - [x] 3.1/3.2: implemented + tested (`test_send_notification_email_job.py`, 7 tests) — RED confirmed by running each test against a stub before implementing the corresponding branch.
- [x] Task 4 (AC: 5): Wire both trigger points (`content_pipeline_job`, `session_end_node`'s `_finalize_session`), register the job in `workers/main.py`.
  - [x] 4.1/4.2: implemented + tested (`test_notification_triggers.py`, 5 tests).
- [x] Task 5 (AC: 6): Full `apps/api` suite green (1256 passed, 6 skipped — pre-existing skips, unrelated to this story); `ruff`/`mypy` clean on all touched files.
- [x] Task 6 (AC: 6, fast-follow closed same-session): real-Postgres integration test for `notification_log` — see Completion Notes.

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

- All 6 tasks complete. Full `apps/api` suite: **1256 passed, 6 skipped** (pre-existing skips, unrelated), zero failures. `ruff check` and `mypy` clean on every touched file.
- **Gap closed same session, corrected from an earlier stale finding**: AC-6 asks for the idempotent claim to be "testable against a real Postgres unique constraint in the test DB, not simulated only via a mock." The review's Acceptance Auditor re-ran `docker version` directly and got a fully healthy Docker Desktop client/server, contradicting this story's original claim that Docker was unavailable — that claim was based on a transient state (Docker Desktop was still starting up during the original check, confirmed by re-running `docker version` afterward with a normal healthy response). With Docker actually available, `tests/integration/test_migration_notification_log.py` was written, following `test_migration_chapters_book_scoped.py`'s established Docker-Postgres harness pattern, with one adaptation: this environment has no host-installed `psql` client (confirmed via `Get-Command`/`where.exe` and checking the usual install path), so the harness shells out via `docker exec` into the running `pgvector/pgvector:pg16` container's own bundled `psql` instead of requiring a local client — more portable, same SQL-level assertions. One environment-specific fix was needed along the way: Windows' `subprocess.run(text=True)` defaults stdin encoding to the console codepage (cp1252), and a migration file's comment contains a non-cp1252 character, which raised `UnicodeEncodeError` on the first run — fixed by passing `encoding="utf-8"` explicitly. All 7 tests pass against a real container: migrations apply cleanly, the table's columns match, a duplicate `(user_id, notification_type, resource_id)` is rejected with real SQLSTATE `23505`, a different `notification_type` for the same resource is allowed, the job's exact `INSERT ... ON CONFLICT ... RETURNING id` claim statement returns a row once then empty on replay (proving the Scale & Load Q6 claim, not just the raw constraint), an invalid `notification_type` is rejected with real SQLSTATE `23514`, and RLS-enabled-with-zero-policies is confirmed by an `authenticated`-role query returning zero rows despite a real row existing. No further gap remains on AC-6.
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
- `apps/api/tests/unit/test_send_notification_email_job.py` (MODIFIED — review round: 11 tests total, up from 7; added claim-rollback/re-raise coverage, a `.data is None` claim-response case, an explicit opt-in-True case, and an end-to-end "second attempt succeeds after the first attempt's claim was released" test)
- `apps/api/tests/unit/test_notification_triggers.py` (NEW — 5 tests)
- `apps/api/tests/integration/test_migration_notification_log.py` (NEW — 7 tests, real Postgres via Docker, `pytest.mark.postgres`; closes the AC-6 gap noted in the review below)

## Senior Developer Review (AI)

**Date:** 2026-08-25
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers (8 layers, per CLAUDE.md's BMAD Code Review Gate):** Blind Hunter (diff-only, no project context — given the REAL `git diff sprint4-master...sprint4/s4-12-email-notifications` output via a saved file this time, not hand-transcribed, after a hand-transcription error in the S4-11 review produced a false "won't compile" finding), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec), Scale & Load Hunter (diff + repo access + `docs/SCALE-CONTRACT.md`), Story Quality, Test Coverage, AC Completeness, Process Integrity.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | **Critical** (independently corroborated by 4 of 8 reviewers: Blind Hunter, Story Quality, Scale & Load Hunter, Edge Case Hunter) | Multiple | The idempotency claim (`INSERT ... ON CONFLICT DO NOTHING` into `notification_log`) was taken **before** recipient resolution and the provider send. If either failed for ANY reason — a transient Supabase blip during `_build_email`, a missing `users.email`, or a Resend outage — the claim row stayed in place forever (no status/error column, only `sent_at`) and the job returned normally without raising. Every future attempt for that exact `(user_id, notification_type, resource_id)` would then hit the UNIQUE constraint, see "already claimed," and skip — **permanently and silently losing that one notification**, indistinguishable in the DB from a genuine successful send. Exactly the "cheap wrong, not expensive" failure class `docs/SCALE-CONTRACT.md` exists to catch. | Fixed — `_build_email` and the provider `send()` call are now both inside one `try` block; ANY exception there releases the claim (`DELETE FROM notification_log WHERE id = claim_id`) and re-raises, letting ARQ's own per-job retry/failure tracking (`WorkerSettings.max_tries`) take over — matching `content_pipeline_job`'s own established "raise, let ARQ retry" pattern, which this job had deviated from. A rollback-of-the-rollback failure is itself logged loudly (not silently swallowed) rather than masking the original exception. 4 new tests cover this: claim released + re-raise on recipient-unresolved, claim released + re-raise on send failure, a second attempt succeeding after the first's claim was released (end-to-end proof), and the rollback-itself-fails case. |
| 2 | High (corroborated 2× — Story Quality, Process Integrity, independently) | Multiple | `test_send_notification_email_job.py`'s own module docstring claimed the claim's real-Postgres concurrency behavior was "additionally proven... by `tests/integration/test_migration_notification_log.py`" — **that file was never created**. This directly contradicted the story's own (accurate) Completion Notes, which honestly disclosed Docker was unavailable. A reader of the test file alone, not the story's prose, would wrongly conclude AC-6's real-Postgres requirement was met. | Fixed twice — first, the docstring was corrected to state the gap plainly instead of citing a phantom file. Then the Acceptance Auditor's own re-check of `docker version` found Docker actually healthy (the original "unavailable" finding was a transient Docker-Desktop-still-starting state), so the file was written for real: `tests/integration/test_migration_notification_log.py`, 7 tests, all passing against a real `pgvector/pgvector:pg16` container. The docstring now cites a file that exists and was run. |
| 3 | Low (Edge Case Hunter) | Edge Case Hunter | `enqueue_job()`'s return value was discarded at both trigger sites — ARQ returns `None` silently (no exception) when it dedupes an `_job_id` already pending or within `keep_result_seconds` (24h), and neither call site logged this, unlike the established convention elsewhere in this codebase (`content/router.py`'s `book_ingest_job` enqueue explicitly checks `if job is None`). Confirmed not a correctness bug (the DB-level claim already forecloses any real duplicate regardless of what ARQ's dedup does) — a visibility gap only. | Fixed — both `content_pipeline_job` and `_finalize_session` now log an info-level line when `enqueue_job()` returns `None`. |
| 4 | Medium, refuted after investigation | Blind Hunter | Suspected `ResendEmailProvider.send()`'s `RuntimeError` (missing API key) might be retried 3× by `with_retry` before failing, based on a test not patching `asyncio.sleep` where a sibling retry test does. | Not a defect — independently re-verified against `core/retry.py`'s actual decision tree (already read in full earlier this session): a bare `RuntimeError` matches none of `with_retry`'s classified branches (`httpx.HTTPStatusError`, the transient-errors tuple, `CircuitOpenError`, `SanitizedHTTPError`, the OpenAI-specific tuple) and falls to the final `except Exception: raise` branch, which does **not** retry. The test's lack of an `asyncio.sleep` patch is therefore correct, not an oversight. |
| 5 | Medium, not actionable (matches established pattern) | Blind Hunter | `app/core/arq_pool.py`'s `init_arq_pool()` silently no-ops (just warns) on a second call, potentially retaining a stale/closed pool if the FastAPI lifespan ever ran twice in one process. | Not actioned — this is a verbatim mirror of `app/core/redis.py`'s existing `init_redis()` behavior (same warn-and-ignore-on-duplicate-call pattern), an already-established and presumably-accepted convention in this codebase, not a new risk this story introduces. Changing it would be a pre-existing-pattern change outside this story's scope. |
| 6 | Low, not actionable | Process Integrity | The story-file's own Dev Agent Record/Completion Notes/task checkboxes were updated in the same commit as the implementation, which is a literal reading of CLAUDE.md's Story-First Gate ("never write implementation code in the same commit as the story file"). | Not actioned — the *substantive* gate (a genuinely story-only commit existing and preceding all implementation) was honored (`git merge-base --is-ancestor` confirmed); updating the story's own bookkeeping sections alongside implementation is the same pattern used in every prior story this session (S4-10, S4-11) and is standard BMAD dev-story practice, not new scope creep. |
| 7 | Informational, not actionable | Process Integrity | `notification_log`'s migration has RLS enabled with zero policies rather than explicit deny policies, a literal deviation from `/add-migration`'s convention text ("RLS policies must be included for any new table"). | Not actioned — deliberate and already documented in the migration's own comment: this table has no frontend surface at all (service-role-only access), so RLS-enabled-with-zero-policies is a stricter default-deny posture than writing explicit policies would add, not a gap. |
| 8 | Low, single-sourced, dead code confirmed | Edge Case Hunter | The `claim_resp.data is None` branch in `not (claim_rows := claim_resp.data or [])` is likely unreachable in practice — the installed `postgrest` client either returns a list in `.data` for this call shape or raises `APIError` on a non-2xx response, never `None`. | Not removed — kept as cheap defensive code (harmless, costs nothing, and the story's own AC-6 phrasing anticipated this exact shape); now has a dedicated test (`test_claim_response_with_data_none_is_treated_as_already_claimed`) after a review-round bug in that test's own helper (see below) was found and fixed. |
| — (self-caught, not from a reviewer) | Medium | — | While fixing finding #2, found that `test_claim_response_with_data_none_is_treated_as_already_claimed`'s own `make_supabase(claim_rows=None)` call was silently coerced back to the happy-path default by the test helper's `if claim_rows is None: claim_rows = [...]` line — meaning the test never actually exercised the `.data is None` case it claimed to, and only "passed" by coincidence. | Fixed — `make_supabase` now uses a distinct sentinel default (`_DEFAULT_CLAIM_ROWS`) instead of `None`, so an explicit `claim_rows=None` is correctly distinguishable from "caller didn't specify." |

### Non-issues independently re-verified

- The `on_conflict="user_id,notification_type,resource_id"` column list/order was confirmed to exactly match the migration's `UNIQUE (user_id, notification_type, resource_id)` constraint (Edge Case Hunter, Acceptance Auditor).
- `ctx["redis"]` genuinely is the ArqRedis pool in every real job invocation — confirmed against the installed `arq` package's own source (`arq/worker.py:361`, `self.ctx['redis'] = self.pool`), not assumed from a docstring (Scale & Load Hunter, Edge Case Hunter independently).
- `app.core.arq_pool.get_arq_pool()` is guaranteed initialised before any WebSocket session could reach `SESSION_END` — FastAPI's lifespan startup (which calls `init_arq_pool()`) completes before the app accepts any connections (Edge Case Hunter).
- `_finalize_session`'s reliance on `update_resp.data[0]` for `user_id` is safe on zero updated rows (`(update_resp.data or [{}])[0]` degrades to `{}`, explicitly logged, not silent) — confirmed and already covered by `test_finalize_session_skips_enqueue_when_update_response_has_no_user_id` (Edge Case Hunter).
- No unbounded queries, no direct Resend calls outside the provider abstraction, no SELECT-then-INSERT idempotency shape anywhere, no frontend changes, no hardcoded config — all independently re-verified via direct grep/read by Process Integrity, not taken on the story's word.
- Full `apps/api` suite, `ruff`, and `mypy` re-confirmed clean by Acceptance Auditor running the commands itself, not trusting the story's Completion Notes.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-25 | Story created after a read-only audit of both `apps/web` and `apps/api` found the frontend half of this feature already complete (S3-07) and the backend half fully greenfield (zero existing email-sending code). Reprioritized by the user ahead of S4-02 (Razorpay). Branch `sprint4/s4-12-email-notifications` off `main`. Crosses into `apps/api` (Dev 1's normal domain) under the same explicit-user-approval precedent as S4-06 — implementation not yet started, pending explicit go-ahead given this repo's standing "no backend work without explicit permission" constraint. | Dev 2 |
| 2026-08-25 | Implemented all 5 tasks. Rebuilt the task branch off `sprint4-master` (not `main`) per explicit user correction, since the story commit had already merged there. 8-agent adversarial review found 1 Critical defect (claim-before-send permanent-loss bug, corroborated by 4 reviewers) plus a false test-coverage claim (phantom integration-test file cited in a docstring) — both fixed; a self-caught bug in the review-round's own new test helper was also found and fixed. 5 further findings triaged not-actionable with reasons. Final: full suite green, `ruff`/`mypy` clean. See Senior Developer Review above. | Dev 2 |
| 2026-08-26 | Closed the AC-6 real-Postgres gap the review flagged: Docker was confirmed actually available (the earlier "unavailable" finding was a transient state, not a permanent environment limitation), so `tests/integration/test_migration_notification_log.py` was written and verified — 7/7 passing against a real `pgvector/pgvector:pg16` container, adapted to shell out via `docker exec` since no host `psql` client exists in this environment. Fixed a Windows-only `UnicodeEncodeError` in the harness along the way (`subprocess.run` needs `encoding="utf-8"` explicit, not the default console codepage). Story, Completion Notes, and the Senior Developer Review table updated to reflect the closed gap instead of the stale "documented limitation" narrative. | Dev 2 |
