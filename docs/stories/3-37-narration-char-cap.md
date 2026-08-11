---
id: "3-37"
title: "Node 8 Narration Hard Cap — 10,000 chars/lesson enforced in tts_node"
status: "ready-for-dev"
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

- [ ] **AC 1.** `Settings.max_narration_chars_per_lesson: int` exists in `config.py`, default
  `10000`, `ge=1`, documented as the Node 8 hard cap from `docs/decisionupdate.md` §8.
- [ ] **AC 2.** When the sum of `len(script)` across all entries in `narration_scripts` (in
  list order) is `<= max_narration_chars_per_lesson`, `tts_node` behaves identically to before
  this change — every script reaches the synthesis loop unmodified.
- [ ] **AC 3.** When the cumulative total would exceed the cap, the segment that crosses the
  boundary is truncated to a character-level slice that exactly fills the remaining budget
  (`script[:remaining_budget]`), and is still sent to the TTS provider (with the truncated
  text).
- [ ] **AC 4.** Every segment after the one in AC 3 is treated as having an empty script —
  no Sarvam/Azure call is made for it, and its output degrades through the SAME
  `audio_provider="browser"`, `audio_url=""`, `timestamps=[]` shape this node already produces
  for a malformed/missing-script entry (no new shape).
- [ ] **AC 5.** The sum of characters actually sent to any TTS provider across the whole node
  run never exceeds `max_narration_chars_per_lesson`.
- [ ] **AC 6.** `node_outputs["narration_cap_applied"]` is written on the SAME `lesson_jobs`
  update that writes `node_outputs["tts_node"]`, on both the empty-`narration_scripts` branch
  and the synthesis-loop branch, with the shape:
  `{"capped": bool, "original_total_chars": int, "capped_total_chars": int,
  "affected_segment_ids": [str, ...]}`. Always present, including when `capped is False` (in
  which case `original_total_chars == capped_total_chars` and `affected_segment_ids == []`).

### Non-functional / regression-guard

- [ ] **AC 7.** RED-confirmed: a test feeding `tts_node` 3 segments of ~4,000 chars each
  (12,000 total, exceeding the 10,000 default) fails against the pre-fix code because nothing
  currently caps the total — every segment reaches `_synthesize_with_fallback` with its full,
  uncapped script.
- [ ] **AC 8.** GREEN after the fix: same scenario, sum of chars actually passed to
  `_synthesize_with_fallback` (or skipped entirely) is `<= max_narration_chars_per_lesson`,
  `node_outputs["narration_cap_applied"]["capped"] is True`, and `affected_segment_ids`
  correctly names the truncated + zeroed segments.
- [ ] **AC 9.** A second test proves the under-cap case is completely unaffected: total chars
  well under 10,000 across all segments → `capped is False`, every script byte-for-byte
  unchanged, no segment skipped.
- [ ] **AC 10.** Full `apps/api/tests/unit/test_tts_node.py` re-run unmodified after the fix,
  zero regressions.
- [ ] **AC 11.** `ruff check`, `ruff format --check`, `mypy --ignore-missing-imports` all clean
  on both modified files.

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
- [ ] 1.1 Add `max_narration_chars_per_lesson` to `Settings` in `config.py`, near
  `max_lesson_cost_usd` (AC 1)

### Task 2 — RED
- [ ] 2.1 Write a test with 3 segments (~4,000 chars each) exceeding the 10,000 default,
  confirm it fails against unfixed `tts_node` (AC 7)
- [ ] 2.2 Paste the actual pytest failure output

### Task 3 — GREEN
- [ ] 3.1 Add `_apply_narration_char_cap` helper in `graph.py`, called at the start of
  `tts_node` (AC 2, 3, 4, 5, 6)
- [ ] 3.2 Add the `not script` fast-path in the synthesis loop so a zeroed segment never calls
  a paid provider (AC 4)
- [ ] 3.3 Add `narration_cap_applied` to both `node_outputs` writes (AC 6)
- [ ] 3.4 Re-run the new tests, confirm GREEN (AC 8, 9)
- [ ] 3.5 Re-run full `test_tts_node.py` unmodified, confirm zero regressions (AC 10)
- [ ] 3.6 `ruff check` / `ruff format --check` / `mypy` clean (AC 11)

### Task 4 — Review
- [ ] 4.1 6-layer adversarial review — round 1 (inline self-review)

### Task 5 — Commit
- [ ] 5.1 Story-first commit (story file alone)
- [ ] 5.2 Implementation commit (code + tests + updated story file)

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

*(filled in during implementation — see final report)*

### Completion Notes

*(filled in after GREEN)*

### File List

- `apps/api/app/config.py` — MODIFIED (new `max_narration_chars_per_lesson` field)
- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (`_apply_narration_char_cap` +
  `tts_node` integration)
- `apps/api/tests/unit/test_tts_node.py` — MODIFIED (2 new tests)
- `docs/stories/3-37-narration-char-cap.md` — this file

### Change Log

- 2026-08-11: Story file created (story-first commit), branch
  `sprint3/s3-37-narration-char-cap`.
