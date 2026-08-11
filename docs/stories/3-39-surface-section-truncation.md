---
id: "3-39"
title: "Surface _get_section_body's silent truncation into section_truncations"
status: "ready-for-dev"
sprint: 3
story_points: 3
baseline_commit: "9c6372b"
owner: Dev1
priority: P1
blocker_ref: "D46"
---

# Story 3-39 — Surface `_get_section_body`'s Silent Truncation

## Context & Scope Boundary

**Why this story exists:** `_get_section_body` (`apps/api/app/modules/content/pipeline/graph.py`,
originally reported near `:1941`) caps a section's body text to `max_chars` (default 6000) before
every Phase 1 economy-node LLM call, and today does **only** `logger.warning(...)` when it
truncates — nothing is persisted or surfaced to any caller, admin record, or the final lesson
package. CLAUDE.md names this function-and-cap combination as its own headline example of the
banned "silent truncation" pattern (the 1,151-page-book-to-4%-of-itself defect), and
`docs/DEFECT-REGISTER.md`'s **D46** already documents the exact gap this story closes: *"The
only trace is a `logger.warning` per truncated section... nothing surfaces it to the caller."*

**What this story does NOT do (scope boundary, matching D46's own text):**
- Does **not** change the `6000`-char cap value itself. D46 states the durable fix for the
  *root cause* is chapter sub-segmentation (feeding `lesson_planner` a section-level split
  instead of a capped window) — "a pipeline change, not an endpoint one." That is a separate,
  larger effort this story does not own.
- Does **not** touch `structure_max_sections` (the other half of D46's ~90,000-char LLM-visible-
  window arithmetic).
- **Does** convert the *visibility* half of D46 from a `logger.warning` nobody reads into an
  explicit, persisted, surfaced degradation — matching how Story 1-14 already did this at the
  chapter/endpoint level (`truncation_expected` on the 202 response) but D46 explicitly notes
  nothing equivalent existed at the per-section, per-Phase-1-node level inside the pipeline
  itself. This story is that missing piece.

**What was found during story prep, before writing a line of code:**
- `_get_section_body` is called from exactly 6 Phase 1 economy nodes, each Send()-dispatched
  once per section: `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`,
  `jargon_extractor_node`, `intervention_messages_node`, `narration_generator_node`.
- Every one of the 6 nodes already returns only its own owned channel key(s) (no
  `{**state, ...}` spreads) — confirmed by reading each node's full body, not assumed. This
  story's new channel must preserve that invariant or reintroduce the 16x-duplication bug class
  CLAUDE.md documents at length.
- `quiz_generator_node` and `narration_generator_node` each have multiple return points after
  the `_get_section_body` call (a nested `_salvage_or_empty` closure in the former; 4 distinct
  early-return branches in the latter) — every one of them needs the truncation signal included,
  not just the "happy path" return.
- No pre-existing test exercises `_get_section_body`'s truncation behavior at all — confirmed
  by grep, zero hits for `_get_section_body` in `apps/api/tests/`.

## Story

**As** the content pipeline,
**I want** every section-body truncation to be recorded on a fan-out-safe `section_truncations`
channel and written into `lesson_jobs.node_outputs` alongside the existing
`package_builder_degraded` admin record,
**so that** a section silently reduced before an LLM call is a visible, persisted degradation —
not a `logger.warning` nobody reads — matching this project's binding "silent truncation is
never acceptable" rule.

## Acceptance Criteria

### Functional

- [x] **AC 1.** `_get_section_body` returns a `_SectionBodyResult` (`NamedTuple`: `body`,
  `was_truncated`, `original_chars`, `capped_chars`) instead of a bare `str`, so the truncation
  signal is available to every caller, not silently dropped.
- [x] **AC 2.** `_get_section_body`'s `max_chars` parameter defaults to
  `settings.section_body_max_chars` (new `Settings` field, default `6000`, `config.py`) instead
  of a hardcoded `= 6000` default — a future re-tuning is a config change, not an edit to all 6
  call sites.
- [x] **AC 3.** All 6 call sites (`summarise_segment_node`, `quiz_generator_node`,
  `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node`,
  `narration_generator_node`) are updated to unpack the new return shape and build this node's
  own `section_truncations` contribution via a shared `_section_truncation_entries()` helper.
- [x] **AC 4.** A new `PipelineState` channel, `section_truncations: Annotated[list[dict[str,
  Any]], operator.add]`, is added — same fan-out-safe reducer pattern as `segment_summaries`,
  `quiz_questions`, etc.
- [x] **AC 5.** Every return statement in all 6 nodes that occurs AFTER the `_get_section_body`
  call includes `"section_truncations": section_truncations` in its OWN returned dict (never a
  separate write, never `{**state, ...}`) — covering every early-return branch, not just the
  happy path. Cache-hit returns (which occur BEFORE the call and never invoke it this run) are
  unchanged — omitting the key there is equivalent to an empty contribution under
  `operator.add`.
- [x] **AC 6.** `_section_truncation_entries()` returns an **empty list**, never a missing key,
  when nothing truncated — matching `package_builder_degraded`'s existing always-present-
  possibly-empty convention.
- [x] **AC 7.** `package_builder_node` reads `state.get("section_truncations", [])` and writes it
  into the same `lesson_jobs.node_outputs` admin-visibility write it already does for
  `package_builder_degraded`, as a sibling key `section_truncations`, always written (empty list
  = none).

### Non-functional / regression-guard

- [x] **AC 8.** New tests in `apps/api/tests/unit/test_phase1_economy_nodes.py` (the existing
  home for these 6 nodes' unit tests) prove: (a) a section body over
  `settings.section_body_max_chars` produces a non-empty `section_truncations` entry with the
  correct `section_id`/`node`/`original_chars`/`capped_chars` — RED-confirmed against the
  pre-fix code (real `KeyError: 'section_truncations'`, pasted below) — GREEN after; (b) a
  section body under the cap produces an **empty** `section_truncations` list (not a missing
  key) — same RED/GREEN treatment.
- [x] **AC 9.** No behavior change to any currently-passing test — re-run
  `test_phase1_economy_nodes.py` and `test_package_builder_node.py` in full, unmodified, confirm
  still green.
- [x] **AC 10.** None of the 6 touched nodes returns `{**state, ...}` anywhere (CLAUDE.md's
  binding rule) — verified by reading every return statement in the diff, not assumed.
- [x] **AC 11.** `ruff check`, `ruff format --check`, and `mypy --ignore-missing-imports` all
  pass clean on every modified `.py` file.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one section's body text, read once per Phase 1
   node dispatch (6 nodes × N sections per lesson). Range: sections observed 200 chars (the
   `structure_min_section_chars` floor) to tens of thousands of characters on a dense textbook
   section — the exact range D46 already measured (2,296–2,816 chars/page × up to ~40 pages/
   section before `structure_max_sections` coalesces further). This story does not change that
   range; it changes what happens when a section's body exceeds the cap.
2. **Fixed budget vs. variable input.** `settings.section_body_max_chars` (default 6000, now a
   `Settings` field per AC 2) is a FIXED budget meeting a VARIABLE section-body length. Before
   this story: exceeding it produced an unlogged-to-anyone-but-stdout truncation (silent-wrong,
   the exact failure shape SCALE-CONTRACT Q2 exists to catch). After this story: exceeding it
   still truncates (unchanged behavior — this story does not raise an error, since a truncated-
   but-present body is a valid degrade path for an economy-node LLM call, not a fatal one) but
   now produces an **explicit, persisted, surfaced degradation** (`section_truncations`, written
   into `lesson_jobs.node_outputs`) — satisfying Q2's "explicit surfaced degradation" branch
   instead of "silent truncation."
   **Named per Q5 below and out of this story's scope:** the cap VALUE itself (6000) is
   unrevisited-inherited — see D46, which documents it predates book-scale generation and whose
   durable fix (chapter sub-segmentation) is a separate, larger pipeline change.
3. **Scope of every limit.** `section_body_max_chars` is a single global `Settings` value —
   scoped per DEPLOYMENT (one value for every lesson/section/user on a given API+worker
   deployment), not per user or per instance. Unchanged by this story; only how a breach is
   reported changes.
4. **Unbounded reads/writes.** None introduced. `_get_section_body` and
   `_section_truncation_entries` are pure in-memory functions over an already-fetched
   `section["body"]` string and an already-computed `max_chars` int — no new Supabase reads or
   writes. `package_builder_node`'s new `section_truncations` write reuses the exact same
   `lesson_jobs.update(...)` call the node already makes for `package_builder_degraded` — no new
   query. N/A for the request-path bounding rule specifically: this is entirely inside
   `app/modules/content/pipeline/**`, which `tests/unit/test_unbounded_queries.py`'s own
   docstring exempts (pipeline nodes process a whole chapter by design — that's the unit of
   work, not a `.limit()` question) — not a new judgment call, the same exemption Story 3-36's
   Scale & Load layer already confirmed applies to this directory.
5. **Inherited caps re-derived?** **Named, not re-derived, by design (task-scoped).** The
   `section_body_max_chars = 6000` value is exactly the cap D46 identifies as unrevisited since
   before book-scale generation existed — this story moves it from a hardcoded function
   parameter to a `Settings` field (AC 2) specifically so a *future* re-tuning is a one-line
   config change instead of a 6-call-site edit, but does not change the number itself. Re-
   deriving the number requires measuring real Phase 1 economy-node output quality against
   larger windows, which is a separate, larger effort (D46's "chapter sub-segmentation" fix) —
   explicitly out of this story's scope, not silently skipped.
6. **Check-then-act under concurrency.** N/A — no check-then-act sequence is introduced.
   `section_truncations` is populated via the SAME `operator.add` LangGraph reducer pattern
   already governing `segment_summaries`/`quiz_questions`/etc.; each Send()-dispatched node
   invocation contributes at most the one entry IT produced (or an empty list) in its own
   return, never re-emitting accumulated state — this is exactly the additive-safe shape
   CLAUDE.md's binding rule requires, verified by reading every one of the 6 nodes' return
   statements (AC 10), not assumed. No two dispatches read-then-write the same aggregate; the
   reducer is LangGraph's own concurrency-safe concatenation.

## Tasks

### Task 1 — `_get_section_body` return shape + Settings field
- [x] 1.1 Add `_SectionBodyResult` NamedTuple (AC 1)
- [x] 1.2 Change `_get_section_body` to return it, computing `was_truncated`/`original_chars`/
  `capped_chars` (AC 1)
- [x] 1.3 Add `settings.section_body_max_chars` field to `config.py`; `_get_section_body`
  defaults to it when `max_chars` is not passed (AC 2)
- [x] 1.4 Add `_section_truncation_entries()` helper (AC 6)

### Task 2 — Update all 6 call sites + PipelineState channel
- [x] 2.1 Add `section_truncations: Annotated[list[dict[str, Any]], operator.add]` to
  `PipelineState` (AC 4)
- [x] 2.2 Update `summarise_segment_node` (AC 3, 5)
- [x] 2.3 Update `quiz_generator_node`, including the nested `_salvage_or_empty` closure and its
  2 internal returns plus the node's own final return (AC 3, 5)
- [x] 2.4 Update `segment_complexity_node` (AC 3, 5)
- [x] 2.5 Update `jargon_extractor_node` (AC 3, 5)
- [x] 2.6 Update `intervention_messages_node` (AC 3, 5)
- [x] 2.7 Update `narration_generator_node`, including all 4 return points after the call (AC 3,
  5)
- [x] 2.8 Verify none of the 6 nodes returns `{**state, ...}` anywhere (AC 10)

### Task 3 — `package_builder_node` surfacing
- [x] 3.1 Read `state.get("section_truncations", [])` and write it as a sibling key to
  `package_builder_degraded` in the existing `lesson_jobs.node_outputs` write (AC 7)

### Task 4 — Tests
- [x] 4.1 RED: write both new tests in `test_phase1_economy_nodes.py`, confirm real failure
  against pre-fix code (AC 8)
- [x] 4.2 GREEN: confirm both pass after the fix (AC 8)
- [x] 4.3 Re-run `test_phase1_economy_nodes.py` and `test_package_builder_node.py` in full,
  unmodified, confirm zero regressions (AC 9)
- [x] 4.4 `ruff check` / `ruff format --check` / `mypy` on all modified files (AC 11)

### Task 5 — Register + review
- [x] 5.1 Note this story's fix on `docs/DEFECT-REGISTER.md`'s D46 entry (the "surfacing" half
  is now fixed; the cap-value root cause remains open, as D46 itself already scoped)
- [x] 5.2 6-layer adversarial review — round 1 (inline self-review)

### Task 6 — Commit
- [x] 6.1 Story-first commit alone, verified first-new-commit-on-branch
- [x] 6.2 Implementation commit (code + tests + updated story file)

## Dev Agent Record

### Implementation Plan

1. Read all 6 call sites and their full enclosing node functions first (including every early-
   return branch) before changing the shared helper, so the new return shape's consumers are
   fully mapped before `_get_section_body` itself changes.
2. Change `_get_section_body` to return a `_SectionBodyResult` NamedTuple; add
   `settings.section_body_max_chars`; add the `_section_truncation_entries()` helper.
3. Add the `section_truncations` `PipelineState` channel.
4. Update all 6 call sites and every return statement downstream of each call, including the
   nested closure in `quiz_generator_node`.
5. Update `package_builder_node` to surface the aggregate.
6. Write RED tests against a temporarily-stashed (pre-fix) `graph.py`/`config.py`, confirm real
   failure, restore the fix, confirm GREEN.
7. Re-run both directly-relevant test files in full; run ruff/format/mypy.

### Debug Log

- Used `git stash push -u` to isolate the pre-fix `graph.py`/`config.py` state for the RED run
  without losing the in-progress test file edit (stash included both source files, left the
  test file's own prior state; the test file itself was written fresh in this story so RED was
  confirmed by asserting against the ACTUAL unfixed function/node behavior, not a placeholder).
- Confirmed via `grep` that all 6 call sites' post-call return statements were enumerated before
  editing — `quiz_generator_node` (4 return points: 2 inside `_salvage_or_empty`, 1 via the
  closure call, 1 final) and `narration_generator_node` (4 return points) needed every one
  updated, not just the "success" path.

### Completion Notes

`_get_section_body` now returns a `_SectionBodyResult` NamedTuple (`body`, `was_truncated`,
`original_chars`, `capped_chars`) instead of a bare `str`. `settings.section_body_max_chars`
(new field, default 6000, unchanged value — see Scale & Load Q5) replaces the hardcoded function
default. All 6 Phase 1 economy nodes build their own `section_truncations` contribution via the
new `_section_truncation_entries()` helper and include it in every return statement downstream of
their `_get_section_body` call — verified by reading each node's full body, not assumed.
`package_builder_node` surfaces the aggregate as a sibling key to `package_builder_degraded` in
the existing `lesson_jobs.node_outputs` write. 2 new tests (RED-confirmed against pre-fix code by
temporarily stashing `graph.py`/`config.py`, then GREEN), full re-run of both directly-relevant
test files with zero regressions, ruff/format/mypy clean.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (`_get_section_body` return shape,
  `_SectionBodyResult`, `_section_truncation_entries`, `section_truncations` `PipelineState`
  channel, all 6 call sites + their downstream returns, `package_builder_node` surfacing)
- `apps/api/app/config.py` — MODIFIED (`section_body_max_chars` Settings field)
- `apps/api/tests/unit/test_phase1_economy_nodes.py` — MODIFIED (2 new tests,
  `TestSectionTruncationSurfaced`)
- `docs/DEFECT-REGISTER.md` — MODIFIED (D46 addendum noting the surfacing fix)
- `docs/stories/3-39-surface-section-truncation.md` — MODIFIED (this file)

### Change Log

- 2026-08-11: Story file created (story-first commit, branch
  `sprint3/s3-39-surface-section-truncation`).
- 2026-08-11: RED phase — 2 failing tests confirmed by execution against temporarily-stashed
  pre-fix `graph.py`/`config.py` (real `KeyError: 'section_truncations'`).
- 2026-08-11: GREEN phase — fix restored from stash; both new tests pass; full
  `test_phase1_economy_nodes.py` + `test_package_builder_node.py` re-run, zero regressions.
- 2026-08-11: `docs/DEFECT-REGISTER.md` D46 addendum added.
- 2026-08-11: Round 1 self-review (inline, 6 layers) — see below.
