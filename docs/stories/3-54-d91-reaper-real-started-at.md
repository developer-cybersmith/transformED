# Story 3-54 — D91: reaper uses a real started_at, not lessons.created_at

**Branch:** `sprint3/s3-54-d91-reaper-real-started-at` (from `main`).
**Owner:** Dev 1.
**Trigger:** live evidence during the ch5/T1 real generation run — not a new discovery, the
exact known limitation `_generating_cutoff_iso()`'s own docstring already named and deliberately
deferred at D53's close ("the durable fix is the D53 reaper plus a real `started_at`").

## Context

D53's reaper (`reap_stale_generating_lessons`) used `lessons.created_at` — the moment the row was
INSERTED, before the job was even enqueued — as its only staleness signal. This conflates
QUEUE-WAIT time with REAL RUN time: a job that sits queued for a while before a worker picks it
up gets less real run-time budget than `arq_job_timeout_s` before being reaped, even though it
may still be genuinely alive and working.

**Observed live, not hypothetical:** a real ch5/T1 generation attempt (lesson `b0a96211`) hit a
severe ARQ retry delay — `try=2 delayed=1925.75s` (~32 minutes) before even being dequeued,
likely the same event-loop-blocking pattern observed earlier this session, compounded by a real
OpenAI Image Generation timeout. The reaper (10-minute cadence) saw the row as stale under the
old `created_at`-only logic and marked it `failed` — while the underlying job was still actually
executing. Result: `lessons.status='failed'` (the reaper's write) but `lesson_jobs.status='running'`
(the still-alive worker's own state) permanently inconsistent, with an ARQ `try=2` attempt still
potentially in flight.

## The fix

1. `content_pipeline.py`'s `_update_lesson_status` now writes `lesson_jobs.started_at` — a real
   timestamp — whenever `status == "running"`. Every retry attempt overwrites it with ITS OWN
   start time (correct: a fresh attempt deserves a fresh staleness clock, not the original row's
   creation time or an earlier attempt's start).
2. The reaper now queries `lesson_jobs` directly (not `lessons`) for `status IN ('pending',
   'running')`, bounded by a GENEROUS outer cutoff (`arq_job_timeout_s * 2`, covering legitimate
   queue-wait + run time combined) via `.lt("created_at", ...)`. In Python, each candidate is then
   refined precisely: if `started_at` is set, compare against the REAL `arq_job_timeout_s` bound
   from that real start time; if `started_at` is still null (never started running at all), the
   row is already known stale via the query's own generous bound.
3. `_generating_cutoff_iso()` itself, and Gate 5/Gate 7 in `router.py`, are UNCHANGED — their
   conservative use of `lessons.created_at` is a different, acceptable tradeoff (erring toward
   NOT letting a new duplicate request through is safe; the reaper erring toward falsely marking
   something dead is actively harmful, which is why only the reaper needed the more precise signal).

## What this does NOT do

- Does not touch `_generating_cutoff_iso()`, Gate 5, or Gate 7 in `router.py` — deliberately
  scoped to the reaper alone; see rationale above.
- Does not attempt to fix the underlying event-loop-blocking delay that caused the real ~32-minute
  ARQ dequeue delay in the first place — a separate, larger, pre-existing issue (synchronous
  Supabase client calls blocking the asyncio event loop), out of this story's scope.
- Does not touch `docs/DEFECT-REGISTER.md` or `docs/dev1-tracker.md` in this commit — registered
  in a consolidated documentation pass alongside D54/D59(a)/D88/D89/D90.

## Scale & Load

1. **Unit of work & range.** One reaper pass scans lesson_jobs for non-terminal rows past a
   generous outer bound; range 0 to however many jobs are genuinely stuck since the last pass.
2. **Fixed budgets vs variable input.** `_REAP_BATCH_LIMIT=100` unchanged. `_QUEUE_WAIT_MULTIPLIER=2`
   is a new, reasoned (not exactly derived) margin — explicitly erring toward under-reaping
   (leaving a merely-slow job alone) rather than over-reaping (falsely killing a live one), since
   the live incident this story fixes showed over-reaping is the actively harmful direction.
3. **Scope of the limit.** Per-deployment, unchanged.
4. **Unbounded reads/writes.** None introduced; the query is bounded exactly as before.
5. **Inherited caps re-derived.** This IS the re-derivation D53's own docstring already promised
   and deferred — now delivered, prompted by real evidence rather than executed speculatively.
6. **Concurrency.** Unchanged — the cron job remains `unique=True`.

## Verification

- RED-GREEN via `mv`-aside (implementation) and `git stash`/pop (the `_update_lesson_status`
  extension) — both confirmed failing with the exact predicted errors before the fix, restored
  and confirmed green after.
- `test_reaps_a_job_whose_real_start_time_is_past_the_run_cutoff` — the base case, reaped.
- `test_does_not_reap_a_job_with_a_recent_real_start_despite_old_created_at` — **the core fix,
  reproduced directly**: an old-by-creation-time but recently-started job must NOT be reaped —
  the exact false positive observed live.
- `test_reaps_a_never_started_job_past_the_generous_queue_cutoff` — the never-started fallback path.
- `test_no_candidates_is_a_pure_noop`, `test_reap_query_targets_lesson_jobs_status_and_is_bounded`,
  `test_one_bad_row_does_not_stop_the_batch` — carried over from D53, adapted to the new query shape.
- `test_running_transition_writes_a_real_started_at` (new, `test_timeout_contract.py`) — the
  `_update_lesson_status` extension itself, using the file's existing `_make_multi_table_supabase_mock`
  helper to correctly attribute the write to `lesson_jobs`, not the mirrored `lessons` write.
- Full repo-wide regression: 52 failed/2113 passed/86 skipped — established baseline, zero new
  failures. `ruff`/`mypy` clean on all touched files.
