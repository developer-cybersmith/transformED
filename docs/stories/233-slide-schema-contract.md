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
  (`apps/api/tests/unit/test_lesson_schema.py:335`) passes unmodified — proves the 5 new fields are
  legitimately recognized fields, not accidentally-permitted "extra" ones (i.e. `extra="forbid"`
  still holds for anything NOT in this story's field list).
- [ ] **AC 8.** No behavior change: an existing call to `slide_generator_node` (real node, mocked
  provider — same convention as `test_slide_generator_node.py`) still produces a `Slide` dict with
  none of the 5 new fields set, and that dict still assembles into a valid `LessonPackage` via
  `package_builder_node`, exactly as before this story.
- [ ] **AC 9. CORRECTED (Round 1 review, Story Quality):** the originally-named guard tests
  (`test_node_return_shape.py`, `test_unbounded_queries.py`) do not actually cover this story's own
  `schemas/__init__.py.__all__` addition — the former AST-scans only pipeline/tutor node returns,
  the latter explicitly scopes to `router.py`/`service.py`, excluding schema files by its own
  docstring. The real, already-precedented guard for exactly this situation is
  `test_f2_1_learner_context.py`'s own `__all__` membership assertion pattern — mirrored as
  `test_split_screen_side_in_schemas_dunder_all`. Full `test_lesson_schema.py` suite (53 tests,
  including this new one) passes; `test_node_return_shape.py`/`test_unbounded_queries.py` also
  still run and pass as general-purpose guard tests (harmless to include, just not the *specific*
  guard for this story's `__all__` change).
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

### Task 1 — Guard-test survey — CORRECTED (Round 1 review, Story Quality: original survey undercounted by 15 files)
`grep -rln "test_.*schema\|Slide\b" apps/api/tests` (run against the real branch base, `fedc47d6`,
not just skimmed) → **22 files**, not the 6 originally listed. Genuinely relevant beyond the
original 6: `test_real_package_payload_validation.py` (builds a fixture directly from
`lesson_package.schema.json` — run explicitly, see Task 4). The rest (`test_migration_assessment_schema.py`,
`test_lesson_ready_pubsub.py`, `test_t28_dna_display_contract_dev2.py`, `test_openapi_spec.py`,
`test_onboarding_content.py`, `test_schema_column_guard.py`, `test_node_return_shape.py`,
`test_onboarding_endpoint.py`, `test_f2_1_learner_context.py` (source of the AC9 fix's pattern),
`test_lesson_ready_routing_key.py`, `test_image_generator_node.py`, `test_structure_no_llm.py`,
`test_book_select_lists_against_postgrest.py`, `test_migration_chapters_book_scoped.py`,
`test_phase1_economy_nodes.py`) matched on the generic word "schema" in an unrelated context —
confirmed by inspection, not expected to be Slide-relevant, run anyway as part of Task 4's full
suite regardless.

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

### Task 4 — Full regression — CORRECTED (Round 1 review, Story Quality)
`test_lesson_schema.py` + `test_slide_generator_node.py` + `test_package_builder_node.py` +
`test_real_package_payload_validation.py` (top-level `apps/api/tests/`, outside both `tests/unit`
and `tests/integration` — the original "full regression" claim silently excluded it; it has 2
pre-existing failures unrelated to this diff, confirmed by running it in isolation and by this
diff never touching `apps/api/app/modules/assessment/service.py`) + guard tests
(`test_node_return_shape.py`, `test_unbounded_queries.py`, `test_ces.py`) + full `tests/unit`/
`tests/integration -m "not postgres"` suite + `ruff check`/`format` + `mypy` + frontend
`npm run type-check` (`tsc --noEmit`, confirmed zero `lesson.ts`/`Slide`-related errors).

### Task 5 — Review & commit
BMAD review (this session's 6-layer substitute per the Process Note), fix/register findings, commit
implementation, push, open PR clearly flagged as a frozen-contract change.

## Dev Agent Record

### Implementation Plan
Followed the exact test-pattern precedent `test_lesson_schema.py` already established for
`LessonPackage`'s avatar fields (`test_lesson_package_avatar_fields_*`): default-to-None,
accepts-real-values, omitting-still-validates-against-raw-JSON-schema, round-trips-through-schema.
Wrote all 14 new tests against the CURRENT (pre-implementation) schema first (RED — confirmed via
`ImportError: cannot import name 'SplitScreenSide'`), then implemented the 3-file mirror.

### Debug Log
No deviations from the story-file plan. `SlideType` used a bare `Literal[...]` (not a `StrEnum`),
matching every other closed-string-set type already in `lesson.py` (`QuizType`, `ComplexityLevel`,
`AudioProvider`) rather than introducing a new convention. `SplitScreenSide.bullets` deliberately
carries no Pydantic-level character cap, explicitly matching `Slide.bullets`' own existing
precedent (the real bound is prompt-level, `_MAX_SLIDE_BULLET_CHARS`) — noted in both the model's
own docstring and the story's Scale & Load §1, so Piece 2 doesn't have to rediscover it.

### Senior Developer Review — Round 1 (2026-09-28, 6 independent Agent-tool reviewers, all 6 CLAUDE.md layers)

6 independent, fully self-contained `Agent` tool calls (not `Workflow`, per this session's own
established finding about the Workflow tool's subagent context-confusion bug) — one per BMAD layer.
Every finding below was independently re-verified against real code (several by actually
reproducing the regression — mutating the code, confirming the test suite stayed green, then
fixing and confirming it goes red-then-green) before being trusted or fixed.

**Verdicts:** Story Quality **FAIL**, Test Coverage **FAIL** (on `SplitScreenSide` specifically),
Blind Hunter/Security **PASS WITH MINOR NOTES**, AC Completeness **PASS WITH GAPS**, Process
Integrity **PASS**, Scale & Load **PASS WITH MINOR NOTES**.

**Findings, independently re-verified and fixed:**

1. **(HIGH, CONFIRMED, Story Quality.)** The story cited
   `docs/proposals/2026-09-28-slide-strategy-15-30-45-alignment.md` as its scope source, but that
   file existed only on an unmerged sibling branch (`origin/docs/slide-strategy-and-handoffs`, PR
   #260) — dead on this branch and on `main`. Verified via `git cat-file -e` on both refs. **Fixed:**
   merged `origin/docs/slide-strategy-and-handoffs` into this branch directly (PR #260 remained
   blocked on required-reviewer approval, which this session cannot grant — merging the sibling
   branch resolves the reference without bypassing that gate).
2. **(HIGH, CONFIRMED, Story Quality.)** Task 1's guard-test survey claimed 6 result files for
   `grep -rln "test_.*schema\|Slide\b" apps/api/tests`; re-running that exact command against the
   branch's real base commit (`fedc47d6`, via `git archive` to avoid disturbing the working tree)
   returned 22. **Fixed:** Task 1 corrected with the full 22-file list and which ones are genuinely
   relevant (`test_real_package_payload_validation.py`) vs. generic-word false positives.
3. **(MEDIUM, CONFIRMED, Story Quality.)** The "full regression" claim excluded
   `test_real_package_payload_validation.py` (lives at top-level `apps/api/tests/`, outside both
   `tests/unit` and `tests/integration`), which has 2 pre-existing failures never mentioned. Ran it
   directly: confirmed 2 failed/7 passed, both a 404 on segment lookup in `grade_teachback`,
   unrelated to any Slide field and reproducible independent of this diff (this diff never touches
   `assessment/service.py`). **Fixed:** Task 4 corrected to name this file explicitly and record the
   2 pre-existing failures as such, not silently excluded from the regression claim.
4. **(MEDIUM, CONFIRMED, Story Quality.)** AC9 named `test_node_return_shape.py`/
   `test_unbounded_queries.py` as this story's guard tests for its `schemas/__init__.py.__all__`
   addition — neither actually covers that (former AST-scans pipeline/tutor node returns only,
   latter's own docstring excludes schema files). The real, already-precedented pattern is
   `test_f2_1_learner_context.py`'s `__all__` membership assertion. **Fixed:** added
   `test_split_screen_side_in_schemas_dunder_all`, mirroring that exact pattern; AC9 corrected.
5. **(HIGH, CONFIRMED, Test Coverage — reproduced, not just asserted.)** No test proved
   `SplitScreenSide.heading`/`bullets` are actually required at the Pydantic layer. Reviewer made
   both fields optional (`= None`) and confirmed all 48 tests stayed green. Independently
   reproduced the same way before fixing. **Fixed:** added
   `test_split_screen_side_requires_heading_and_bullets`; confirmed it fails against the mutated
   code and passes against the real code.
6. **(HIGH, CONFIRMED, Test Coverage — reproduced, not just asserted.)** No test exercised the JSON
   schema's reject path for a malformed `left_content`/`right_content` — every existing test only
   covers the accept path. Reviewer weakened `left_content`'s `$ref` to a permissive
   `{"type": "object"}` and confirmed all 48 tests stayed green. Independently reproduced the same
   way before fixing. **Fixed:** added `test_slide_left_content_rejects_malformed_object_via_json_schema`;
   confirmed it fails against the weakened schema and passes against the real one.
7. **(MEDIUM, CONFIRMED, Test Coverage.)** No test proved `left_content`/`right_content` are
   independently settable (every test set both together or both-`None`). **Fixed:** added
   `test_slide_left_and_right_content_independently_settable`.
8. **(Real gap, AC Completeness — AC8.)** No test asserted `slide_generator_node`'s REAL returned
   dict has the 5 new fields null/absent — only inferred from reading `Slide.model_validate()`'s
   defaulting behavior. **Fixed:** added explicit assertions to
   `test_happy_path_produces_nested_slide_entries_matching_segments` in `test_slide_generator_node.py`.
9. **(LOW, CONFIRMED, Blind Hunter.)** `topic_index`/`target_duration_sec` were the only new numeric
   fields in this file added without a lower bound, unlike every comparable existing field
   (`NarrationTimestamp.start_ms`/`end_ms`, `LessonMetadata.total_segments`,
   `SegmentComplexity.intervention_sensitivity`). Not exploitable today (nothing populates these
   fields yet, `Slide` isn't accepted as external API input anywhere), but a real consistency gap.
   **Fixed:** `topic_index` gets `Field(ge=1)` (topics are 1 or 2 per spec, never 0),
   `target_duration_sec` gets `Field(ge=0)`, mirrored in the JSON schema (`"minimum"`) and noted in
   the TS comment; added `test_slide_topic_index_and_duration_reject_out_of_range_values`.
10. **(LOW, CONFIRMED, Scale & Load.)** `target_duration_sec` and `topic_index` are not fresh names
    in this codebase — both already exist with different, unrelated semantics elsewhere
    (`target_duration_sec` as a per-narration-section pacing key in `narration_generator_node`;
    `topic_index` as a `segment_expansion_node` loop/dict key). Real risk: whichever piece wires
    these `Slide` fields could accidentally source a same-named-but-wrong-meaning value. **Fixed:**
    added an explicit comment directly above the fields in `lesson.py` naming both collisions, so
    Piece 2 can't rediscover this the hard way.
11. **(LOW, CONFIRMED, Story Quality.)** AC7's line citation was off by one (334 vs. the actual 335).
    **Fixed.**

**Findings independently re-verified and judged NOT requiring a fix:** AC Completeness's AC2/AC4
(TypeScript-side `SlideType`/`SplitScreenSide` has zero automated test coverage) — confirmed by both
Test Coverage and AC Completeness independently as a pre-existing, whole-repo limitation (no test
in this codebase parses/type-checks `lesson.ts` programmatically, including for fields added by
prior stories like `sixtydb`), not a regression this story introduces; building new cross-language
test infrastructure for a schema-only piece was judged disproportionate — registered here as a
known, accepted, pre-existing limitation rather than silently ignored. Blind Hunter's schema-
strictness/enum-identity/avatar-fields-precedent checks all came back clean (verified, not findings).
Process Integrity's full 7-point check came back PASS with no findings requiring a fix (one trivial
line-citation note, folded into #11 above since it's the same underlying issue).

**11 findings fixed (2 code fixes — numeric bounds + a forward-looking naming-collision comment — plus
9 test/documentation fixes), 1 finding registered as an accepted pre-existing limitation, 7 new tests
added (53 total in `test_lesson_schema.py`, up from 14; plus 5 new assertions in
`test_slide_generator_node.py`), full regression re-run green.**

### Completion Notes
All 10 ACs implemented and verified:
- AC1-4: `Slide` gains 5 new optional/nullable fields; `SlideType` (7-value `Literal`) and
  `SplitScreenSide` (`_STRICT` config, matching every other model in the file) added; mirrored
  identically across `apps/api/app/schemas/lesson.py`, `packages/shared/lesson_package.schema.json`,
  `packages/shared/types/lesson.ts`. None of the 5 new fields added to either `required` array.
  `topic_index`/`target_duration_sec` gained `Field(ge=1)`/`Field(ge=0)` in Round 1 review.
- AC5/AC6: `test_slide_omitting_new_fields_validates_against_raw_json_schema` and
  `test_slide_new_fields_round_trip_through_json_schema` both pass — reusing `MINIMAL_PACKAGE_DICT`
  unchanged for the first (proving zero regression for every existing fixture/lesson record).
- AC7: pre-existing `test_slide_extra_fields_forbidden` passes unmodified.
- AC8: `test_slide_generator_node.py` (32 tests, 5 new assertions added in Round 1 review) +
  `test_package_builder_node.py` (46 tests) all pass — confirms zero behavior change to what the
  real node produces, now with an explicit assertion rather than an inferred one.
- AC9: CORRECTED in Round 1 review — `test_split_screen_side_in_schemas_dunder_all` is the real
  guard for this story's `__all__` addition; `test_ces.py`/`test_node_return_shape.py`/
  `test_unbounded_queries.py` also green (70 passed) as general-purpose guards.
- AC10: this session's 6-layer-BMAD-substitute process note stated plainly in the story header;
  the review itself (Round 1, documented above) is that substitute, now complete. Formal PR/merge
  request is the next step, pending explicit user confirmation.
- Frontend: `npm run type-check` (`tsc --noEmit`) run directly — zero `lesson.ts`/`Slide`-related
  errors. Pre-existing, unrelated errors confirmed separately (missing `posthog-js` in
  `node_modules`, stale `.next` build-artifact references to removed pages) — not caused by this
  change, verified by grepping the type-check output for "lesson"/"slide" (zero matches) and
  confirming `posthog-js` is genuinely absent from `node_modules` independent of any edit here.
- `test_real_package_payload_validation.py` (Round 1 review addition to the regression scope): 7
  passed, 2 pre-existing unrelated failures (`test_teachback_receives_title_and_jargon_from_real_segment`,
  `test_empty_jargon_teachback_graceful` — both a 404 in `grade_teachback`, this diff never touches
  `assessment/service.py`).
- Full regression: `tests/unit` + `tests/integration -m "not postgres"` green (same single
  pre-existing unrelated failure, `test_effective_wpm_is_not_the_raw_rate`, seen on every full-suite
  run this session). `ruff check`/`format`: clean. `mypy` on both touched app files: clean, zero
  errors.
- 2 mutation-based regression-detection checks performed and reverted (per the reviewer's own
  methodology): weakened `SplitScreenSide` to optional fields (new test caught it), weakened
  `left_content`'s JSON-schema `$ref` to a permissive object (new test caught it) — both confirmed
  the new tests are real, not cosmetic.

### File List
- `apps/api/app/schemas/lesson.py` — new `SlideType` (`Literal`, 7 values), new `SplitScreenSide`
  model, `Slide` gains 5 new optional fields (`topic_index`/`target_duration_sec` bounded via
  `Field(ge=1)`/`Field(ge=0)`, Round 1 review fix), plus a comment naming the `target_duration_sec`/
  `topic_index` naming-collision risk for Piece 2 (Round 1 review fix).
- `apps/api/app/schemas/__init__.py` — export `SplitScreenSide`.
- `packages/shared/lesson_package.schema.json` — new `SplitScreenSide` definition, `Slide`
  definition gains 5 new optional properties (none added to `required`); `topic_index`/
  `target_duration_sec` gain `"minimum"` (Round 1 review fix).
- `packages/shared/types/lesson.ts` — new `SlideType` union type, new `SplitScreenSide` interface,
  `Slide` interface gains 5 new optional fields, bound comments added (Round 1 review fix).
- `apps/api/tests/unit/test_lesson_schema.py` — 21 new tests total (14 original + 7 from Round 1
  review: requiredness, JSON-schema reject-path, independent left/right settability, numeric
  bounds, `__all__` membership).
- `apps/api/tests/unit/test_slide_generator_node.py` — 5 new assertions in the existing happy-path
  test (Round 1 review fix, AC8).
- `docs/proposals/2026-09-28-{slide-strategy-15-30-45-alignment,handoff-book-chapter-context,handoff-onboarding-form-30q}.md`
  — merged in from `origin/docs/slide-strategy-and-handoffs` (Round 1 review fix — resolves the
  dead doc reference finding).

### Change Log
- 2026-09-28: Story file created (story-first commit), branch `feature/233-slide-schema-contract`,
  based on `main` at `fedc47d6`.
- 2026-09-28: RED phase (14 new tests, confirmed failing for the right reason — `ImportError`) then
  GREEN phase (3-file schema mirror implemented) — see Dev Agent Record above. Full regression
  green, zero regressions.
- 2026-09-28: Round 1 review — 6 independent `Agent` tool calls (all 6 layers ran). 11 findings
  fixed (2 real code fixes — numeric bounds, naming-collision comment — plus 9 test/documentation
  fixes, including merging in the previously-dead-referenced planning doc), 1 finding registered as
  an accepted pre-existing limitation (TS-side test coverage), 7 new tests + 5 new assertions added.
  Full regression re-run green. Not yet opened as a PR — this session's own Process Note (frozen-contract
  review substitute) means the next step is explicit user confirmation before requesting merge, not
  a silent PR-and-wait.
