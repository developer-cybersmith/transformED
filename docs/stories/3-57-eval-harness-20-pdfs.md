# Story 3-57 — S3-1: Eval harness expanded to 20 PDFs

**Branch:** `sprint3/s3-1-eval-harness-20-pdfs` (from `main`).
**Owner:** Dev 1.
**Tracker source:** `docs/dev1-tracker.md` S3-1 — "`apps/api/tests/evals/`. Cover all failure
modes: dense text, table-heavy, image-heavy, short (≤10 pages), long (≥100 pages). **AC:** All 20
PDFs produce valid `LessonPackage`; no pipeline crash; scores tracked in Langfuse."

## Context

Story 2-14 (S2-14, done) built the harness infrastructure with exactly **5** synthetic PDFs — one
per required category (short/long/dense-text/table-heavy/image-heavy) — and named S3-1 explicitly
as its own follow-up: *"Sprint 3's expanded 20-PDF gate (S3-1)."* Read fresh before writing this
story:

- `apps/api/tests/fixtures/generate_eval_pdfs.py` — deterministic, `fpdf2`-based synthetic PDF
  generator (Story 2-14 AC-2: no randomness, so two runs produce structurally identical PDFs).
  Real textbook PDFs were never available in this environment; that scope decision from S2-14
  stands unchanged here — still synthetic, same generator design, just more of them.
- `apps/api/tests/evals/runner.py` — `_EVAL_PDF_KEYS` (a flat tuple of 5 names) is the *only*
  place the PDF count is fixed; `run_all_evals()` iterates it with no hardcoded length anywhere
  else in the loop, summary, or results-JSON logic. Expanding the tuple is sufficient to make the
  harness itself run 20 — no structural change needed there.
- `apps/api/tests/evals/test_live_run.py` — the actual real-provider run, gated behind the
  `live_eval` marker / `--run-live-eval` flag (off by default, per `tests/evals/conftest.py`).
  **This is where S3-1's real blocker lives** — see "What this story does NOT complete" below.
- `apps/api/tests/unit/test_eval_runner.py` — asserts `len(results) == 5` /
  `payload["summary"]["pdfs_run"] == 5` against a fully-mocked pipeline. No real provider calls;
  this is what actually runs in CI/default `pytest`.
- `tests/fixtures/eval_pdfs/*.pdf` is gitignored (`apps/api/.gitignore:40`) — the fixture files
  themselves are never committed, only the generator script. Verified via `git ls-files`.

**A real coupling this story fixes, not just extends:** `_EVAL_PDF_KEYS`
(`tests/evals/runner.py`) and `_GENERATORS.keys()` (`tests/fixtures/generate_eval_pdfs.py`) are
two independent lists of the same 5 names, kept in sync only by convention — exactly the "two
documents both claiming authority drift" pattern CLAUDE.md's own binding rule 5 names as a
recorded defect class in this repo. Adding 15 more names in two places, by hand, with nothing
checking they still match, is how that drift starts. This story adds a guard test asserting the
two sets are identical, so a future edit to one without the other fails CI immediately instead of
silently generating fixtures the runner never looks for (or vice versa).

## The fix

**1. Twenty real, meaningfully-distinct variants — not 15 lazy duplicates.** Four per category,
each testing a different real edge within that category (not just a renamed copy of the original
5, and not padding the count without adding coverage):

| Category | 4 variants |
|---|---|
| short (≤10p) | 1-page (extreme minimum) · 3-page (S2-14's original) · 10-page (upper boundary) · sparse (few pages, near-empty per page) |
| long (≥100p) | 100-page (lower boundary) · 150-page · 250-page · 400-page (stress `structure_max_sections` capping at real scale) |
| dense_text | uniform (S2-14's original) · long-paragraphs (few, large blocks) · short-paragraphs (many fragments) · with-headers (dense text broken by frequent subheadings — a different structure-detection load than pure density) |
| table_heavy | small tables/many-per-page (S2-14's original) · wide (many columns) · tall (many rows) · mixed (tables interspersed with narrative text, not pure-table pages) |
| image_heavy | small/many-per-page (S2-14's original) · large/few-per-page · captioned (substantial caption text alongside images) · grid (dense many-small-image stress case) |

Page counts for "long" are kept in the 100–400 range rather than pushing toward the real
1,671/2,475-page OpenStax scale CLAUDE.md's inherited-cap discussion names — this harness's job is
regression-catching on a cheap, frequent cadence (S2-14's own stated design goal), and each of the
20 PDFs becomes one full real pipeline run (real LLM/TTS/image cost) once actually executed live;
400 pages already exercises the same hierarchical-processing/section-capping code paths a
2,000-page book would, at a fraction of the cost. Real-book-scale testing is L1's job, not this
harness's.

**2. `generate_eval_pdfs.py`** — refactor the 5 single-purpose builder functions into
parameterized ones where the variants are genuinely the same shape with a different dial (e.g.
`_build_long(pages: int)`, `_build_short(pages: int, sparse: bool)`), rather than 20 copy-pasted
functions. `_GENERATORS` grows to 20 entries.

**3. `runner.py`** — `_EVAL_PDF_KEYS` grows to the same 20 names, same order as `_GENERATORS`.
Module docstring's "5-PDF subset" → "20-PDF" (S2-14 built the subset, this story completes it).

**4. `test_eval_runner.py`** — the two `== 5` assertions become `== 20`.

**5. `test_live_run.py`** — docstring/comments updated from "5" to "20" (gated test; still worth
being accurate for whoever runs `--run-live-eval` next, since the docstring is the only
documentation of what that invocation actually does).

**6. New guard test** (in `test_eval_runner.py` or a new small file — exact placement decided
during implementation): `set(_EVAL_PDF_KEYS) == set(_GENERATORS.keys())`. Fails loudly if either
list is edited without the other.

## What this story does NOT complete

The tracker's one-line AC ("All 20 PDFs produce valid `LessonPackage`; no pipeline crash; scores
tracked in Langfuse") describes the *live* run's outcome, not the harness's existence. The fuller
PRD Week 5 gate criteria (`.claude/commands/run-evals.md`) additionally requires **"15 of 20 PDFs
rated 'useful to a student' by a human reviewer."** Neither of these can be satisfied by this
story alone:

- **The live run itself is blocked** — `test_live_run.py` hits real OpenAI/Sarvam/Azure. Sarvam
  currently returns `402 insufficient_quota_error` (confirmed live against the real API this same
  session, independent of this story) — the same external blocker already tracked against L1. 20
  sequential real lessons at up to ~15 min each is also a real multi-hour, real-money commitment
  that should be a deliberate, explicit invocation once credits return, not something to trigger
  as a side effect of this story landing.
- **The human-review gate is, definitionally, not something to automate.** "Rated useful to a
  student" is a subjective judgment this story cannot manufacture a substitute for.

This story delivers everything that does NOT require either of those: a harness that is *capable*
of running, scoring, and reporting on 20 real, meaningfully-varied PDFs the moment someone invokes
`--run-live-eval` with working credentials, fully verified today via the mocked default test path
(same real code, same `run_pipeline` call, same scoring, same results-JSON — only the actual
network calls are stubbed). The live run + human review remain the explicit next step, tracked the
same way L1 already is.

## Scale & Load

1. **Unit of work & range.** One eval PDF → one full pipeline run. Range: 1–400 synthetic pages
   across the 20 fixtures (see table above); real page count is bounded by the generator, not
   variable input from an untrusted source.
2. **Fixed budgets vs variable input.** Each live run is still subject to the existing
   `max_lesson_cost_usd` ceiling (unchanged by this story) — `run_all_evals`'s summary already
   reports `cost_ceiling_breaches` by name (Story 2-38), which now covers 20 names instead of 5.
   No new budget introduced here.
3. **Scope of the limit.** N/A — no new limit. The existing $3.00/lesson ceiling is per-lesson,
   unchanged.
4. **Unbounded reads/writes.** N/A — no new read/write path. `run_eval`'s existing per-PDF
   Supabase rows + Storage upload + cleanup sequence is unchanged, just invoked 20 times instead
   of 5 (still sequential, still isolated per-PDF per AC-4).
5. **Inherited caps re-derived.** The "long" category's page-count ceiling (400, this story's own
   new value) is explicitly reasoned above, not inherited from an earlier, differently-scoped
   design — matching this contract's own standard for what "re-derived" means.
6. **Concurrency.** N/A — `run_all_evals` is a sequential `for` loop today (unchanged by this
   story); running 20 real lessons concurrently is out of scope here and would need its own
   cost/rate-limit analysis before being introduced.

## Verification

- RED-GREEN: extend `test_run_all_evals_isolates_per_pdf_failures_and_writes_results` (or add a
  sibling test) asserting `len(results) == 20` / `pdfs_run == 20` against the real
  `generate_all()` output — confirm it fails against the unmodified 5-entry state, then passes
  after `_EVAL_PDF_KEYS`/`_GENERATORS` are both expanded.
- New guard test (`set(_EVAL_PDF_KEYS) == set(_GENERATORS.keys())`) — confirm it would fail if the
  two lists were allowed to drift (temporarily desync one during implementation, confirm RED,
  restore, confirm GREEN).
- Run `generate_all()` locally against a tmp dir and confirm 20 real PDF files are produced, each
  non-empty, each satisfying its category's page-count constraint (short ≤10p, long ≥100p) —
  verified programmatically (real `pypdfium2` page count on the generated bytes), not assumed from
  the builder's own page-count parameter.
- Full existing `test_eval_runner.py` / `test_eval_scoring.py` / `test_eval_cost_capture.py` —
  confirm zero pre-existing tests broke (none of them hardcode PDF names beyond `"short.pdf"`
  fixtures they construct themselves in `tmp_path`, independent of `_EVAL_PDF_KEYS`/`_GENERATORS`
  — confirmed by grep before writing this story).
- Full repo-wide regression (`pytest -q` from `apps/api`) — diff against the current baseline,
  confirm zero new failures.
- `ruff check` / `ruff format --check` / `mypy app` clean on all touched files.
- Explicitly NOT run as part of this story: `pytest tests/evals/test_live_run.py -v
  --run-live-eval` — blocked on Sarvam credits, tracked the same way as L1, not silently skipped
  without saying so.
