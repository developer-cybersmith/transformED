# Story 3-44 — Retry a single lesson_planner batch on echo mismatch (D77)

**Branch:** `sprint3/s3-44-planner-batch-retry` (from `main`, immediately after Story 3-43 merged).
**Owner:** Dev 1.
**Trigger:** Phase 4 of Story 3-43's own plan — the first real end-to-end demo-generation attempt
against D75's merged fix.

## Process note — order of work

As with Stories 3-40/3-42, the implementation was written and RED-GREEN verified before this
story file — this was found live, mid-execution of an approved plan's Phase 4 (the real
generation run), not planned in advance. Committed alone, before the implementation commit, so
the two stay separately reviewable.

## Context

Story 3-43 (D75) fixed a real, confirmed bug: `lesson_planner_batch_size` (15) equalled
`structure_max_sections` (15), so Story 2-16's batching never actually engaged, and a real
15-segment chapter always took the unreliable single-call path. D75 lowered the batch size to
10, verified via a unit test using a real settings value and a well-behaved mock LLM.

Running Story 3-43's own Phase 4 (the real demo-generation run) against the merged fix, **two
consecutive real attempts still failed** at `lesson_planner`:

- Attempt 1: `expected 15, got 14`
- Attempt 2: `expected 15, got 12`

This was not assumed to be a fix failure — verified directly against real Langfuse trace data
before writing any code. Fetched the real trace for the second failed lesson
(`create_trace_id(seed=lesson_id)` → `GET /api/public/traces/{id}`) and confirmed: **batching
genuinely engaged as designed** — one real LLM call carried exactly 10 `segment_id` references,
a second carried exactly 5. D75's fix works exactly as built. The residual gap is different: a
real LLM can still occasionally under-echo even a correctly-sized 10-item or 5-item batch — a
lower-frequency instance of the same 1:1-echo unreliability Story 2-16 first found at 44 items,
just not eliminated by batch-sizing alone.

## The fix

`_run_planner_batch` now retries **the same batch's own completion** (not the whole node, not
the other already-correct batches) up to `_PLANNER_BATCH_MAX_ATTEMPTS = 3` times when the
response doesn't echo back every input `segment_id` in that batch exactly once. Targets the
actual observed failure mode directly, rather than guessing an even smaller "safe" batch size
with no more evidence than D75 already had.

- A `None` response (provider returned nothing parseable) still raises immediately, unchanged —
  out of this fix's scope, a different failure mode.
- When every retry attempt still mismatches, the function returns the last attempt's response
  unchanged, and `lesson_planner_node`'s existing assembled-response guard block raises its own
  contextual error exactly as before — retries are a recovery attempt layered in front of the
  existing guarantee, not a weakening of it.

## What this does NOT do

- Does not change `structure_max_sections`, `lesson_planner_batch_size`, or the batching/split
  logic itself (D75, unchanged).
- Does not add retry to the `response is None` path — a different, already-immediate failure
  mode, not what was observed live.
- Does not touch the node-level assembled guard block (`graph.py`'s duplicate/unknown-id/blank
  checks) — those remain the final backstop, unchanged, and this story's own tests prove they
  still fire correctly when retries are exhausted.

## Scale & Load

1. **Unit of work & range.** One batch's LLM completion, retried 1–3 times. Worst case (every
   batch in a maximal chapter needs all 3 attempts): for a 15-segment chapter (10+5 split), up
   to 6 real LLM calls instead of 2 — bounded, not unbounded.
2. **Fixed budgets vs variable input.** `_PLANNER_BATCH_MAX_ATTEMPTS = 3` is a new fixed budget;
   exceeding it surfaces the existing explicit `RuntimeError`, never silently accepts a
   corrupted plan.
3. **Scope of the limit.** Per-batch, per-call — same scope as the batch itself.
4. **Unbounded reads/writes.** None introduced.
5. **Inherited caps re-derived.** N/A — new constant, not inherited.
6. **Concurrency.** No new check-then-act sequence; batches within one `lesson_planner_node`
   call already run sequentially (D75, unchanged).

## Verification

- RED-GREEN verified via the Edit tool (not a fragile string-replace script, learned from an
  earlier failed attempt in this same session): reverted `_run_planner_batch` to the pre-fix
  single-call body, confirmed both new tests fail with the predicted messages (a real
  `RuntimeError` from the existing guard for the recovery test; `1 == 3` call-count mismatch for
  the exhaustion test); restored, confirmed GREEN.
- `test_planner_retries_same_batch_on_echo_mismatch_and_recovers` — a batch that under-echoes on
  attempt 1, succeeds on attempt 2; asserts the **recovered** response is used (not just that
  the eventual guard still fires — that's a different, pre-existing test).
- `test_planner_batch_retry_exhausts_and_still_raises_via_existing_guard` — a permanently-broken
  batch still raises via the existing guard after exactly `_PLANNER_BATCH_MAX_ATTEMPTS` calls,
  no more, no fewer.
- Full `test_lesson_planner_node.py`: 40/40 passing, including both pre-existing
  guard-preservation tests (`test_planner_batched_dropped_id_still_rejected`,
  `..._duplicate_id_count_preserved_still_rejected`) — confirmed these still assert the correct
  final outcome even with retries now running underneath them (their mocks corrupt
  deterministically on every call, so retries exhaust and the existing guard fires exactly as
  before).
- `tests/integration/test_howto_pipeline_e2e.py`: still 2/2 passing (its mock LLM always
  succeeds, so retries never trigger there — unaffected).
- Full repo-wide regression: 54 failed / 2062 passed / 85 skipped — the exact established
  pre-existing baseline, +2 for this story's new tests, zero new failures. `ruff`/`mypy` clean
  on all touched files.


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
