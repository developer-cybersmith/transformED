---
status: in-progress
baseline_commit: dc5ed51
---

# Story 5-14 — Chapter Context Wiring: CI Gate (Unit Guard Test)

## Story

**As** the CI pipeline,
**I want** Story 249's `chapter_context` wiring invariants to be in the gating test
bucket (`tests/unit/`),
**so that** a regression to the pre-Story-249 state — `chapter_context` silently not
reaching `slide_generator_node` or `narration_generator_node` — blocks a merge
instead of appearing only as advisory noise.

## Background

Story 249 (2026-09-25) wired `chapter_context` into `slide_generator_node` and
`narration_generator_node` and added `chapter_context_truncated` to `PipelineState`.
Its full test suite (`tests/test_249_context_wiring.py`) lives in the `tests/` root —
the **advisory** CI bucket (`continue-on-error: true`). CLAUDE.md is explicit:
*"A green checkmark does NOT mean the advisory bucket is clean."*

The critical structural invariants are ungated today:
- Is `"chapter_context"` in `_FAN_OUT_STATE_KEYS`? (narration_generator_node's only
  receive path via `Send()`)
- Does `slide_generator_node` still call `merge_chapter_context()`?
- Is `_CHAPTER_CONTEXT_MAX_CHARS` still 1,300?
- Does `PipelineState` still declare the `chapter_context` / `chapter_context_truncated`
  pair?

A developer modifying `_FAN_OUT_STATE_KEYS` or refactoring `graph.py` today gets no
CI gate failure if they inadvertently remove Story 249's wiring. Identified during
the post-merge audit session of 2026-09-28 (Story 5-13).

**What this story does NOT do:**
- Does not move `tests/test_249_context_wiring.py` — that file's async node tests need
  heavier mock infrastructure that belongs in the advisory bucket. This story adds a
  *parallel* guard in `tests/unit/` covering only structural invariants (imports,
  constant values, fan-out set membership, source-text call count).
- Does not add new wiring — Story 249 is complete and correct.
- Does not touch `tests/test_249_context_wiring.py` or any other test file.

## Acceptance Criteria

1. **AC1** — `tests/unit/test_chapter_context_wiring_guard.py` exists and every test
   in it passes in the gating CI bucket.

2. **AC2** — The guard asserts `"chapter_context" in _FAN_OUT_STATE_KEYS` (import-level
   check, not source scan), with an error message naming Story 249 AC 7 and the
   consequence (narration_generator_node silently receives no chapter context).

3. **AC3** — The guard asserts `"chapter_context_truncated" in _FAN_OUT_STATE_KEYS`
   (same import-level check), with an error message naming Story 249 AC 8.

4. **AC4** — The guard asserts `PipelineState` declares both `chapter_context` and
   `chapter_context_truncated` via `typing.get_type_hints()` (catches forward-ref
   issues that raw `__annotations__` misses).

5. **AC5** — The guard asserts `_CHAPTER_CONTEXT_MAX_CHARS == 1_300` with an error
   message that names the re-derivation step required to change it legitimately
   (to prevent the inherited-cap trap, Scale Contract Q5).

6. **AC6** — The guard asserts `merge_chapter_context` is importable and callable
   from `prompt_context`.

7. **AC7** — The guard asserts `graph.py` calls `merge_chapter_context()` at least
   twice via a source-text pattern scan (lesson_planner_node + slide_generator_node;
   catching accidental removal of either call site).

8. **AC8** — Existing gating guard tests
   (`test_node_return_shape`, `test_unbounded_queries`,
   `test_defect_register_no_duplicate_ids`) still pass with zero regressions.

## Scale & Load

**S1 — Unit of work:** One test file, 8 tests. All source-scan or import-level.
No HTTP, no DB, no LLM calls. Runs in < 1 s.

**S2 — Fixed budgets vs. variable input:** N/A — reads two local source files
(graph.py, prompt_context.py) that are fixed at test-collection time.

**S3 — Scope of every limit:** Per-CI-run. Stateless, idempotent.

**S4 — Unbounded reads/writes:** None. The two source-file reads are bounded by
the files' actual sizes, which are static.

**S5 — Inherited caps re-derived:** N/A — no pipeline caps involved.

**S6 — Check-then-act under concurrency:** N/A — read-only source inspection.

## Tasks

- [x] **T1 — Story-first commit (BMAD gate)**
  - [x] T1.1 — Write this file
  - [x] T1.2 — `git commit -m "docs(story-first): Story 5-14 — chapter context wiring CI gate"`
  - [x] T1.3 — Push story-only commit to remote

- [x] **T2 — Implement guard test**
  - [x] T2.1 — Write `tests/unit/test_chapter_context_wiring_guard.py`
    - [x] T2.1a — `_FAN_OUT_STATE_KEYS` membership guards (AC2 + AC3)
    - [x] T2.1b — `PipelineState` field guards (AC4)
    - [x] T2.1c — `_CHAPTER_CONTEXT_MAX_CHARS` constant guard (AC5)
    - [x] T2.1d — `merge_chapter_context` callable guard (AC6)
    - [x] T2.1e — `graph.py` source-scan call-count guard (AC7)

- [x] **T3 — Run guard tests**
  - [x] T3.1 — `pytest tests/unit/test_chapter_context_wiring_guard.py -v` — **7 passed**
  - [x] T3.2 — `pytest tests/unit/test_node_return_shape.py tests/unit/test_unbounded_queries.py -v`
    — 21 passed, 1 pre-existing `tinytag` ModuleNotFoundError on
    `test_tts_node_returns_only_its_own_keys` (confirmed pre-existing, not introduced here —
    same baseline as Story 5-13 completion notes).
    `test_defect_register_no_duplicate_ids.py` lives on the S5-13 branch (not yet merged to
    main); its absence on this branch is not a regression introduced here.

## Dev Agent Record

### Change Log

| Date       | Change                        | Author         |
|------------|-------------------------------|----------------|
| 2026-09-28 | Story file created            | Dev 3 / Claude |
| 2026-09-28 | Guard test implemented        | Dev 3 / Claude |

### Completion Notes

7 new gating guard tests added to `tests/unit/test_chapter_context_wiring_guard.py`.
All 7 pass. The tests use import-level assertions (for `_FAN_OUT_STATE_KEYS`,
`PipelineState` type hints, `merge_chapter_context` callable, `_CHAPTER_CONTEXT_MAX_CHARS`
value) and a source-text regex scan (for the `graph.py` call-count invariant).
No async node execution — runs in under 4 seconds.

Pre-existing `tinytag` ModuleNotFoundError on `test_tts_node_returns_only_its_own_keys`
confirmed pre-existing (same as Story 5-13 completion notes) — not introduced here.

`test_defect_register_no_duplicate_ids.py` is on the S5-13 branch (open PR, not yet
merged to main) — not a regression introduced here; will appear in gating CI once
S5-13 merges.

### Debug Log

_To be filled in if needed._
