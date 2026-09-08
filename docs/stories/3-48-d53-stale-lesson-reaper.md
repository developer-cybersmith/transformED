# Story 3-48 — D53 reaper: actually transition stale `generating` lessons to `failed`

**Branch:** `sprint3/s3-48-d53-stale-lesson-reaper` (from `main`).
**Owner:** Dev 1.
**Trigger:** explicit priority pick — D53 is the only defect in the register currently flagged
both **High** and **live in production**.

## Context

D53 (registered `docs/DEFECT-REGISTER.md` line 182): nothing but the ARQ worker itself ever
transitions a `lessons` row out of `status='generating'`. A worker killed mid-run (OOM per D50, a
deploy, a container eviction) leaves a row that nothing clears, and that row is a permanent dead
end for the user who owns it — it blocks that `(chapter_id, tier, user_id)` from ever being
regenerated (the idempotency pre-check keeps returning 200 with the dead lesson), and three such
rows exhaust `max_concurrent_generations_per_user` and 429 the user out of ALL generation.

**Half of D53's stated fix already exists** (confirmed by reading the current code, not assumed):
`router.py`'s `_generating_cutoff_iso()` and both call sites (Gate 5 idempotency check, Gate 7
concurrency count) already bound `generating` rows by age
(`created_at < now() - settings.arq_job_timeout_s`) — a stale row no longer blocks a new
generation or consumes a concurrency slot. The function's own docstring says exactly what's
still missing: *"NOTHING but the worker ever moves a lesson out of `generating` — there is no
reaper... The durable fix is the D53 reaper plus a real `started_at`."*

**What this means in practice, right now:** the WORKAROUND works (a user can eventually
regenerate), but the ORIGINAL stuck row itself never actually becomes `failed` in the database.
`GET /lessons/{that exact id}` polls `generating` forever. `list_lessons` shows a phantom
`generating` entry forever. Nothing ever tells the user (or an admin) that lesson actually died —
D53 is still open and still live in production for exactly this reason.

## The fix

A new ARQ periodic cron job, `reap_stale_generating_lessons` (`apps/api/app/workers/jobs/
reap_stale_lessons.py`), scheduled every 10 minutes via `WorkerSettings.cron_jobs`. Each run:

1. Queries `lessons` for `status='generating'` AND `created_at < _generating_cutoff_iso()` —
   reusing the router's own staleness bound directly (imported, not duplicated) so the reaper and
   the query-level workaround can never silently drift apart on what counts as "stale."
2. For each stale row, calls `content_pipeline.py`'s own `_update_lesson_status(supabase,
   lesson_id, "failed", error=...)` — the SAME helper `content_pipeline_job` itself uses on every
   other failure path, already extended by D86 to persist whatever real cost had accumulated in
   Redis before the worker died (not a fabricated 0). A reaped row and a genuinely-failed row are
   therefore indistinguishable to every downstream reader — no new status-writing logic, full
   reuse of an already-tested path.
3. One row's reap failure does not stop the batch (try/except per row, matching this codebase's
   established never-let-one-bad-item-break-a-loop pattern).

`_update_lesson_status` already mirrors `lessons.status` from a `lesson_jobs` status write, so
one call closes both tables in the same shape as every other failure transition in this codebase.

## What this does NOT do

- Does not add a real `started_at` clock (the "durable fix" the docstring separately names) — that
  addresses queue-wait-time being wrongly counted as run-time (a narrower, non-production-blocking
  known limitation, explicitly "accepted for now" in the existing code's own comment). Out of this
  story's minimal scope; D53's OPEN, LIVE-IN-PRODUCTION half is the permanent-dead-row problem,
  which this fix closes completely on its own.
- Does not touch `_generating_cutoff_iso()`, Gate 5, or Gate 7 — already correct, unchanged.
- Does not build `?force=true` (D54) — a different, already-separately-registered escape hatch.
- Does not touch `_update_lesson_status` itself — reused exactly as D86 left it.

## Scale & Load

1. **Unit of work & range.** One reaper pass scans for stale `generating` rows repo-wide (not
   per-user — a background maintenance job, not a request path). Range: 0 (the common case) to
   however many workers crashed since the last pass.
2. **Fixed budgets vs variable input.** New `.limit(100)` on the reap query — a real stuck-row
   count anywhere near 100 in a single 10-minute window is its own incident, not something this
   job should try to silently drain unbounded in one pass; the next scheduled run picks up
   whatever's left. Bounded, not silently truncated: nothing is lost, it's just spread across
   passes.
3. **Scope of the limit.** Per-deployment (one worker process's cron schedule) — the query itself
   is not scoped to a single user, by design (a crashed worker doesn't only affect one user).
4. **Unbounded reads/writes.** The reap query is now bounded (`.limit(100)`); previously there was
   no reaper at all, so this introduces the first bounded read where none existed.
5. **Inherited caps re-derived.** N/A — reuses `_generating_cutoff_iso()` verbatim, already
   correctly re-derived from `settings.arq_job_timeout_s`.
6. **Concurrency.** The cron job itself is `unique=True` (ARQ default) — a new run cannot start
   while a previous one is still in flight, so no double-reap race on the same row.

## Verification

- RED-GREEN: new tests written first, confirmed failing (function doesn't exist), then GREEN
  after implementation.
- `test_reap_stale_generating_lessons.py`: a stale row gets reaped (both `lessons.status` and
  `lesson_jobs.status` become `failed`, real cost persisted via the mocked `get_cost` path,
  reused from D86's own test conventions); a FRESH `generating` row (created_at inside the
  staleness window) is left untouched; a reap failure on one row doesn't stop the batch (asserts
  the second, healthy row still gets reaped); the query is bounded (`.limit()` called with the
  documented cap).
- Full repo-wide regression against the established baseline, zero new failures.
- `ruff`/`mypy` clean on touched files.


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
