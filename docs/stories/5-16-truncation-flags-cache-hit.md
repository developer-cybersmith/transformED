---
status: in-progress
baseline_commit: 5abaed6
---

# Story 5-16 — Resurface `_truncated` Flags on `lesson_planner_node` and `slide_generator_node` Cache-Hit (D191)

## Story

**As** the lesson pipeline,
**I want** `book_context_truncated`, `chapter_context_truncated`, and
`onboarding_context_truncated` to be returned with their correct values when
`lesson_planner_node` or `slide_generator_node` takes the idempotency
cache-hit path on an ARQ retry,
**so that** `package_builder_node` always persists accurate truncation flags to
`lesson_jobs.node_outputs`, and admins can query for lessons whose context was
silently trimmed.

## Background

`book_context_truncated`, `chapter_context_truncated`, and
`onboarding_context_truncated` are written to `lesson_jobs.node_outputs` by
`package_builder_node` via `state.get("book_context_truncated", False)` (graph.py
lines 7753–7764). That write is the only admin-visible record of whether the
personalization context was truncated.

### Root cause

Both `lesson_planner_node` and `slide_generator_node` implement the idempotency
pattern: if their output key is already in `node_outputs`, they return the
cached result and skip the LLM call. On the cache-hit path **neither node
returns the three `_truncated` flags**:

- `lesson_planner_node` cache-hit (graph.py line 2425): returns `lesson_plan`,
  `book_context`, `chapter_context`, `onboarding_context` — missing all three flags.
- `slide_generator_node` cache-hit (graph.py line 2975): returns `slides` only —
  missing all three flags.

The fresh-computation paths for both nodes DO compute and return the flags
correctly. The fan-out dispatch router sets
`base.setdefault("book_context_truncated", False)` (graph.py lines 7939–7941,
8096–8098), so on an ARQ retry where both nodes cache-hit, the flags remain
`False` in state throughout. `package_builder_node` then writes
`book_context_truncated: false` into `lesson_jobs.node_outputs` — silently wrong,
no error, no warning — even though the context was truncated on the original run.

Defect: **D191** (registered, not fixed, 2026-09-28).

### Why fixing `lesson_planner_node` alone is insufficient

`slide_generator_node` is the second and last node to correctly set the flags on
a fresh run (line 3289–3291). If only `lesson_planner_node`'s cache-hit is fixed
and `slide_generator_node` also cache-hits, the flags set by `lesson_planner_node`
would be correct — but `slide_generator_node`'s cache-hit return overwrites the
state channel (last-write-wins, non-reducer). The new False-omission-by-absence
from `slide_generator_node`'s cache-hit return leaves the flags absent from its
return dict, so they don't update. Since the flags ARE non-reducers, a missing key
in one node's return doesn't overwrite what was set by an earlier node — this is
actually safe. But for defence-in-depth and correctness on ANY retry topology,
both nodes should return the flags on cache-hit.

### The fix

For both cache-hit paths: compute the truncation flags from the context strings
that are already available (fetched before the cache check in
`lesson_planner_node`, read from state in `slide_generator_node`) and include
them in the return dict. The computation is `len(ctx) > _MAX_CHARS` — O(1), no
LLM call, no DB call.

## Acceptance Criteria

1. **AC1** — `lesson_planner_node` cache-hit path (graph.py `if "lesson_planner"
   in node_outputs:`) returns `book_context_truncated`,
   `chapter_context_truncated`, and `onboarding_context_truncated` computed as
   `len(ctx) > _MAX_CHARS` from the already-fetched context strings.

2. **AC2** — `slide_generator_node` cache-hit path (graph.py `if
   "slide_generator" in node_outputs:`) returns the same three flags computed
   from `state.get("book_context") or ""`, `state.get("chapter_context") or ""`
   and `state.get("onboarding_context") or ""`.

3. **AC3** — The D191 comment block at `lesson_planner_node` cache-hit (lines
   2430–2434) is removed and replaced by a brief inline note referencing this story.

4. **AC4** — A guard test `tests/unit/test_lesson_planner_node.py` (extending the
   existing file) or a new `tests/unit/test_d191_truncation_flags_cache_hit.py`
   asserts that, when `lesson_planner_node` cache-hits with an over-budget context
   string (> `_BOOK_CONTEXT_MAX_CHARS`), the returned dict contains
   `book_context_truncated: True`. Same assertion for `chapter_context_truncated`
   and `onboarding_context_truncated`.

5. **AC5** — A parallel guard test asserts the same three flags for
   `slide_generator_node`'s cache-hit path.

6. **AC6** — Existing gating guard tests (`test_node_return_shape`,
   `test_unbounded_queries`, `test_fan_out_state_keys`) pass with zero regressions.

7. **AC7** — D191 entry in `docs/DEFECT-REGISTER.md` is updated to
   `FIXED-GUARDED` with a reference to this story.

## Scale & Load

**S1 — Unit of work:** One `len(str) > int` comparison per context field, per
node, per ARQ attempt. Min: 0 chars (no context — flag stays False). Typical:
50–400 chars. Largest observed: ~2,200 chars (over the 2,000-char book context
budget). Behaviour beyond budget: flag = True. No timeout risk.

**S2 — Fixed budgets vs. variable input:** `_BOOK_CONTEXT_MAX_CHARS`,
`_CHAPTER_CONTEXT_MAX_CHARS`, `_ONBOARDING_CONTEXT_MAX_CHARS` are the same
fixed thresholds already applied on the fresh-computation path. The fix adds no
new thresholds. The flags are booleans — no growth.

**S3 — Scope of every limit:** Per-lesson, per-node, per-ARQ-attempt. The
comparison is deterministic and stateless.

**S4 — Unbounded reads/writes:** None introduced. The context strings are
already in memory (fetched before the cache check in `lesson_planner_node`;
read from state in `slide_generator_node`). No new DB reads.

**S5 — Inherited caps re-derived:** The `_MAX_CHARS` constants are imported from
`prompt_context.py` (already imported at module top, line 83–86). No new caps.

**S6 — Check-then-act under concurrency:** N/A — the cache-hit path is
read-only; no writes to shared state. The `*_truncated` state channels are
non-reducers (last-write-wins), and this fix writes the same values
`lesson_planner_node` would have written on a fresh run.

## Tasks

- [x] **T1 — Story-first commit (BMAD gate)**
  - [x] T1.1 — Write this file
  - [x] T1.2 — `git commit -m "docs(story-first): Story 5-16 — resurface truncation flags on cache-hit (D191)"`
  - [x] T1.3 — Push story-only commit to remote

- [ ] **T2 — Fix `lesson_planner_node` cache-hit (AC1)**
  - [ ] T2.1 — Add `book_context_truncated`, `chapter_context_truncated`,
    `onboarding_context_truncated` to the cache-hit return dict
  - [ ] T2.2 — Remove D191 comment block (AC3), add one-line story reference

- [ ] **T3 — Fix `slide_generator_node` cache-hit (AC2)**
  - [ ] T3.1 — Add three truncation flag keys to the cache-hit return dict,
    reading context strings from state

- [ ] **T4 — Guard tests (AC4, AC5)**
  - [ ] T4.1 — Add/extend `test_lesson_planner_node.py` or create
    `test_d191_truncation_flags_cache_hit.py`; assert truncated=True on
    cache-hit when context > MAX_CHARS (all three flags, for both nodes)

- [ ] **T5 — Run tests (AC6)**
  - [ ] T5.1 — `pytest tests/unit/test_d191_truncation_flags_cache_hit.py -v`
  - [ ] T5.2 — `pytest tests/unit/test_node_return_shape.py
    tests/unit/test_unbounded_queries.py tests/unit/test_fan_out_state_keys.py -v`

- [ ] **T6 — Update DEFECT-REGISTER.md (AC7)**
  - [ ] T6.1 — D191 → `FIXED-GUARDED`, reference Story 5-16 and guard test

## Dev Agent Record

### Change Log

| Date       | Change             | Author         |
|------------|--------------------|----------------|
| 2026-09-28 | Story file created | Dev 3 / Claude |

### Completion Notes

_To be filled in on completion._

### Debug Log

_To be filled in if needed._
