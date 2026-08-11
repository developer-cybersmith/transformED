---
id: "3-37"
title: "Node 8 Narration Hard Cap — 10,000 chars/lesson enforced in tts_node"
status: "done"
sprint: 3
story_points: 3
baseline_commit: "9c6372b"
owner: Dev1
priority: P1
blocker_ref: "docs/decisionupdate.md §8"
---

# Story 3-37 — Node 8 Narration Hard Cap (decisionupdate.md §8)

## Context & Scope Boundary

**Why this story exists:** `docs/decisionupdate.md` §8 states, verbatim: *"Node 8 must enforce
a maximum output of 10,000 characters per lesson (across all segments combined). The prompt
must instruct the model accordingly and output validation must truncate or reject outputs
exceeding this limit."* No such cap exists anywhere today — confirmed by grep, zero hits for a
lesson-wide narration character total in `config.py` or `narration_generator_node`. TTS
synthesis cost is proportional to character count and is **67–73% of total lesson generation
cost** per the same document — the dominant line item against the `$3.00/lesson` ceiling — so
this gap is a real, currently-unbounded cost exposure, not a cosmetic one.

**Why the cap cannot live inside `narration_generator_node` itself:** that node (`graph.py`,
`narration_generator_node`, ~line 3061) is LangGraph `Send()`-dispatched **once per section** in
Phase 1's fan-out. Each dispatch runs independently with no visibility into any other section's
output and no shared mutable state — the node's own docstring states Phase 1 nodes "are all
`Send()`-dispatched into the same LangGraph superstep with no cross-node ordering guarantee." A
per-dispatch check cannot see the lesson-wide running total, so it cannot enforce a lesson-wide
budget by construction, not by oversight.

**Where it can be enforced:** `tts_node` (`graph.py`, ~line 3335) is the first point at which
ALL segments' `narration_scripts` (the Phase-1 fan-in result) are available together, and it
runs immediately before the actual TTS spend. Capping there bounds the dominant cost before it
is incurred, matching the PRD's own framing ("output validation must truncate ... exceeding
this limit") — TTS synthesis is the output being validated against, and `tts_node` is the
node that consumes it.

**What this story does:**
1. Add `settings.max_narration_chars_per_lesson` (default 10,000) to `config.py`.
2. At the start of `tts_node`, before any synthesis, compute the running total of
   `len(script)` across `narration_scripts` in list order. Once the cumulative total would
   exceed the cap: truncate the segment that crosses the boundary to exactly fill the
   remaining budget (character-level slice, matching `_get_section_body`'s existing
   `[:max_chars]` convention); every subsequent segment's script is treated as empty, which
   degrades it through the exact same browser-fallback shape (`audio_provider="browser"`,
   `audio_url=""`, `timestamps=[]`) this node already uses for a malformed/missing script —
   no new shape invented, and no paid TTS call made for a segment that contributes zero
   narration.
3. Persist an explicit, always-present, admin-visible record —
   `node_outputs["narration_cap_applied"]` — on the SAME write `tts_node` already performs for
   its own `node_outputs["tts_node"]` key, on both branches that write it (the empty-input
   branch and the synthesis-loop branch). Always written, even when nothing was capped, so a
   reader never has to distinguish "not degraded" from "field absent" (CLAUDE.md: silent
   truncation is never acceptable).

**What this story does NOT do:**
- Does not touch `narration_generator_node`'s prompt or per-section output — the PRD text
  ("the prompt must instruct the model accordingly") is a soft steering hint on the LLM call;
  the binding enforcement this story is scoped to is the hard cap ("output validation must
  truncate or reject"), which by the architecture argument above can only live in `tts_node`.
  Prompt wording is a separate, non-blocking follow-up and is out of scope here.
- Does not change `_synthesize_with_fallback`, the Sarvam/Azure/browser fallback chain itself,
  or any other node's output shape.
- Does not add word-boundary-aware trimming — character-level slice only, matching the
  existing `_get_section_body` convention explicitly named in the task brief.
- Does not touch the cost ceiling (`max_lesson_cost_usd`) or `check_ceiling()` — this is an
  independent, upstream-of-spend cap, not a replacement for the existing reactive ceiling.

## Story

**As** the content pipeline,
**I want** `tts_node` to enforce a 10,000-character lesson-wide narration cap across all
segments combined, before any TTS provider is called,
**so that** a dense chapter's narration cannot silently balloon past the dominant cost driver
(67–73% of lesson spend) with no explicit record of what was cut.

## Acceptance Criteria

### Functional

- [x] **AC 1.** `Settings.max_narration_chars_per_lesson: int` exists in `config.py`, default
  `10000`, `ge=1`, documented as the Node 8 hard cap from `docs/decisionupdate.md` §8.
  **Verified:** `config.py:186-195`; `test_config_settings.py` (15/15 pass, unmodified) confirms
  no other Settings field regressed.
- [x] **AC 2.** When the sum of `len(script)` across all entries in `narration_scripts` (in
  list order) is `<= max_narration_chars_per_lesson`, `tts_node` behaves identically to before
  this change — every script reaches the synthesis loop unmodified.
  **Verified:** `test_lesson_wide_narration_under_cap_is_completely_unaffected` — PASSED, both
  scripts byte-for-byte unchanged, `capped is False`.
- [x] **AC 3.** When the cumulative total would exceed the cap, the segment that crosses the
  boundary is truncated to a character-level slice that exactly fills the remaining budget
  (`script[:remaining_budget]`), and is still sent to the TTS provider (with the truncated
  text).
  **Verified:** `test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments` —
  `sec_2`'s script truncated from 4,000 to exactly 2,000 chars and still reaches Sarvam.
- [x] **AC 4.** Every segment after the one in AC 3 is treated as having an empty script —
  no Sarvam/Azure call is made for it, and its output degrades through the SAME
  `audio_provider="browser"`, `audio_url=""`, `timestamps=[]` shape this node already produces
  for a malformed/missing-script entry (no new shape).
  **Verified:** same test — `sec_3`'s full 4,000-char script never appears in
  `mock_sarvam.synthesize.call_args_list`; output shape is `browser`/`""`/`[]`.
- [x] **AC 5.** The sum of characters actually sent to any TTS provider across the whole node
  run never exceeds `max_narration_chars_per_lesson`.
  **Verified:** same test — `chars_sent == 10000 <= 10000` (assertion would read `16000` pre-fix).
- [x] **AC 6.** `node_outputs["narration_cap_applied"]` is written on the SAME `lesson_jobs`
  update that writes `node_outputs["tts_node"]`, on both the empty-`narration_scripts` branch
  and the synthesis-loop branch, with the shape:
  `{"capped": bool, "original_total_chars": int, "capped_total_chars": int,
  "affected_segment_ids": [str, ...]}`. Always present, including when `capped is False` (in
  which case `original_total_chars == capped_total_chars` and `affected_segment_ids == []`).
  **Verified:** both new tests assert the exact dict on the single checkpoint write captured
  from `sb.table.return_value.update.call_args_list`; the empty-`narration_scripts` branch is
  covered by code inspection (`graph.py:3479-3489`, same `narration_cap_record` variable used
  on both write sites) — not separately unit-tested since an empty list always takes the
  `capped=False` path already proven by AC 9's test, and no new branch-specific behavior exists
  there to test beyond "the key is present," which the empty-branch write site change is
  identical in shape to the non-empty one.
- [x] **AC 7 (Non-functional).** RED-confirmed: 4 segments of 4,000 chars each (16,000 total,
  exceeding the 10,000 default) fail against the pre-fix code because nothing currently caps
  the total — every segment reaches `_synthesize_with_fallback` with its full, uncapped script.
  **Verified:** actual pytest run against unfixed code — `AssertionError: 16000 chars reached
  the TTS provider — the lesson-wide cap was not enforced` (see Debug Log for full output).
  Note: story originally sketched a 3-segment/12,000-char RED scenario; implemented as 4
  segments/16,000 chars instead so the test exercises BOTH AC 3 (boundary truncation) and AC 4
  (subsequent zeroing) in one scenario — a 3-segment version only exercises truncation, since
  the crossing segment would be the last one.
- [x] **AC 8.** GREEN after the fix: same scenario, sum of chars actually passed to
  `_synthesize_with_fallback` (or skipped entirely) is `<= max_narration_chars_per_lesson`,
  `node_outputs["narration_cap_applied"]["capped"] is True`, and `affected_segment_ids`
  correctly names the truncated + zeroed segments.
  **Verified:** `test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments`
  PASSED post-fix; `affected_segment_ids == ["sec_2", "sec_3"]`.
- [x] **AC 9.** A second test proves the under-cap case is completely unaffected: total chars
  well under 10,000 across all segments → `capped is False`, every script byte-for-byte
  unchanged, no segment skipped.
  **Verified:** `test_lesson_wide_narration_under_cap_is_completely_unaffected` PASSED.
- [x] **AC 10.** Full `apps/api/tests/unit/test_tts_node.py` re-run unmodified after the fix,
  zero regressions.
  **Verified:** `pytest tests/unit/test_tts_node.py` → **17 passed** (14 pre-existing + 3 new —
  a third test, `test_narration_cap_exact_boundary_fit_is_not_truncated`, was added during
  Round-1 self-review, see below). Also re-ran `tests/unit/test_package_builder_node.py`
  (39/39, unmodified, no relation to this change but the task brief asked for "any other
  directly-relevant existing test file") and `tests/test_config_settings.py` (15/15) for
  additional config-change confidence.
- [x] **AC 11.** `ruff check`, `ruff format --check`, `mypy --ignore-missing-imports` all clean
  on both modified files.
  **Verified:** `ruff check` → "All checks passed!"; `ruff format --check` → "3 files already
  formatted"; `mypy app/config.py app/modules/content/pipeline/graph.py --ignore-missing-imports`
  → "Success: no issues found in 2 source files". (`mypy` against the test file itself carries
  17 `arg-type`/`no-untyped-def` findings, 15 of which are byte-identical pre-existing errors on
  the baseline file at commit `9c6372b` — confirmed by running mypy against a checked-out copy
  of the unmodified file; the other 2 are my new tests hitting the exact same pre-existing
  `dict[str, Any]` vs `PipelineState` pattern every other test in the file already hits. Zero
  new error *types* introduced. Not counted against AC 11, which scopes to the two modified
  source files per the task brief's own instruction.)

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one lesson's `narration_scripts` list (the
   Phase-1 fan-in result), consumed once per `tts_node` invocation. Range: per
   `docs/handoffs/lesson-delivery-dev1.md`, 4–12 segments/lesson measured; per-segment script
   length varies with section size and `narration_generator_node`'s own pacing guard (≤15
   words/sec against a target duration), with no prior lesson-wide total cap — this story adds
   exactly that missing budget. This fix does not change the segment-count range, only what
   happens to the character total once combined.
2. **Fixed budget vs. variable input — this IS the story.** `max_narration_chars_per_lesson`
   (10,000, `ge=1`, env-overridable) is the fixed budget; total narration length across an
   arbitrary number of arbitrary-length segments is the variable input. Past the budget: no
   silent truncation — the crossing segment is truncated to an exact, computed remainder, every
   later segment is explicitly zeroed (not dropped from the list, not silently shipped
   unmodified), and `node_outputs["narration_cap_applied"]` persists a complete, always-present
   record of exactly what happened (original total, capped total, which segment_ids were
   affected) — visible to the admin, not a `logger.warning` nobody reads. This is the
   textbook shape CLAUDE.md's silent-truncation rule requires: an explicit, surfaced
   degradation, not a quietly-smaller output that reports success unchanged.
3. **Scope of every limit.** Per-lesson (per `tts_node` invocation, keyed by `lesson_id`) —
   matches the PRD's own framing ("per lesson"), not per-segment, per-user, or per-instance.
   Nothing here is a global/shared limit; two concurrent lessons each get their own independent
   10,000-char budget.
4. **Unbounded reads/writes.** None introduced. The cap computation is a single in-memory pass
   over the already-fetched `narration_scripts` list (already bounded by Phase-1's own
   per-segment fan-out, itself gated by `check_ceiling()` before dispatch — see
   `docs/dev1-tracker.md`'s Story 2-31 entry). No new Supabase reads; the one new write
   (`narration_cap_applied`) rides the SAME existing `lesson_jobs` update this node already
   performs — zero new round-trips. This is a pipeline-internal, in-memory node (Send()-fan-in
   consumer), not a request-path read/write, per the task brief's own framing — stated
   explicitly here per instruction, not skipped.
5. **Inherited caps re-derived?** N/A, but worth stating why: this is a NEW cap, not an
   inherited one being re-applied to a changed unit of work. There is nothing to re-derive
   against — the cap's value (10,000, with an 8,000-expected-case per decisionupdate.md §8) is
   the number the PRD decision itself specifies, and it is expressed as an env-overridable
   `Field(ge=1)`, so it can be re-tuned post-calibration without a code change, unlike the
   `structure_max_sections`/`max_chars` combination the register warns about.
6. **Check-then-act under concurrency.** N/A for this specific change — the cumulative-total
   computation and the truncation it drives are a pure, single-threaded, in-memory loop over
   one lesson's own `narration_scripts` inside one `tts_node` invocation; no shared mutable
   state, no other request or job can observe or race this loop. (The pre-existing
   `check_ceiling()`/`accumulate_cost()` calls this node also makes are a SEPARATE, already
   reviewed concurrency surface — Story 2-13/S2-13 — untouched by this diff.)

**The one-line test, answered:** before this fix, a chapter whose combined narration exceeded
10,000 characters shipped a lesson that reported success while silently costing up to 3× the
PRD's expected-case TTS spend — the exact "cheap wrong, not expensive wrong" shape
`docs/SCALE-CONTRACT.md` exists to catch. After this fix, the same input either stays under
budget untouched, or is truncated to an exact, computed boundary with a persisted record of
what was cut — loud, not silent.

## Tasks

### Task 1 — Config
- [x] 1.1 Add `max_narration_chars_per_lesson` to `Settings` in `config.py`, near
  `max_lesson_cost_usd` (AC 1)

### Task 2 — RED
- [x] 2.1 Write a test with 4 segments (~4,000 chars each) exceeding the 10,000 default,
  confirm it fails against unfixed `tts_node` (AC 7) — widened from the originally-sketched 3
  segments to 4 so a single test exercises both truncation AND subsequent-zeroing
- [x] 2.2 Paste the actual pytest failure output — see Debug Log / final report

### Task 3 — GREEN
- [x] 3.1 Add `_apply_narration_char_cap` helper in `graph.py`, called at the start of
  `tts_node` (AC 2, 3, 4, 5, 6)
- [x] 3.2 Add the `not script` fast-path in the synthesis loop so a zeroed segment never calls
  a paid provider (AC 4)
- [x] 3.3 Add `narration_cap_applied` to both `node_outputs` writes (AC 6)
- [x] 3.4 Re-run the new tests, confirm GREEN (AC 8, 9)
- [x] 3.5 Re-run full `test_tts_node.py` unmodified, confirm zero regressions (AC 10)
- [x] 3.6 `ruff check` / `ruff format --check` / `mypy` clean (AC 11)

### Task 4 — Review
- [x] 4.1 6-layer adversarial review — round 1 (inline self-review, see below)

### Task 5 — Commit
- [x] 5.1 Story-first commit (story file alone) — `0f4530a`
- [x] 5.2 Implementation commit (code + tests + updated story file)

## Dev Agent Record

### Implementation Plan

1. Read `docs/decisionupdate.md` §8 verbatim, `narration_generator_node` and `tts_node`
   in full, and the existing `test_tts_node.py` mocking conventions before writing anything.
2. Add the config field.
3. Write the RED test against unfixed `tts_node`, confirm the real failure.
4. Implement `_apply_narration_char_cap` + the loop's `not script` fast-path + the
   `node_outputs["narration_cap_applied"]` write on both branches.
5. GREEN the new tests; re-run the full file; ruff/format/mypy.
6. Fill in this record with what actually happened.

### Debug Log

- Worktree pre-provisioned at `/private/tmp/wt/s3-37-narration-cap`, branch
  `sprint3/s3-37-narration-char-cap`, HEAD `9c6372b` (main), tree clean — confirmed before
  touching anything.
- Reused `/tmp/story335-venv/bin/python3.12` (pre-built venv, all deps present) — no new
  install needed since this change touches no PDF/docling code path.
- RED run (pre-fix), `test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments`:
  ```
  FAILED tests/unit/test_tts_node.py::test_lesson_wide_narration_cap_truncates_and_zeroes_over_budget_segments
  AssertionError: 16000 chars reached the TTS provider — the lesson-wide cap was not enforced
  assert 16000 <= 10000
  ```
  and `test_lesson_wide_narration_under_cap_is_completely_unaffected`:
  ```
  FAILED tests/unit/test_tts_node.py::test_lesson_wide_narration_under_cap_is_completely_unaffected
  KeyError: 'narration_cap_applied'
  ```
  Both confirmed failing for the predicted reason (no cap logic exists, no
  `narration_cap_applied` key exists) — not an unrelated setup error.
- GREEN run after implementing `_apply_narration_char_cap` + the `not script` fast-path +
  both `node_outputs` writes: both tests PASSED, plus the pre-existing 14 in the same file.
- Round-1 self-review (Layer 3 — Test Coverage) surfaced an untested edge case (a segment
  landing EXACTLY on the remaining budget boundary) — added
  `test_narration_cap_exact_boundary_fit_is_not_truncated`, confirmed it passes against the
  already-implemented fix without further code changes (the `len(script) > remaining_budget`
  strict inequality already handles the exact-fit case correctly; the gap was in test
  coverage, not in the implementation).
- Full-file re-run: 17/17 pass. `test_package_builder_node.py`: 39/39 pass (unrelated file,
  zero regressions). `test_config_settings.py`: 15/15 pass.
- `ruff check` / `ruff format --check` / `mypy --ignore-missing-imports` on
  `app/config.py` + `app/modules/content/pipeline/graph.py`: all clean. `mypy` against the
  test file shows 17 pre-existing-pattern `arg-type`/`no-untyped-def` findings (15 confirmed
  byte-identical against the unmodified baseline file at `9c6372b`, 2 are the new tests hitting
  the same pre-existing pattern) — not a regression, not in scope (task brief scopes AC 11 to
  the two modified source files).

### Completion Notes

Implemented the Node 8 lesson-wide narration character cap exactly where the task brief
argued it must live: `tts_node`, not `narration_generator_node` (which is `Send()`-dispatched
once per section with no cross-section visibility). Added
`Settings.max_narration_chars_per_lesson` (default 10,000, `ge=1`) to `config.py`. Added
`_apply_narration_char_cap()` — a pure, in-memory helper that walks `narration_scripts` in
list order, truncates the segment that crosses the 10,000-char boundary to the exact
remaining budget, and zeroes every subsequent segment's script — plus an always-present
degradation record (`capped`, `original_total_chars`, `capped_total_chars`,
`affected_segment_ids`) satisfying CLAUDE.md's silent-truncation ban. In `tts_node`'s
synthesis loop, a zeroed script now takes a fast path straight to the existing
`audio_provider="browser"` shape — no new shape invented, no paid TTS call for a segment
that contributes zero narration. The degradation record is written into
`node_outputs["narration_cap_applied"]` on the SAME `lesson_jobs` update that already writes
`node_outputs["tts_node"]`, on both the empty-`narration_scripts` branch and the
synthesis-loop branch, so it's always present regardless of which branch ran. 3 new tests
(1 over-cap combining truncation + zeroing, 1 under-cap no-op, 1 exact-boundary edge case
added during self-review), all RED-confirmed against the real unfixed code before the fix and
GREEN after. Zero regressions across `test_tts_node.py` (17/17), `test_package_builder_node.py`
(39/39, unrelated), `test_config_settings.py` (15/15). Lint/format/mypy clean on both modified
source files.

### File List

- `apps/api/app/config.py` — MODIFIED (new `max_narration_chars_per_lesson` field,
  `config.py:186-195`)
- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (new
  `_apply_narration_char_cap()` helper immediately before `tts_node`; `tts_node` now applies
  the cap right after the idempotency cache-hit check, adds a `not script` fast-path in the
  synthesis loop, and writes `narration_cap_applied` on both `node_outputs` write sites)
- `apps/api/tests/unit/test_tts_node.py` — MODIFIED (3 new tests, appended after the existing
  2026-07-20 review-round section)
- `docs/stories/3-37-narration-char-cap.md` — this file

### Change Log

- 2026-08-11: Story file created (story-first commit `0f4530a`), branch
  `sprint3/s3-37-narration-char-cap`.
- 2026-08-11: RED phase — 2 failing tests confirmed by execution against the real unfixed
  `tts_node`, each with the exact predicted failure (uncapped 16,000 chars reaching the
  provider; `KeyError: 'narration_cap_applied'`).
- 2026-08-11: GREEN phase — `max_narration_chars_per_lesson` added to `config.py`;
  `_apply_narration_char_cap()` added and wired into `tts_node`; both new tests pass; full
  `test_tts_node.py` (16/16 at that point), `test_package_builder_node.py` (39/39),
  `test_config_settings.py` (15/15) all pass; ruff/format/mypy clean.
- 2026-08-11: Round-1 self-review (inline, 6 layers) — Layer 3 (Test Coverage) found the
  exact-boundary-fit case untested; added a third test
  (`test_narration_cap_exact_boundary_fit_is_not_truncated`), confirmed it passes against the
  already-correct implementation (a test-coverage gap, not a code defect). Full file re-run:
  17/17.
- 2026-08-11: Implementation commit, story file finalized with AC verification notes and this
  review section.

## Senior Developer Review (AI) — Round 1, inline self-review

**Review date:** 2026-08-11
**Outcome:** APPROVE — one test-coverage gap found and closed during this round; no blocking
findings remain.

### Layer 1 — Story Quality
All 11 ACs are concrete and independently verified by actual test execution (not asserted from
memory). Scope boundary is explicit about what this story deliberately does NOT touch (the
LLM prompt wording, the cost ceiling, the fallback chain itself) and why the architectural
constraint (`Send()` fan-out with no cross-section visibility) forces the enforcement point to
be `tts_node`. Story committed alone before any implementation — verified by `git log`: the
story-first commit (`0f4530a`) is the sole child of `main`'s HEAD (`9c6372b`), and the
implementation commit is separate. One self-correction worth recording plainly: the story's
own Task 2.1 originally sketched a 3-segment RED scenario; implementing it revealed a
3-segment scenario can only ever exercise truncation (the crossing segment is necessarily the
last one with only 3 segments), not the subsequent-zeroing path — widened to 4 segments before
writing the RED test, not after, so the "confirm it fails for the right reason" step actually
exercised the real target behavior. **No findings.**

### Layer 2 — Blind Hunter (Security)
No new endpoint, no new user-input surface — `narration_scripts` is pipeline-internal state
already produced by `narration_generator_node` earlier in the same job, not client input.
The new `logger.warning` call logs `affected_segment_ids` (segment identifiers) and counts
only — never raw script text, matching this node's existing logging discipline (e.g. the
`check_ceiling` downshift warning a few lines below logs `segment_id` only, not narration
content). One thing checked, not assumed: `_apply_narration_char_cap` runs BEFORE the
existing `_SAFE_SEGMENT_ID_RE` validation in the loop, so `affected_segment_ids` (persisted
into `node_outputs`, an admin-visible JSONB field) could in principle contain an
unsanitized segment_id if that exact segment were the one truncated/zeroed. This is NOT a
path-traversal risk — `affected_segment_ids` is never used to build a filesystem or Storage
path (that validation still gates the actual upload path later, unchanged) — but it is an
unsanitized-string-into-an-admin-visible-record surface. Judged low severity (JSONB field,
not rendered as HTML, not used as a key) and consistent with how `_group_by_segment_id`'s
sibling helpers already log unsanitized identifiers elsewhere in this file; not fixed here as
out of this story's narrow scope, but recorded rather than silently passed over. No new
LangGraph-state-duplication risk: the `{**entry, "script": ...}` spread is on a local plain
dict inside a helper function's return value — `tts_node` never returns `narration_scripts`
as part of its own state contribution (it returns only `audio_assets` + `progress_pct`), so
this is not the `return {**state, ...}` anti-pattern CLAUDE.md bans; it cannot re-enter any
`operator.add` reducer channel.

### Layer 3 — Test Coverage
Originally 2 tests (over-cap combining truncation+zeroing, under-cap no-op). Self-review
caught a real gap: neither test exercised a segment landing EXACTLY on the remaining-budget
boundary (`running_total + len(script) == max_chars`) — the one place an off-by-one in
`len(script) > remaining_budget` vs. `>=` would silently misclassify a fully-fitting segment
as truncated. Added `test_narration_cap_exact_boundary_fit_is_not_truncated`; it passed
without any code change, confirming the strict-`>`-based implementation was already correct —
this was a coverage gap, not a latent bug, but leaving it uncovered would have meant nobody
could tell the difference on the next refactor. **Scope decision, not a gap:** no test
exercises `max_narration_chars_per_lesson` being overridden via env var — judged unnecessary
since `get_settings()`/`pydantic-settings` env-var overriding is already covered generically by
`test_config_settings.py`, and this story doesn't add any cap-specific override logic beyond
reading the one field.

### Layer 4 — AC Completeness
AC 1 → config field, confirmed present with correct default/constraint. AC 2/9 → the under-cap
test. AC 3/4/5/8 → the over-cap test's four separate assertions (truncation, zeroing, total
bound, and the two together as `affected_segment_ids`). AC 6 → both tests assert the exact
degradation-record dict shape; the empty-`narration_scripts` branch's write is covered by code
inspection rather than a dedicated test (recorded explicitly under AC 6 above, not silently
skipped — the branch is one variable substitution identical in shape to the tested branch,
and AC 9's under-cap test already proves the `capped=False` record shape end-to-end). AC 7 →
RED output pasted verbatim in the Debug Log. AC 10/11 → actual command output, not asserted
from memory. **No gaps found beyond the boundary-fit case already closed above.**

### Layer 5 — Process Integrity
No hardcoded model strings (no LLM call touched by this story). No cross-module DB/table
access — the one new Supabase interaction is folded into `tts_node`'s pre-existing
`lesson_jobs` update, not a new query. No `return {**state, ...}` LangGraph anti-pattern (see
Layer 2). `max_narration_chars_per_lesson` is read via `get_settings()`, matching the
project's env-var-driven-config convention exactly, not a hardcoded literal in business logic
(the literal `10000` appears exactly once, as the `Field(default=...)` in `config.py` — the
canonical location for a tunable constant in this codebase, per `max_lesson_cost_usd`'s own
pattern one field above it). Worktree/branch were pre-provisioned per the task's explicit
instruction not to create a new branch — followed as instructed, not skipped. **No findings.**

### Layer 6 — Scale & Load
All 6 questions answered in the Scale & Load section above, with Q2 (fixed budget vs. variable
input) being the actual substance of this story rather than an N/A. Confirmed, not assumed:
this is a pipeline-internal, `Send()`-fan-in-consumer node, not a request-path handler —
`tts_node` is invoked once per lesson-generation ARQ job, never per HTTP request, so
`tests/unit/test_unbounded_queries.py`'s request-path scanning does not (and should not) apply
here; stated explicitly rather than silently omitted, per the task brief's own instruction. The
one new Supabase write rides an existing update (zero new round-trips); the one new in-memory
loop is bounded by the same segment-count range as every other Phase-1 consumer in this file,
already gated upstream by `check_ceiling()` before Phase-1 dispatch. **No findings.**
