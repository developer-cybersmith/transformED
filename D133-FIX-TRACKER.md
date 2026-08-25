# D133 Fix Tracker — slide_generator segment_id Echo Corruption

**Defect:** `docs/DEFECT-REGISTER.md` D133 — 4 of 20 PDFs in the completed live eval run failed
with `slide_generator returned unknown segment_id(s)`. Real, reproducible root cause found (not
guessed) — see below.

**Started:** 2026-08-25 · **Status:** Root cause confirmed (Step 1 done). Fix not yet built.

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

## Step 2 — Fix (planned, not yet built)

Apply the SAME already-proven pattern D77 established for this exact failure class
(under/mis-echoed structured ids from an LLM) to `slide_generator_node`: retry the completion a
few times on a segment_id mismatch before hard-failing, mirroring `_run_planner_batch`'s
structure exactly. Low risk — not a new idea, a proven one already trusted in this codebase for
the identical problem.

Not planned (deliberately, for now): changing the prompt format itself. The retry-based fix
directly addresses the confirmed mechanism (occasional LLM non-determinism — the same prompt
sometimes echoes cleanly, sometimes doesn't) without touching a prompt that already has other
review history behind it. If retries alone prove insufficient once tested against the real
failing fixtures, revisit.

## Step 3 — Verify (planned)
Unit tests mirroring `_run_planner_batch`'s own test coverage (corrupt-then-clean response
sequence). Full regression suite.

## Step 4 — Live re-verification (planned)
Re-run the 4 previously-failing fixtures for real. 3 of 4 are single-segment (cheap — they
failed in under a minute each pre-fix, so retries add little cost even if triggered);
`dense_text_with_headers` has 15 segments (the fixture that actually spent real Phase 1/2 money
before failing at slide_generator).

---

## Milestone Log

### Step 1 — 2026-08-25
Root cause found and confirmed with real, reproduced evidence (see above) — not guessed, not
assumed. Registered as D133.
