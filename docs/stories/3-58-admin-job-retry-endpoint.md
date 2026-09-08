# Story 3-58 — S3-4: Admin panel — job status, cost tracking, failed jobs

**Branch:** `sprint3/s3-4-admin-panel-job-cost-tracking` (from `main`).
**Owner:** Dev 1.
**Tracker source:** `docs/dev1-tracker.md` S3-4 — "`apps/api/app/modules/admin/router.py`
*(to create)*. Endpoints: `GET /api/admin/jobs`, `POST /api/admin/jobs/{job_id}/retry`,
`GET /api/admin/costs`. **AC:** All jobs listable with status + cost; failed jobs retryable via
single API call; cost per lesson and per user visible."

## Context

The tracker's "(to create)" is stale — `admin/router.py` already exists (295 lines), built across
Story 2-25 (`require_admin` gating) and this session's own D59(a) fix (bounded the cost-report
query). Read it fresh before writing this story, not assumed from the tracker's wording:

- `GET /jobs` (`list_jobs`) — exists, matches the AC's `GET /api/admin/jobs` exactly. Each
  `JobSummary` already carries `cost_usd` — **"cost per lesson" is already satisfied.**
- `GET /jobs/{job_id}` (`get_job`) — exists, a bonus single-job detail view, not in the AC.
- `GET /costs` (`get_cost_report`) — exists, matches `GET /api/admin/costs`, already returns
  `by_user: list[{"user_id", "cost_usd"}]` — **"cost per user" is already satisfied.**
- `GET /health` (`deep_health`) — exists, unrelated to this AC.

**The one real gap: `POST /jobs/{job_id}/retry` does not exist.** That is the entire scope of
this story — the AC's other two clauses are already true today.

**What "retry" must actually do — investigated, not assumed:**

- `content_pipeline_job(ctx, lesson_id)` (`workers/jobs/content_pipeline.py:23`) takes only
  `lesson_id` — it re-fetches `user_id`/`chapter_id`/`tier`/`source_file_path` fresh from the
  `lessons` row every time. **Retrying never needs to re-validate ownership, chapter existence, or
  page-span** — those were already checked when the lesson was first created; re-enqueuing the
  same `lesson_id` is sufficient.
- Resume is real and already correct: `graph.py:5602`'s own comment — *"Resume MUST be rebuilt
  from the durable Supabase `node_outputs`"* — confirms `run_pipeline` reads
  `lesson_jobs.node_outputs`/`last_node` to skip already-completed nodes. **The retry endpoint
  must NOT clear those columns** — only `status` (and `error`, cosmetically) — or a job that died
  on `image_generator` would silently re-run and re-bill `lesson_planner` through `tts_node`.
- **A real thread_id-uniqueness trap, already named in this exact file's own comment**
  (`content_pipeline.py:112-114`): *"TRAP: `ctx['job_id']` alone is NOT a uniquifier — router.py
  pins `_job_id=f'pipeline:{lesson_id}'` for enqueue-dedup, so it is byte-identical on every
  retry. `job_try` is what actually varies."* That comment describes ARQ's own internal retry
  loop, where ARQ increments `job_try` for the SAME in-flight `_job_id`. It does **not** establish
  what happens when a completely NEW `enqueue_job()` call reuses the same `_job_id` string after
  the original job already finished (success or final failure) — whether ARQ resets `job_try` to
  1 for that fresh call is not something this story verifies from ARQ's internals, and CLAUDE.md's
  own binding rule on this exact subject (`thread_id` must be unique per pipeline *attempt*, not
  just per `lesson_id`) is unambiguous that reuse is the unsafe direction. **The safe, minimal
  fix that needs zero changes to `graph.py`/`content_pipeline.py`:** mint a fresh, uniquified ARQ
  `_job_id` per admin-triggered retry (e.g. `f"pipeline:{lesson_id}:retry:{token}"`). Since
  `attempt = f"{ctx.get('job_id')}:{ctx.get('job_try', 1)}"` already derives from `ctx['job_id']`
  (i.e. the `_job_id` I choose), a fresh `_job_id` guarantees a fresh `thread_id` regardless of
  `job_try`'s reset behavior — sidestepping the ambiguity entirely rather than depending on it.

## The fix

New endpoint, `admin/router.py`:

```
POST /jobs/{job_id}/retry
```

1. Validate `job_id` as a UUID (matches `get_job`'s existing pattern) — 404 on malformed input,
   same as `get_job`, not a 422 that would leak "this endpoint validates UUID shape" to an
   unauthenticated-shaped probe.
2. Look up the `lesson_jobs` row by `job_id`. 404 if absent.
3. **Only `failed` jobs are retryable** (the AC's own wording) — `409 Conflict` if the job's
   current status is `pending`/`running`/`completed`, naming the actual status in the response so
   the caller knows why.
4. Reset `lessons.status` → `generating` and `lesson_jobs.status` → `pending`, clear
   `lesson_jobs.error` — mirrors `generate_chapter_lesson`'s own initial-creation state, so the
   job doesn't sit displaying `failed` in `GET /jobs` for the window between this call returning
   and the worker actually picking it up. `node_outputs`, `last_node`, and `cost_usd` are
   deliberately left untouched (resume + real-spend accounting, both explained above).
5. Re-enqueue via `arq_redis.enqueue_job("content_pipeline_job", lesson_id, _job_id=f"pipeline:
   {lesson_id}:retry:{uuid4().hex[:8]}")`. `job is None` (ARQ deduplicated) is treated as a real
   500 — it should be unreachable given the fresh id, and silently returning 202 anyway would
   claim a retry that never actually got enqueued.
6. Return 202 with the job id, lesson id, and new status — same acceptance shape as
   `generate_chapter_lesson`'s 202, not a bespoke response shape for no reason.

## What this story does NOT do

- Does not touch `GET /jobs` or `GET /costs` — both already satisfy their AC clauses, confirmed by
  reading the current code, not assumed from the tracker's stale "(to create)".
- Does not add a "retry all failed jobs" bulk endpoint — the AC says "via single API call" (one
  job, one call), not a bulk operation; out of scope unless asked for separately.
- Does not touch `generate_chapter_lesson` (D54's `force=true` endpoint) — that creates a NEW
  lesson row for a user-facing regeneration request; this retries the EXISTING failed job by its
  own `lesson_id`, a different operation with different auth (admin, not the lesson's owner) and
  different rate-limiting concerns (D54's endpoint is user-rate-limited per PRD spend controls;
  this is an operator action and is not subject to that same per-user limiter).
- Does not modify `content_pipeline_job`, `run_pipeline`, or any LangGraph node — the fresh
  `_job_id` per retry is sufficient; no change to the checkpoint/resume/thread_id mechanism itself.

## Scale & Load

1. **Unit of work & range.** One retry = one job lookup + two status-column updates + one ARQ
   enqueue. No new range — identical shape to the existing job-creation path.
2. **Fixed budgets vs variable input.** N/A — no new budget. The existing $3.00/lesson ceiling and
   `max_chapter_pages` gate are unaffected; a retried job re-enters the pipeline at whatever node
   it stopped on and is still subject to the same ceiling on any further spend.
3. **Scope of the limit.** Per-job, admin-triggered, no per-user rate limit applied (deliberate —
   see "What this story does NOT do"; an admin operator, not the lesson's own rate-limited user,
   is the caller, gated by `require_admin`'s allowlist instead).
4. **Unbounded reads/writes.** N/A — single-row lookups/updates by primary key throughout, no new
   list/range query.
5. **Inherited caps re-derived.** N/A — no cap introduced by this story.
6. **Concurrency.** A genuine check-then-act: the status check (step 3) and the status update
   (step 4) are two separate round-trips with no lock between them — two concurrent retry calls
   for the same `job_id` could both pass the `failed` check and both enqueue. Mitigated, not
   eliminated: each enqueue gets its own fresh `_job_id` (step 5), so a double-retry produces two
   independent, non-colliding pipeline runs rather than a `thread_id` collision — the worse
   failure mode this story's design already prevents. A genuinely exclusive retry (only one of two
   concurrent calls wins) would need a conditional update (`UPDATE ... WHERE status = 'failed'`
   with a rows-affected check) — noted as a real, small follow-up, not fixed here since two
   redundant runs of the SAME already-failed job is a cost nuisance, not the double-billing or
   data-corruption class of bug this session's `D45`-style findings are about.

## Verification

- RED-GREEN: new test file (or added to an existing `test_admin_*.py` if one exists — confirmed
  during implementation) covering: 404 on unknown/malformed `job_id`, 409 on a non-`failed` job
  (parametrized over pending/running/completed), the happy path (status resets, `node_outputs`
  untouched, ARQ `enqueue_job` called with a `_job_id` that is NOT the bare `f"pipeline:
  {lesson_id}"` string), and the `job is None` 500 path.
- Full existing `admin` test suite — confirm zero pre-existing tests broke.
- Full repo-wide regression (`pytest -q` from `apps/api`) — diff against the current baseline,
  confirm zero new failures.
- `ruff check` / `ruff format --check` / `mypy app` clean on touched files.
- Cannot exercise this against a real failed job end-to-end without a real pipeline failure to
  retry — verified at the mock level (ARQ, Supabase) matching this router's own existing test
  conventions, same limitation every other endpoint in this file already has.

## Review Findings

Retroactive 8-layer BMAD review (2026-08-14) — the required 6-agent gate was skipped before the
original merge; run after the fact against `main`. Full findings and triage in the session record;
this section lists what applied to this story specifically.

- [x] [Review][Patch] `retry_job`'s status-reset write was scoped by `lesson_id` (no unique
  constraint) instead of `job_id` (the real primary key) — a lesson with more than one
  `lesson_jobs` row (D45 already documents this as real) could have had an unrelated
  running/completed job silently reset. [`admin/router.py`, the `lesson_jobs` update in `retry_job`]
- [x] [Review][Decision] Concurrent retries silently bypass the $3.00 cost ceiling — resolved:
  quick mitigation (reject if another job for the lesson is active) applied now; full fix
  (DB-level lock/constraint) registered as **D109**, deferred. [`admin/router.py`]
- [x] [Review][Patch] `arq_redis.enqueue_job` exceptions (not just a `None` return) were
  uncaught — status was already reset to generating/pending by that point, leaving the job stuck
  showing `pending` forever. Now caught, status reverted to `failed`. [`admin/router.py`]
- [x] [Review][Patch] Response returned the pre-existing `lesson_jobs.job_id`, not the actual ARQ
  job id enqueued — no way to correlate the response with the running job. Added `arq_job_id`.
  [`admin/router.py`, `JobRetryResponse`]
- [x] [Review][Patch] Test mock used one shared `sb.table.return_value` for both `lessons` and
  `lesson_jobs` — could not have caught a table-name swap bug. Rewritten to table-aware mocks.
  [`test_admin_router.py`, `_retry_supabase`]
- [x] [Review][Patch] Happy-path test didn't assert `error: None` was included in the
  `lesson_jobs` update payload. [`test_admin_router.py`]
- [x] [Review][Patch] "Unreachable by construction" overclaim on the `job is None` path — softened
  to name the real (astronomically unlikely, not impossible) reason. [`admin/router.py`]
- [x] [Review][Patch] No `# MOCK-CONTRACT:` note on the fully-mocked retry tests — added, honestly
  stating no real-dependency (integration) test exists yet for this endpoint. [`test_admin_router.py`]
- [x] [Review][Defer] Narrow residual TOCTOU race survives the concurrency mitigation (two retry
  calls could still both pass the concurrent-check before either write lands) — **D109**,
  registered in `docs/DEFECT-REGISTER.md`, owner Dev 1, trigger: before real-student launch or if
  observed in production.
- [ ] [Review][Dismiss] "Sprint Task Branch Rule violated — stacked branches" — verified false:
  each branch was genuinely cut from `main`'s actual tip at the time (confirmed via
  `git status`/`git pull` before each branch). The only real issue is cosmetic: fast-forward
  merges instead of explicit merge commits, which made the git log read as stacked when it wasn't.
- [ ] [Review][Dismiss] `lessons(user_id)` selected but unused in `retry_job` — harmless; admin
  retry has no per-user ownership check by design (an admin operator, not the lesson's owner).


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
