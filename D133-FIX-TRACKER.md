# D133 Fix Tracker — slide_generator segment_id Echo Corruption

**Defect:** `docs/DEFECT-REGISTER.md` D133 — 4 of 20 PDFs in the completed live eval run failed
with `slide_generator returned unknown segment_id(s)`. Real, reproducible root cause found (not
guessed) — see below.

**Started:** 2026-08-25 · **Status:** Fix built, tested, RED-GREEN verified, full regression clean (Steps 1-3 done). Live re-verification (Step 4) next.

---

## Step 1 — Root cause (DONE, evidenced, zero cost to confirm)

Reproduced `structure_node`'s real output (pure, no LLM, no DB, no cost) against all 4 failing
fixtures directly:

| Fixture | Real section title | Real derived `segment_id` |
|---|---|---|
| `dense_text_with_headers` (seg 0) | `"1.1 Subsection"` | `section_0_1-1-Subsection` |
| `table_heavy_small` | `"Document"` (structure-detection fallback) | `section_0_Document` |
| `image_heavy_small` | `"Document"` | `section_0_Document` |
| `image_heavy_grid` | `"Document"` | `section_0_Document` |

Compared byte-for-byte against the real LLM responses that were rejected:
- `section_0_1-1-Subsection` -> LLM returned `section_0_1-1-Subsection: Introduction to Cellular Respiration`
- `section_0_Document` -> LLM returned `section_0_Document: Introduction to Tabular Data` (and
  the equivalent for the other two `_Document` cases)

**The real id is copied perfectly, character for character, every time.** The LLM then appends
`": <a more specific, better title inferred from the segment's own summary content>"` — because
the prompt line format itself is `segment_id={id}: {title} — {summary}`, which teaches the model
by literal example that a `segment_id` value looks like `"opaque-token: readable description"`.
When the real id+title combination is generic or bare (`"Document"`, a bare numbered heading
like `"1.1 Subsection"`), the model "completes" it with a better label pulled from context,
using the exact shape it was just shown — it is not hallucinating from nothing, it is
over-fitting to the prompt's own formatting.

**Why only these 4 of 20:** every other fixture's headings already contain specific, descriptive
words (e.g. real chapter topics), so there's nothing generic-looking for the model to "improve."
These 4 are exactly the ones where `detect_headings` produced either the total fallback title
(`"Document"`) or a bare numeric label with no real subject words (`"1.1 Subsection"`).

**Why `lesson_planner_node` didn't hit this (same risky prompt shape, confirmed):**
`_run_planner_batch` (graph.py:1325) builds the IDENTICAL `segment_id={id}: {summary}` line
format — but D77 (already in `docs/DEFECT-REGISTER.md`) already gave it a retry-on-mismatch loop
(`_PLANNER_BATCH_MAX_ATTEMPTS`) for a related echo-fidelity problem. `slide_generator_node` has
no equivalent retry — one bad completion is an immediate hard failure, no second chance.

## Step 2 — Fix (DONE, 2026-08-25)

Applied the SAME already-proven pattern D77 established for this exact failure class
(under/mis-echoed structured ids from an LLM) to `slide_generator_node`: retry the completion up
to `_SLIDE_GENERATOR_MAX_ATTEMPTS = 3` times on a segment_id mismatch before falling through to
the existing degrade-not-fabricate guards, mirroring `_run_planner_batch`'s structure exactly —
same attempt-count constant shape, same `set(ids) == input_id_set` match condition, same
`logger.warning` diagnostic on a mismatched attempt. `graph.py` diff: +55/-8 lines, isolated to
the `_SLIDE_GENERATOR_MAX_ATTEMPTS` constant + the new retry loop in `slide_generator_node`; the
downstream count/unknown-id/duplicate-id guards are byte-for-byte unchanged, so their exact
`RuntimeError` messages and "no checkpoint on failure" behavior are preserved.

Not changed (deliberately): the prompt format itself. The retry-based fix directly addresses the
confirmed mechanism (occasional LLM non-determinism — the same prompt sometimes echoes cleanly,
sometimes doesn't) without touching a prompt that already has other review history behind it.

## Step 3 — Verify (DONE, 2026-08-25)

**New tests** (`tests/unit/test_slide_generator_node.py`), mirroring `_run_planner_batch`'s own
D77 test coverage:
- `test_slide_generator_retries_on_echo_mismatch_and_recovers` — first attempt corrupts one
  segment_id with the exact real observed shape (`"sec_1: How It Actually Works"`), second
  attempt echoes cleanly; asserts `call_count == 2` and that the RECOVERED response is used.
- `test_slide_generator_retry_exhausts_and_still_raises` — every attempt corrupts the same
  segment_id (permanently broken, not transient); asserts it still raises
  `RuntimeError` matching `"unknown segment_id"` via the existing guard, asserts
  `call_count == _SLIDE_GENERATOR_MAX_ATTEMPTS` exactly (3, no more, no fewer), and asserts
  `sb.table.return_value.update.assert_not_called()` (no checkpoint written on failure).

**RED-GREEN discipline applied**: swapped `graph.py` back to the pre-fix (`HEAD`) version and
re-ran just these 2 new tests — both genuinely failed (one with the exact production
`RuntimeError: ... unknown segment_id(s): ['sec_1: How It Actually Works']`, the other with
`ImportError` on the not-yet-existing `_SLIDE_GENERATOR_MAX_ATTEMPTS`), proving the tests
actually discriminate the fix rather than passing trivially. Restored the fix version; both
tests GREEN again.

**Full verification sweep, all green:**
- `ruff check` on `graph.py` + the test file — all checks passed.
- `ruff format --check` on both — already formatted.
- `pytest tests/unit/test_slide_generator_node.py` — all 32 tests pass (30 pre-existing +
  2 new), pre-existing tests unmodified.
- `mypy app/modules/content/pipeline/graph.py` — 0 errors in `graph.py` itself (3 pre-existing,
  unrelated httpx-version errors surfaced in `providers/llm/openai.py`,
  `providers/image/openai_image.py`, `providers/embeddings/openai.py` — none touched by this fix).
- `pytest tests/unit` (full suite) — **1256 passed, 9 skipped, 0 failed** (200.5s).

## Step 4 — Live re-verification (in progress)
Re-run the 4 previously-failing fixtures for real. 3 of 4 are single-segment (cheap — they
failed in under a minute each pre-fix, so retries add little cost even if triggered);
`dense_text_with_headers` has 15 segments (the fixture that actually spent real Phase 1/2 money
before failing at slide_generator).

---

## Milestone Log

### Step 1 — 2026-08-25
Root cause found and confirmed with real, reproduced evidence (see above) — not guessed, not
assumed. Registered as D133.

### Step 2/3 — 2026-08-25
Fix built (mirrors D77's proven retry pattern), 2 new discriminating tests written and
RED-GREEN verified, full unit regression clean (1256 passed / 9 skipped / 0 failed), lint +
format + mypy clean on the changed file. Ready for live re-verification against the real
fixtures that actually failed in the completed 20-PDF run.
