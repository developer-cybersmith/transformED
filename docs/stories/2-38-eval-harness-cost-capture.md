# Story 2.38: The eval harness must report per-lesson cost

Status: review

## Story

As whoever runs the 5-PDF eval,
I want each run to record the real USD spent on that lesson,
so that "re-measure the cost baselines" becomes a command someone runs rather than a task nobody can do.

**Source:** the standing action from `docs/DEFECT-REGISTER.md` D1 — *"cost baselines are ~4×
inflated by a duplication bug now fixed; any lesson-cost figure you have been shown is unreliable
until re-measured."*

## The defect

**There is no instrument.** `tests/evals/runner.py` is 302 lines and contains zero references to
cost, USD, or price. `EvalResult` records `slide_quality`, `quiz_relevance` and
`elapsed_seconds` — and nothing about money.

So the repo asserts a **$3.00/lesson ceiling** (PRD §12, `settings.max_lesson_cost_usd`) that is
*enforced* at runtime by `core/cost_tracker.py`, while **no harness has ever reported what a
lesson actually costs.** Every cost figure in the docs is an estimate, and the one number that
would have caught the 16× duplication bug on spend — real dollars per lesson — was never
captured.

"Re-measure the baselines" has therefore been an un-actionable item: you cannot re-measure with
an instrument that does not exist.

The data is already there. `accumulate_cost()` writes a per-lesson running total to Redis on
every LLM, TTS and image call, and `get_cost(lesson_id)` reads it back. The harness simply never
asks.

## Acceptance Criteria

1. **AC-1 — `EvalResult` carries `cost_usd`.** Read via `get_cost(lesson_id)` **after**
   `run_pipeline` returns and **before** cleanup, so it reflects the whole run.
2. **AC-2 — Capture is best-effort and never fails the eval.** A Redis error while reading the
   cost must not turn a successful, already-paid-for pipeline run into a failed eval result. Log
   and record `None`. Same principle as `_safe_trace` and `_safe_record`: observability must
   never displace the result it observes.
3. **AC-3 — Cost is captured on the failure path too.** A run that fails partway has still spent
   money, and that number is the most interesting one for diagnosing a ceiling breach. The
   `except` branch must record it as well.
4. **AC-4 — The Redis cost key is cleaned up.** `run_eval` calls `run_pipeline` directly, not the
   ARQ job, so the worker's `clear_lesson_cost` never runs and every eval leaks a key. Clear it
   in `finally`, after the read, alongside the existing `_cleanup_eval_rows`.
5. **AC-5 — The summary reports the aggregate.** `run_all_evals` output includes total and mean
   cost across the 5 PDFs, and the per-lesson figures are written to the results JSON so a run is
   comparable against a later one.
6. **AC-6 — A breach of the ceiling is visible in the summary.** If any lesson's `cost_usd`
   exceeds `settings.max_lesson_cost_usd`, say so explicitly. A number in a JSON file that nobody
   compares against the limit is not a guard.
7. **AC-7 — Tested without a live run.** The live eval is deliberately deferred and costs real
   money. Every AC above must be covered by tests that stub `run_pipeline` and `get_cost`, so the
   instrument is proven correct *before* anyone spends money with it.
8. **AC-8 — No regression.** Full suite shows exactly the pre-existing failures. `ruff check`,
   `ruff format --check` and `mypy app` produce no findings not already at baseline, measured
   **repo-wide** (CLAUDE.md binding rule 1).

## Tasks / Subtasks

- [x] Task 1 (AC-1, AC-2, AC-3, AC-4): capture cost in `run_eval`, both paths; clear the key.
- [x] Task 2 (AC-5, AC-6): aggregate + ceiling-breach reporting in `run_all_evals`.
- [x] Task 3 (AC-7): tests with `run_pipeline` and `get_cost` stubbed.
- [x] Task 4 (AC-8): full suite, lint, types.

## Dev Notes

- **Do not add cost to the pass/fail criteria of the eval.** This story makes cost *visible*, not
  *gating*. A lesson that breaches the ceiling is already aborted at source by
  `_maybe_accumulate_cost`; re-deciding that here would put the same rule in two places with two
  different owners.
- **`get_cost` returns 0.0 for an unknown lesson**, which is indistinguishable from "genuinely
  free". That is acceptable here — a real pipeline run always makes at least one billed call —
  but do not reuse this helper anywhere that needs to tell the two apart.
- **This does not itself re-measure anything.** It builds the instrument. The baseline numbers
  land when someone runs `pytest tests/evals/test_live_run.py -v --run-live-eval` with live
  credentials. That is a deliberate, separately-funded action.
- Every new test needs `@pytest.mark.unit`.

### Explicitly OUT of scope

- Running the live eval (costs real money; deferred by an explicit decision).
- Changing `max_lesson_cost_usd` or any ceiling behaviour.
- Per-node cost attribution — useful, but it needs `cost_tracker` to key by node, which is a
  bigger change than the instrument this story is closing.

### Project Structure Notes

Touches `apps/api/tests/evals/runner.py` and tests. **No** `app/` changes, **no**
`packages/shared/*`, **no** `supabase/migrations/*` — §16 gate not triggered.

### Branching

`sprint2/dev1-eval-cost-capture`, based on `main`.

### References

- [Source: docs/DEFECT-REGISTER.md — D1 standing action on cost baselines]
- [Source: CLAUDE.md §14 — $3.00/lesson ceiling]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-30 | Story created. Closes the last open Dev 1 action by building the missing instrument rather than estimating a number. | Dev 1 |

## Dev Agent Record

### Completion Notes

Builds the instrument; does **not** produce the baseline. The numbers land when someone runs
`pytest tests/evals/test_live_run.py -v --run-live-eval` with live credentials — a deliberate,
separately-funded action.

**A test of mine passed for the wrong reason and I caught it by reading the assertion.** The
helper originally passed `Path("nonexistent.pdf")`; `run_eval` does `pdf_path.read_bytes()`
during setup, so *every* call took the failure path — and because AC-3 captures cost there too,
the AC-1 success-path test was green without ever exercising the success path. Fixed by writing
a real temp file, and the test now asserts `package_valid is True` **before** checking the cost,
so it cannot regress to that state silently.

**`None` is not `0.0`.** An unreadable meter records `None` and is excluded from the mean.
Averaging in a zero would understate the baseline — the one direction of error a cost ceiling
must not have.

### Mutation testing — 8 mutants, 8 caught, 0 survivors

Including "unreadable cost becomes 0.0", "None counted as 0.0 in the mean", and both
directions of the ceiling-breach check (never reports / always reports).

### Verification (repo-wide, CLAUDE.md binding rule 1)

- `pytest tests/unit tests/integration` — **793 passed**, 1 skipped
- `pytest tests` — 22 failed, **1485 passed**; failure set unchanged (Dev 3 19, Dev 4 3)
- `ruff check .` / `ruff format --check .` — clean · `mypy app` — 24 in 3 files, unchanged

### File List

- `apps/api/tests/evals/runner.py` (modified)
- `apps/api/tests/unit/test_eval_cost_capture.py` (new)
