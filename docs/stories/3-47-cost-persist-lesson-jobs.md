# Story 3-47 — Persist real accumulated cost to `lesson_jobs.cost_usd` (D86)

**Branch:** `sprint3/s3-47-cost-persist-lesson-jobs` (from `main`).
**Owner:** Dev 1.
**Trigger:** Direct code reading this session, confirmed live against two real, real-money
lesson generations.

## Context

Every lesson generation is tracked against a per-lesson dollar cost ceiling ($3.00,
`settings.max_lesson_cost_usd`). The REAL, live-enforced running total lives in Redis
(`apps/api/app/core/cost_tracker.py`): `accumulate_cost()` does `redis.incrbyfloat(
"cost:{lesson_id}", ...)`, `get_cost()` reads it back, `check_ceiling()` compares it against the
ceiling during the pipeline run. This Redis-based enforcement genuinely works and is unchanged by
this story.

Separately, `lesson_jobs` (migration `20260611000000_initial_schema.sql`) has its own
`cost_usd numeric(10,4) NOT NULL DEFAULT 0` column — the durable, post-hoc record of what a
lesson actually cost, needed for reporting/calibration (real "measured cost per lesson" is a
stated L1 acceptance-run deliverable).

## The defect (D86)

`lesson_jobs.cost_usd` is never written by anything, ever, at any point in a real pipeline run —
confirmed two ways:

1. Grepped `apps/api/app/workers/jobs/content_pipeline.py` (the ARQ job that runs a lesson
   pipeline end to end) for `cost_usd` — zero matches anywhere in the file, before this story.
2. `clear_lesson_cost()` in `cost_tracker.py` — called at `content_pipeline.py`'s success path
   right after the pipeline finishes — carries this exact docstring: *"Call this when a lesson
   pipeline run is fully complete and **the cost has been persisted to the DB**, or when
   aborting a run entirely."* The persistence step this docstring promises was never
   implemented. The Redis key is deleted with the real accumulated total discarded, every single
   time, success or failure.

**Real observed evidence:** two real, fully successful lesson generations this session (real
confirmed OpenAI LLM spend + real Sarvam TTS spend, verified by downloading and validating real
audio files) both show `lesson_jobs.cost_usd = 0.0000` in the database. The number this project
needs for cost calibration has never once been recorded.

This is exactly the class of failure `docs/SCALE-CONTRACT.md` Q2 names: not a scale/limit
question directly, but the same "silent degradation is never acceptable" principle applies — a
`$0.00` recorded cost for a lesson that demonstrably cost real money is silently wrong, not
loudly broken. Nothing errors, nothing warns anywhere a human reads it; the row simply reports a
number that is not true.

## The fix

In `apps/api/app/workers/jobs/content_pipeline.py`:

1. **Success path.** Before the direct `supabase.table("lesson_jobs").update({"status":
   "completed", "completed_at": ...})` call, and before the later `await
   clear_lesson_cost(lesson_id)` call in the same function, fetch the real accumulated cost via
   `get_cost(lesson_id)` (imported alongside the existing `clear_lesson_cost` import) and add
   `"cost_usd": round(current_cost, 4)` to that same update payload — one DB write, not two.
   Order matters: cost is read **before** `clear_lesson_cost` deletes the Redis key. The
   `get_cost()` call is wrapped in its own `try/except`: a Redis read failure degrades to leaving
   `cost_usd` unset (the column's existing/default value) rather than crashing an otherwise-
   successful pipeline run — this repo's established pattern for a secondary tracking concern
   (see `_update_lesson_status`'s own try/except around its Supabase writes).

2. **Failure paths.** All go through the shared `_update_lesson_status(supabase, lesson_id,
   status, error=None)` helper. Extended with an optional `cost_usd: float | None = None`
   parameter; when not supplied, and only when `status == "failed"`, the helper fetches it itself
   via the same `get_cost()` call, guarded by the same try/except-and-degrade pattern (the
   `"running"` transition never fetches — there is no accumulated cost yet at that point, and
   fetching would be pure waste). Added to the existing `payload` dict alongside
   `status`/`error` in the single `supabase.table("lesson_jobs").update(payload)` call already in
   that helper — no second DB write. Every one of the helper's 4 call sites (RuntimeError/cost
   ceiling, generic RuntimeError, `asyncio.CancelledError`, generic `Exception`) now persists real
   cost on failure, not 0.

**Unchanged, by design:** `accumulate_cost`, `check_ceiling`, `clear_lesson_cost`'s own
signatures/Redis behavior, `_COST_KEY_TTL_SECONDS`, Redis key naming, and how the $3.00 ceiling
itself is enforced (`check_ceiling`'s callers in `graph.py`). This is purely a persistence-on-
completion fix.

## Scale & Load

1. **Unit of work & range.** One lesson's accumulated Redis cost float
   (`cost:{lesson_id}`), read exactly once per terminal state transition (one success write, or
   one failure write per failed attempt). Range: `$0.00` (pipeline fails before any billed call)
   to whatever the pipeline actually spends before hitting the $3.00 ceiling — bounded by the
   ceiling itself, which this story does not touch.
2. **Fixed budgets vs variable input.** No new fixed budget is introduced. `round(cost_usd, 4)`
   matches the column's own `numeric(10,4)` precision exactly, so no value this story writes can
   overflow or silently truncate against the schema. The one thing that CAN fail — the Redis read
   itself — degrades explicitly: `cost_usd` is left unset (not zeroed, not fabricated) and a
   `logger.warning` names the lesson_id, rather than writing a false `0.0000` that looks
   identical to "genuinely free" in the reporting data. This is the exact silent-vs-loud
   distinction Q2 asks for, applied to the failure mode this story itself could introduce.
3. **Scope of the limit.** Per-lesson — `cost:{lesson_id}` is already a per-lesson Redis key
   (unchanged); this story only reads it, once, at a point the pipeline already reaches
   (completion or failure) for every lesson today.
4. **Unbounded reads/writes.** None introduced. One additional `GET` against a single Redis key
   per terminal transition; no new Supabase reads, and the new `cost_usd` field is folded into an
   **existing** `.update()` call at every site (one extra dict key, not one extra round trip).
5. **Inherited caps re-derived.** N/A — no cap is being sized or resized here; this closes a pure
   accounting gap in a column that already existed with the correct precision
   (`numeric(10,4)`) since the frozen initial schema.
6. **Concurrency.** `get_cost()` is a plain Redis `GET`, not a check-then-act — nothing here reads
   a value and later acts on staleness. `accumulate_cost()`'s own `INCRBYFLOAT` (unchanged,
   already atomic) is the only writer to the Redis total; this story only ever consumes the value
   it returns at the moment of a single lesson's own terminal transition, which is not shared
   across concurrent lessons (key is per-`lesson_id`) or subject to a race with itself (a given
   `lesson_id`'s pipeline reaches exactly one terminal transition — success or one specific
   failure branch — not both).

## Verification plan

- New tests in `apps/api/tests/test_lesson_ready_pubsub.py` (success path — mirrors its existing
  `_patch_pipeline_deps` mock/fixture conventions) and `apps/api/tests/unit/test_timeout_contract.py`
  (failure path — mirrors its existing `_make_multi_table_supabase_mock` / parametrized failure
  cases):
  - Success path's `lesson_jobs` update call includes a real `cost_usd` sourced from a mocked
    `get_cost()`, not 0 and not absent from the payload.
  - A failure path (`except Exception` branch) also includes real `cost_usd` in its `lesson_jobs`
    update, not just `status`/`error`.
  - A `get_cost()` failure (raised inside the mock) does not crash the job — the existing
    status/error update still succeeds, `cost_usd` simply omitted.
- RED-GREEN verified via the Edit tool (revert, confirm failure, restore, confirm pass) — not a
  fragile string-replace script.
- Full repo-wide regression (`python3 -m pytest -q` from `apps/api`) run before and after — zero
  new failures is the invariant. Exact counts recorded in the implementation commit.
- `ruff check`, `ruff format --check`, `mypy app` on every touched file.


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
