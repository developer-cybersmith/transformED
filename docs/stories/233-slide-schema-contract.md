---
title: "Story 233 (Piece 1) — Slide schema & contract: typed slides, split-screen, per-slide timing"
issue: "#233 — Slide generation: mandatory 15/30/45-min structures + transcript protocol"
status: in-progress
branch: feature/233-slide-schema-contract
---

## Context & Scope Boundary

Issue #233 requires replacing today's variable-count, uniform-shape slide generation with the
three fixed structures (7/10/10 slides for 15/30/45-min) described in
`docs/proposals/source-specs/2026-09-hie-lecture-format-{15,30}min.pdf` and
`...-45min-and-onboarding-pack.pdf` §4.4 — a mandatory split-screen slide type, typed slide roles
(Overview/Contents/Topic-Teaching/Split-Screen/Q&A/Broader-Picture/Mind-Map), and a fixed
per-slide-type time budget. Full comparison against current code:
`docs/proposals/2026-09-28-slide-strategy-15-30-45-alignment.md` §3 (B2/B3/B4), decision record in
§5-7 of that same doc.

**This story is Piece 1 of that larger initiative: the data-shape change only.** It adds the fields
needed to represent a typed, timed, split-screen slide to the frozen `LessonPackage` contract. It
does **not** change what `slide_generator_node` produces — that node keeps emitting today's shape
(no `slide_type` set) until Piece 2. Zero behavior change; this is additive schema surface only.

**Why this piece first, and why alone:** every later piece (typed-slide generation, split-screen
rendering, per-slide pacing) depends on this shape existing. It also carries the only real
non-code dependency in the whole initiative — CLAUDE.md §16 requires 4-developer sign-off on any
change to `packages/shared/lesson_package.schema.json` + `types/lesson.ts` before merge, the exact
process Story 235's `learner_dna` migration and the `avatar-fields-schema-change.md` proposal both
already followed for schema-touching work. Isolating it into its own piece means Pieces 2+ aren't
blocked waiting on that review to complete.

**Process note, stated plainly rather than silently glossed over:** this repo's `CLAUDE.md`
describes review by 4 named developers across the team. In this session, that formal multi-person
sign-off isn't literally available — the practical substitute this session has used throughout for
frozen-contract and cross-cutting changes is the same 6-layer BMAD adversarial review (Story
Quality / Blind Hunter / Test Coverage / AC Completeness / Process Integrity / Scale & Load) plus
explicit user confirmation before merge. That substitute is what "sign-off" means for AC10 below,
not a claim that 4 distinct human developers reviewed this.

## Story

As the content pipeline's slide-generation logic (a later piece), I need `Slide` to be able to
represent 7 distinct slide roles, a split-screen layout, and a target time budget, so that typed
slide generation has somewhere to put its output — without breaking any existing lesson record or
consumer that only knows today's `{slide_id, title, bullets, image_url, fallback_image_url}` shape.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `Slide` (`apps/api/app/schemas/lesson.py`) gains 5 new fields, all optional/nullable,
  no existing field's shape or requiredness changes: `slide_type: SlideType | None`,
  `topic_index: int | None`, `target_duration_sec: int | None`, `left_content: SplitScreenSide |
  None`, `right_content: SplitScreenSide | None`. New `SplitScreenSide` model: `heading: str,
  bullets: list[str]`, `_STRICT` config (matching every other model in this file).
- [ ] **AC 2.** `slide_type` is a closed enum/Literal with exactly 7 values, identical across all
  three files (AC1 Python, AC3 JSON schema, AC4 TypeScript): `overview, contents, topic_teaching,
  split_screen, qa, broader_picture, mind_map`.
- [ ] **AC 3.** `packages/shared/lesson_package.schema.json`'s `Slide` definition mirrors AC1/AC2
  exactly — 5 new properties (each `oneOf [<real type>, null]` matching the existing
  `image_url`/`fallback_image_url` convention), a new `SplitScreenSide` definition, `"required"`
  unchanged (none of the 5 new fields added to it), `"additionalProperties": false` unchanged.
- [ ] **AC 4.** `packages/shared/types/lesson.ts`'s `Slide` interface mirrors AC1/AC2 exactly — 5
  new optional/nullable fields, a new `SplitScreenSide` interface, a new `SlideType` union type.
- [ ] **AC 5.** A `LessonPackage`/`Slide` dict with NONE of the 5 new fields present (i.e., every
  existing lesson record and every existing test fixture, unchanged) still validates against the
  updated JSON schema — mirrors `test_lesson_package_omitting_avatar_fields_validates_against_raw_json_schema`'s
  exact pattern for this exact reason (CLAUDE.md binding rule 2: assert an observable outcome, not
  a mock).
- [ ] **AC 6.** A `Slide` with all 5 new fields populated (including a fully-populated
  `SplitScreenSide` on both `left_content` and `right_content`) round-trips correctly through
  `Slide.model_validate()` → `.model_dump()` → the raw JSON schema validator — mirrors
  `test_lesson_package_avatar_fields_round_trip_through_json_schema`'s pattern.
- [ ] **AC 7.** The existing guard test `test_slide_extra_fields_forbidden`
  (`apps/api/tests/unit/test_lesson_schema.py:334`) passes unmodified — proves the 5 new fields are
  legitimately recognized fields, not accidentally-permitted "extra" ones (i.e. `extra="forbid"`
  still holds for anything NOT in this story's field list).
- [ ] **AC 8.** No behavior change: an existing call to `slide_generator_node` (real node, mocked
  provider — same convention as `test_slide_generator_node.py`) still produces a `Slide` dict with
  none of the 5 new fields set, and that dict still assembles into a valid `LessonPackage` via
  `package_builder_node`, exactly as before this story.
- [ ] **AC 9.** Existing guard tests for the touched module all pass: full `test_lesson_schema.py`
  suite, plus `tests/unit/test_node_return_shape.py` (this story touches no node return dicts, but
  the guard-test survey rule applies to any story touching a pipeline-adjacent schema file) and
  `tests/unit/test_unbounded_queries.py`.
- [ ] **AC 10.** Frozen-contract review recorded before merge — see the Process Note above for what
  "sign-off" means in this session's context. Not silently skipped.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions. Several are genuinely N/A for a schema-only, zero-runtime-behavior
piece — CLAUDE.md permits "N/A" only with a stated reason, given below for each.)*

1. **Unit of work, and its range.** One `Slide` object gaining 5 optional fields. No data volume
   change — this piece adds shape, not a new fetch, generation call, or stored value. The one thing
   worth flagging forward (not solved here): `SplitScreenSide.bullets` inherits no explicit
   character cap in this story, matching the EXISTING top-level `Slide.bullets` field, which also
   has no Pydantic-level cap today — that field's real bound is enforced at the *prompt* level
   (`_MAX_SLIDE_BULLET_CHARS = 200`, `graph.py:2829`), not the schema level. `left_content`/
   `right_content`'s bullets should get the identical prompt-level bound when Piece 2 actually
   generates split-screen content — named here so Piece 2 doesn't have to rediscover this
   convention, not deferred silently.
2. **Fixed budgets vs. variable input.** None introduced by this piece. **N/A with reason:** no LLM
   output is generated against these fields yet (that starts in Piece 2) — there is nothing to
   truncate or cap at the schema-definition stage itself. `target_duration_sec` is stored as given,
   with zero enforcement anywhere in this piece (explicitly out of scope, see below).
3. **Scope of every limit.** **N/A with reason:** no limits introduced.
4. **Unbounded reads/writes.** **N/A with reason:** zero new Supabase queries, zero new fetches —
   pure in-memory schema shape change across 3 files.
5. **Inherited caps re-derived.** **N/A with reason:** no numeric cap is being reused or inherited
   from another field in this piece; `target_duration_sec` doesn't borrow any existing constant.
6. **Check-then-act under concurrency.** **N/A with reason:** no runtime logic changes; this is a
   static type/schema definition change only, evaluated once at import/validation time, not a
   sequence of operations that could race.

**The one-line test, answered:** nothing here can be silently wrong, because nothing here produces
a value yet — the only way this piece fails loudly-not-silently is a schema mismatch between the 3
files (caught by AC5/AC6's round-trip tests) or an accidental behavior change to existing slides
(caught by AC8).

## Tasks

### Task 1 — Guard-test survey (done, listed here per CLAUDE.md)
`grep -rln "test_.*schema\|Slide\b" apps/api/tests` → `test_lesson_schema.py` (primary guard,
Slide-specific tests + the avatar-fields round-trip pattern this story mirrors),
`test_slide_generator_node.py` (AC8's regression target), `test_content_router.py`,
`test_image_generator_node.py`, `test_s5_4_duration_budget.py`, `test_howto_pipeline_e2e.py`
(broader `Slide`-adjacent tests, run for regression per Task 4, not expected to need changes).

### Task 2 — RED
Write the new tests (AC2/5/6/7 shape) against the CURRENT (pre-this-story) schema — they must fail,
proving they test something real before any implementation lands.

### Task 3 — GREEN
1. `apps/api/app/schemas/lesson.py` — add `SlideType` (Literal or StrEnum, TBD at implementation
   time based on this file's existing convention for closed string sets), `SplitScreenSide` model,
   5 new `Slide` fields.
2. `packages/shared/lesson_package.schema.json` — mirror in the `Slide` definition + new
   `SplitScreenSide` definition.
3. `packages/shared/types/lesson.ts` — mirror in the `Slide` interface + new `SplitScreenSide`/
   `SlideType` types.

### Task 4 — Full regression
`test_lesson_schema.py` + `test_slide_generator_node.py` + guard tests
(`test_node_return_shape.py`, `test_unbounded_queries.py`) + full `tests/unit`/`tests/integration
-m "not postgres"` suite + `ruff check`/`format` + `mypy`.

### Task 5 — Review & commit
BMAD review (this session's 6-layer substitute per the Process Note), fix/register findings, commit
implementation, push, open PR clearly flagged as a frozen-contract change.

## Dev Agent Record

### Implementation Plan
_(filled during implementation)_

### Debug Log
_(filled during implementation)_

### Completion Notes
_(filled during implementation)_

### File List
_(filled during implementation)_

### Change Log
- 2026-09-28: Story file created (story-first commit), branch `feature/233-slide-schema-contract`,
  based on `main` at `fedc47d6`.
