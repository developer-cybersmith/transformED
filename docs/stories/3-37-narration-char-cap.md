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
  from `sb.table.return_value.update.call_args_list`. Round-2 review (Cynical Review) correction:
  this section previously claimed the empty-`narration_scripts` branch was "proven" by AC 9's
  test — that test runs `_base_state()` with 2 non-empty short segments and never actually
  exercises a truly empty list, so the claim was an inferential leap, not a demonstrated fact.
  `test_narration_cap_empty_narration_scripts_list_is_uncapped_by_construction` now runs
  `narration_scripts=[]` directly and asserts the exact `capped=False`/`0`/`0`/`[]` record on
  the empty-branch write site (`graph.py`, the `if not narration_scripts:` branch) — closing the
  gap for real rather than re-describing it.
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
  **Verified (Round 2, superseding the Round-1 number below):**
  `pytest tests/unit/test_tts_node.py` → **21 passed** (14 pre-existing + 3 Round 1 + 4 Round 2:
  a dedicated empty-`narration_scripts` case, out-of-order fan-in reordering, a non-dict entry,
  and a Devanagari grapheme-boundary case — see the Round 2 review section for why each was
  added). `apps/api/tests/unit/test_admin_router.py` → **27 passed** (20 pre-existing + 4 Round
  2, for the new `narration_capped` admin-visibility field). Full `tests/unit` +
  `tests/integration -m "not postgres"` (matching CI's gating command exactly): **1058 passed,
  6 skipped, 79 deselected**, zero regressions. *(Round 1 originally reported 17/17 here, plus
  `test_package_builder_node.py` 39/39 and `test_config_settings.py` 15/15 individually — both
  still pass unmodified and are included in the 1058 above.)*
- [x] **AC 11.** `ruff check`, `ruff format --check`, `mypy` all clean on the modified source
  files, and repo-wide (CI scope).
  **Verified (Round 2, superseding the Round-1 number below):** `ruff check .` (repo-wide) →
  "All checks passed!" (one real `E501` line-too-long was found in the new
  `admin/router.py` code during this pass and fixed). `ruff format --check` on all 5 touched
  files → clean (4 unrelated pre-existing files elsewhere in the repo would reformat; confirmed
  not in this diff, not touched). `mypy app/config.py app/modules/content/pipeline/graph.py
  app/modules/admin/router.py --ignore-missing-imports` → "Success: no issues found in 3 source
  files". `mypy app` (full package, matching CI's `mypy app` exactly) → 45 pre-existing errors
  in 4 files this story never touches, confirmed byte-identical before/after this diff via
  `git stash`. (`mypy` against the two touched test files carries `arg-type`/`no-untyped-def`
  findings — confirmed by running mypy against a checked-out copy of each unmodified baseline
  file at commit `9c6372b`/`main` that every one of them is the same pre-existing
  `dict[str, Any]` vs `PipelineState` pattern every test in `test_tts_node.py` already hits,
  plus this round's own 7 new call sites of the identical pattern. Zero new error *types*.
  Not counted against AC 11, which scopes to modified source files, not test files — see the
  Round 2 review section for the independent re-verification of this exact claim, including
  the parts of it that were fair pushback vs. confirmed-true.)
  *(Round 1 originally reported "2 source files"/17 test-file findings before Round 2 added
  `admin/router.py` and 7 more tests.)*

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
- [x] 1.1 Add `max_narration_chars_per_lesson` to `Settings` in `config.py`, in the "Cost
  limits (PRD §12)" block alongside `max_lesson_cost_usd`/`max_daily_spend_per_user_usd` (AC 1)
  — Round-2 review (Cynical Review) correction: the field is inserted directly after
  `max_daily_spend_per_user_usd` ("Daily per-user AI spend cap"), not directly after
  `max_lesson_cost_usd` as originally stated here; both are in the same cost-limits block, but
  the earlier wording named the wrong immediate neighbor

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
- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (Round 1: new
  `_apply_narration_char_cap()` helper immediately before `tts_node`; `tts_node` now applies
  the cap right after the idempotency cache-hit check, adds a `not script` fast-path in the
  synthesis loop, and writes `narration_cap_applied` on both `node_outputs` write sites.
  Round 2: `_apply_narration_char_cap` rewritten to sort by true section order
  (`_segment_order_key`), drop non-dict entries defensively, and truncate on a grapheme-safe
  boundary (`_trim_to_grapheme_boundary`); `lesson_id` now threaded through for log
  correlation; new `unicodedata` import)
- `apps/api/app/modules/admin/router.py` — MODIFIED (Round 2: new `JobSummary.narration_capped`
  field + `_job_row_to_summary` now reads `node_outputs["narration_cap_applied"]["capped"]`
  off the row `select("*")` already fetches, instead of discarding it)
- `apps/api/tests/unit/test_tts_node.py` — MODIFIED (Round 1: 3 new tests, appended after the
  existing 2026-07-20 review-round section. Round 2: 4 more — empty-list AC 6 coverage,
  out-of-order fan-in reordering, non-dict entry defense, Devanagari grapheme-safe truncation)
- `apps/api/tests/unit/test_admin_router.py` — MODIFIED (Round 2: 4 new tests for
  `narration_capped`)
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
- 2026-08-12: Round 2 — real `/bmad-code-review`, 4 independent parallel agents. Two
  independently-confirmed real defects fixed: fan-in order was trusted directly even though
  `narration_scripts` is a `Send()`-fed `operator.add` reducer with no cross-call ordering
  guarantee (could truncate/zero an arbitrary segment, not necessarily the lesson's tail);
  a non-dict `narration_scripts` entry crashed the whole node via an unguarded `.get(...)`.
  Also fixed: a non-grapheme-safe raw character slice could split a Devanagari base character
  from its combining vowel sign at the cap boundary (Sarvam Bulbul v2 is this repo's primary
  TTS provider); the degradation record was persisted but never read back out by any admin
  endpoint (`JobSummary` enumerated 9 fields, none of them `node_outputs`) — added
  `narration_capped` to the admin job-summary response; the new log line was missing
  `lesson_id`; the "always returns a copy" docstring claim was previously false for the
  under-budget fast path and for in-budget entries on the capped path — now genuinely true;
  the `"<unknown>"` placeholder for a missing segment_id was ambiguous across multiple affected
  entries — now unique per position. Also corrected: the AC 6 self-review previously cited a
  test that didn't actually cover the empty-list branch — added a dedicated test instead of
  just fixing the words. 7 new tests total (3 in `test_tts_node.py`'s ordering/non-dict/
  grapheme cases + 1 dedicated empty-list case, 3 in `test_admin_router.py`), each RED-confirmed
  by reverting the relevant source file alone via `git stash` and re-running against the
  pre-round-2 code. One finding (unsanitized `segment_id` reaching `affected_segment_ids`
  before `_SAFE_SEGMENT_ID_RE` runs) remains accepted-not-fixed, same reasoning as Round 1.
  Two reviewer claims independently re-checked and found FALSE (not fixed, disposition
  recorded): the 67–73% TTS-cost figure and the `_get_section_body` truncation-convention
  citation are both real and verifiable in-repo, just not inside the diff itself. Full
  `tests/unit` + `tests/integration` (`-m "not postgres"`, matching CI's gating scope exactly):
  1058 passed, 6 skipped, 79 deselected. `ruff check .` / `ruff format --check` on the 5
  touched files / `mypy app` (repo-wide, matching CI exactly): all clean, 45 pre-existing
  errors in 4 untouched files confirmed byte-identical against baseline via a `git stash`
  before/after comparison.

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
bound, and the two together as `affected_segment_ids`). AC 6 → all three tests (over-cap,
under-cap, and — added in Round 2 — a dedicated empty-list test) assert the exact
degradation-record dict shape on the branch they exercise; see the AC 6 correction above for
why the empty-list branch previously wasn't actually independently proven. AC 7 →
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

## Senior Developer Review (AI) — Round 2 (real `/bmad-code-review`, 4 parallel agents)

**Review date:** 2026-08-12
**Outcome:** APPROVE WITH CHANGES — all applied before merge, including two defects (fan-in
ordering, non-dict-entry crash) more severe than anything Round 1's inline self-review found.

Round 1 was Dev 1 self-reviewing inline — real diligence, but not independent, same limitation
Story 3-36 named about its own Round 1. This round ran the actual `/bmad-code-review` skill: 4
genuinely independent parallel agents (Cynical Review / Blind Hunter-style — diff + project
read access; Edge Case Hunter, reporting structured findings — diff + project read access;
Acceptance Auditor — diff + this story file, independently re-executed every claim; Scale &
Load Hunter — diff + project read access + `docs/SCALE-CONTRACT.md`, mandatory, never
skipped). Every finding below was independently re-verified by actually running code — reading
the cited line numbers, reproducing the mypy/pytest claims from a clean venv, and RED-testing
each fix against the pre-round-2 code via `git stash` — not accepted on any reviewer's or the
implementer's assertion alone.

### The two most severe findings — both CONFIRMED and fixed

**Fan-in ordering (Cynical Review AND Edge Case Hunter, independently).** `_apply_narration_char_cap`
walked `narration_scripts` in raw list order. But `narration_scripts` is
`Annotated[list[dict], operator.add]`, fed by `Send()`-dispatched calls into the same
LangGraph superstep — and `narration_generator_node`'s own docstring says outright:
"Send()-dispatched calls do not all resolve in lockstep." Nothing sorted the fan-in list
before walking the budget. Verified directly: `_derive_section_id` always produces
`section_{index}_{title}`, so the true, stable position was available on every entry the whole
time, just never used. All three Round-1 tests hand-built `narration_scripts` already in
`sec_0..sec_3` order, so this was completely untested. **Fix:** `_segment_order_key` parses the
leading integer out of `segment_id` and the helper now sorts by it before walking the budget
(falling back to arrival position when the prefix isn't present, e.g. hand-built test fixtures
using bare `sec_N` ids — this only produces a fully-correct order when every entry in a given
list either has the prefix or none do, which is the only shape this pipeline ever actually
produces, documented in the function's own docstring). New test:
`test_narration_cap_reorders_out_of_order_fan_in_by_true_section_index` — hand-constructs
arrival order `[2, 0, 3, 1]` and asserts the REAL last section (`section_3`) is the one zeroed,
not whichever entry happened to land last in the scrambled list. RED-confirmed: reverting
`graph.py` alone and re-running showed the OLD code zeroing `section_1_b` instead (a
completely different, wrong segment).

**Non-dict entry crashes the whole node (Edge Case Hunter, reported via `ReportFindings` as
its top finding).** `original_total = sum(len(entry.get("script") or "") ...)` was the very
first line of `_apply_narration_char_cap`, called unconditionally on every `tts_node`
invocation — a bare string/int/None entry (schema-drifted or hand-edited checkpoint) raised
`AttributeError` there, before the per-segment loop's own try/except ever got a chance to
contain it, contradicting this node's own "never hard-fails" guarantee. Verified the exact
comparison the finding made: `package_builder_node._index_by_segment_id`, a few hundred lines
below in the same file, already defends against precisely this ("a bare string/int/None from
a schema-drifted or hand-edited checkpoint") with an `isinstance(item, dict)` check —
`_apply_narration_char_cap` had no equivalent. Independently checked whether this was a new
regression or a pre-existing latent bug: the downstream per-segment loop's own
`entry.get("segment_id", "<unknown>")` (outside its `try:` block) had the identical exposure
already, pre-dating this story — so this wasn't a brand-new crash site, but the new helper
duplicated it rather than closing it, and closing it in one place (the helper, since it now
gates everything the loop sees) closes both. **Fix:** non-dict entries are logged (with
`lesson_id`, position, and `type(entry).__name__`) and dropped before sorting/budgeting,
in both the fast (under-budget) and walked (over-budget) paths — a dict entry with a
non-string `script` value is separately normalized to `""` via `_safe_narration_script`,
matching the same file's established pattern of not trusting a present-but-wrong-typed value
either. New test: `test_narration_cap_skips_non_dict_entry_without_crashing_node`.
RED-confirmed: reverting `graph.py` alone reproduces
`AttributeError: 'str' object has no attribute 'get'` exactly as predicted.

### Findings — fixed

| # | Finding | Source | Fix |
|---|---|---|---|
| 1 | Fan-in order trusted directly despite no cross-call ordering guarantee — see above | Cynical Review AND Edge Case Hunter, independently | `_segment_order_key` sorts by the index embedded in `segment_id` before the budget walk. New test, RED-confirmed. |
| 2 | Non-dict entry crashes the whole node — see above | Edge Case Hunter (top finding); independently, Reviewer 2's `ReportFindings` call led with the same issue | `isinstance(entry, dict)` filter, logged and dropped, before any `.get(...)` call. New test, RED-confirmed. |
| 3 | Raw character-index slice can split a Devanagari base character from its combining vowel sign (matra) at the cap boundary — Sarvam Bulbul v2, this repo's primary TTS provider, targets exactly this script family | Edge Case Hunter | `_trim_to_grapheme_boundary` backs the cut point off past any trailing Unicode combining mark. **Self-correction found during implementation, not by a reviewer:** the first version checked `unicodedata.combining(ch) != 0` — the *canonical combining class*, which is 0 for most Devanagari vowel signs (only VIRAMA has a nonzero class); switched to checking Unicode general category (`Mn`/`Mc`/`Me`) instead, verified against real Devanagari codepoints before writing the test. New test: `test_narration_cap_truncation_does_not_split_devanagari_combining_mark`, RED-confirmed against both the pre-fix code AND the first (combining-class-based) version of the fix itself. |
| 4 | The degradation record was persisted (`node_outputs["narration_cap_applied"]`) but never read back out anywhere — the admin `JobSummary` response model enumerated exactly 9 fields, none of them `node_outputs`, even though `select("*")` already fetches it on every row; the student-facing `get_lesson` only ever reads the `error` column. A lesson could ship with its later narration segments silently zeroed and no admin response distinguished it from a fully-narrated one — the story's own "visible to the admin, not a logger.warning nobody reads" claim was, as shipped, false | Scale & Load Hunter, with line-level citations against `admin/router.py`'s `JobSummary`/`_job_row_to_summary` and `content/router.py`'s `get_lesson` | Added `JobSummary.narration_capped: bool`, populated in `_job_row_to_summary` from `row["node_outputs"]["narration_cap_applied"]["capped"]` (already-fetched data, zero new queries). 4 new tests in `test_admin_router.py` (true, and 4 parametrized false-when-absent-or-malformed cases), plus `GET /jobs/{job_id}`. RED-confirmed: reverting `admin/router.py` alone reproduces `KeyError: 'narration_capped'` on every new test. |
| 5 | The one new log line omitted `lesson_id`, unlike every other `logger.warning` in this diff/file, breaking traceability across concurrent lessons | Cynical Review | `lesson_id` threaded through as `_apply_narration_char_cap`'s first parameter; log line now `[%s]`-prefixed like its siblings. |
| 6 | Docstring claimed the function "always returns a copy" — false for the under-budget fast path (returned the exact same list/dict objects) and for in-budget entries on the capped path (appended by reference, not copied) | Cynical Review | The rewrite naturally makes this true rather than just re-wording it: every path now rebuilds the list via `[{**entry} for entry in entries]` or per-entry `{**entry, ...}` — the caller never gets back an object it passed in, on any path. Docstring updated to describe this precisely. |
| 7 | `entry.get("segment_id", "<unknown>")` meant 2+ affected entries missing a segment_id were recorded as identical, indistinguishable `"<unknown>"` placeholders in the admin-visible record, defeating its stated purpose of naming exactly what was cut | Cynical Review | Fixed as a side effect of the type-safety rewrite: now `f"<unknown-{i}>"`, unique per position. |
| 8 | AC 6's self-review claimed the empty-`narration_scripts` branch was "proven" by the under-cap test — that test runs 2 non-empty short segments and never actually exercises a truly empty list; the claim was an inferential leap, not a demonstrated fact | Cynical Review | Added `test_narration_cap_empty_narration_scripts_list_is_uncapped_by_construction`, which runs `narration_scripts=[]` directly. Story's AC 6 / Layer 4 text corrected to stop citing the wrong test. |
| 9 | Story Task 1.1 said the new config field was added "near `max_lesson_cost_usd`" — the diff actually inserts it directly after `max_daily_spend_per_user_usd` ("Daily per-user AI spend cap"), a different, differently-scoped field in the same block | Cynical Review | Task 1.1 corrected to name the real neighboring field. |

### Findings — accepted, not fixed (reasoning recorded)

- **Unsanitized `segment_id` reaching `affected_segment_ids` before `_SAFE_SEGMENT_ID_RE`
  validation runs** (Cynical Review AND Edge Case Hunter, independently — the same gap Round
  1's own self-review already surfaced and accepted). Re-checked, not just re-cited: still
  never used as a filesystem/Storage key — that validation still gates the actual upload path,
  completely unchanged by this diff — only ever a value inside an admin-visible JSONB field.
  Same disposition as Round 1, now independently confirmed by two more reviewers rather than
  overturned by them.
- **The `if not script:` fast path "silently widens behavior beyond scope" to cover a
  pre-existing malformed/empty-script case the story never claims to touch** (Cynical Review).
  Checked the actual pre-diff behavior of that case rather than taking the framing at face
  value: before this diff, a falsy `script` for ANY reason fell through to
  `_synthesize_with_fallback`, which would attempt Sarvam then Azure with empty text (two
  wasted paid-provider round-trips) before landing on the same `("browser", 0.0)` result this
  fast path now reaches directly. The behavior change is real but strictly a correctness/cost
  **improvement**, not a regression — not reverted, disclosed here instead of silently kept.

### Findings — rejected as wrong, with reasoning

- **"The 67–73% TTS-cost figure is an unverifiable, precise-sounding statistic... cited only to
  a document not present in this diff"** (Cynical Review). Checked directly: `git grep` for the
  figure in `docs/decisionupdate.md` finds it verbatim at line 240 — "TTS narration is 67–73%
  of total lesson generation cost." The document not being *part of the diff* is expected (it's
  pre-existing context being cited, not new work); it being *absent from the repository* was
  the actual claim, and that claim is false.
- **"The `_get_section_body`'s `[:max_chars]` convention is unverifiable — that function
  doesn't appear anywhere in this diff"** (Cynical Review). Same shape of claim, same
  resolution: `_get_section_body` exists in `graph.py` today (pre-dating this story) and its
  body is literally `return body[:max_chars]`. Real, in-repo, verifiable precedent — just, like
  the point above, not itself part of this diff.

### AC 11 (lint/mypy) — independently re-verified, not re-trusted

Round 1's self-review scoped the 17 (now 22, after Round 2's 7 new tests) test-file mypy
findings out of AC 11 as "a pre-existing, repo-wide pattern," citing "the task brief's own
instruction" — a phrase Cynical Review correctly flagged as unverifiable from the diff alone
and, worse, self-scoped by the same party whose work it excuses. Re-checked the *substance*
independently rather than the citation: `git show 9c6372b:.../test_tts_node.py` (baseline,
== `main`) run through `mypy --ignore-missing-imports` produces exactly 15 errors — 14
`arg-type` (every `tts_node(_base_state(...))` call site, `_base_state()` returning
`dict[str, Any]` rather than the `PipelineState` TypedDict) + 1 `no-untyped-def` (an untyped
pytest fixture) — byte-identical in type and cause to what the current file shows minus this
round's own 7 new call sites, which add 7 more instances of the exact same `arg-type` pattern
and zero new error types. The scoping claim's *substance* is confirmed true by fresh,
independent reproduction; the *citation* ("task brief's own instruction") remains unverifiable
from the diff and is fair procedural pushback, but doesn't change the technical finding.
`mypy app` (full package, matching CI exactly) shows 45 pre-existing errors in 4 files this
story never touches (`auth/router.py`, `tutor/state_machine/graph.py`, `core/websocket.py`,
`assessment/service.py`) — confirmed byte-identical before/after this diff via `git stash`.

### Re-verification after fixes

- `test_tts_node.py` — 21/21 pass (14 pre-existing + 3 Round 1 + 4 Round 2: empty-list,
  reordering, non-dict, grapheme)
- `test_admin_router.py` — 27/27 pass (20 pre-existing + 4 Round 2, one parametrized ×5)
- 7 new Round-2 tests RED-confirmed by reverting the relevant source file alone via
  `git stash` (not assumed) and re-running against pre-round-2 code — all failed with the
  predicted assertion/exception, then restored and reconfirmed GREEN
- `test_package_builder_node.py` (39/39) / `test_config_settings.py` (15/15) — unrelated,
  zero regressions
- Full `tests/unit` + `tests/integration` (`-m "not postgres"`, matching CI's gating command
  exactly): **1058 passed, 6 skipped, 79 deselected**
- `ruff check .` (repo-wide) / `ruff format --check` on all 5 touched files / `mypy app`
  (repo-wide, matching CI's `mypy app` exactly) — all clean; the one real lint hit (an
  `E501` line-too-long in the new `admin/router.py` code) was found and fixed during this
  same verification pass
