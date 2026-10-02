# Story: Slide bullets should be complete one-two-line sentences, not short fragments

**Requested:** 2026-09-29, product feedback relayed from the manager: bullet points in the slide
panel read as 4-5-word fragments; they should be complete, well-formed sentences of roughly one to
two lines each.

**Clarified with the user before implementation:** this refers to `slide_generator_node`'s LLM-
generated slide bullets (the sidebar list shown next to a slide's image, or the full-width text
panel on an image-less slide) — not `CaptionOverlay`'s narration captions (the bottom ~30%-height
bar), which already split by real sentence boundaries server-side (`_split_into_caption_lines`,
Story 4-29/BR-6) and are out of scope here.

## Root cause

`slide_generator_node`'s system prompt (`apps/api/app/modules/content/pipeline/graph.py`)
currently instructs the LLM:

> "Each bullet must be a single concise point — no more than 200 characters — not a full sentence
> or paragraph; split a longer idea into multiple bullets instead."

This explicitly tells the model NOT to write a full sentence — the exact opposite of what's wanted.
`_MAX_SLIDE_BULLET_CHARS = 200` (D125) is a MAXIMUM safety ceiling only (with a truncation guard
for anything still over it after generation) — there is no minimum guidance at all, so a model
following "concise point, not a sentence" naturally produces short label-like fragments well under
even a one-line budget.

## Fix

Reword the prompt instruction to require one complete, well-formed sentence per bullet, targeting
roughly one to two lines (a concrete character-count anchor: ~60-160 characters) — while keeping
the existing `_MAX_SLIDE_BULLET_CHARS = 200` hard ceiling and its post-generation truncation guard
unchanged (D125's "wall of text" / multi-sentence-paragraph protection still applies; this story
only changes what counts as "concise," not the outer safety bound).

No other node, constant, or eval-harness threshold changes:
- `tests/evals/scoring.py`'s `_MAX_BULLET_CHARS = 200` (the D125-synced "wall of text" ceiling)
  is unchanged — still a maximum-length check only, unaffected by a prompt-wording change that
  doesn't touch the ceiling.
- The post-generation truncation guard (slice to `_MAX_SLIDE_BULLET_CHARS - 1` + ellipsis) is
  unchanged — still the backstop if the LLM doesn't comply.
- No new minimum-length enforcement is added in code — matching this codebase's existing pattern
  of prompt guidance + hard-ceiling-only enforcement (D125's own precedent), not a hard floor that
  would force awkward padding of a legitimately short, complete sentence.

## Acceptance Criteria

1. **AC1**: `slide_generator_node`'s system prompt no longer contains the instruction "not a full
   sentence or paragraph" (or equivalent language discouraging complete sentences).
2. **AC2**: the prompt explicitly instructs the LLM to write one complete, well-formed sentence per
   bullet, with a concrete one-to-two-line-length target stated in the prompt text.
3. **AC3**: `_MAX_SLIDE_BULLET_CHARS` (200) and the post-generation truncation guard are unchanged
   — this story does not touch the outer safety ceiling, only the prompt's target/guidance.
4. **AC4**: `tests/unit/test_slide_generator_node.py::test_slide_prompt_states_the_bullet_length_limit`
   continues to pass unmodified — the numeric limit is still stated in the prompt.
5. **AC5**: a new test asserts the prompt text no longer discourages full sentences and does
   instruct a complete-sentence, one-to-two-line target.
6. **AC6** (added 2026-09-29, review round): `slide_generator_node` persists an admin-visible
   record of every bullet the D125 200-char guard had to truncate (`slide_bullet_truncations`,
   surfaced via `package_builder_node` into `lesson_jobs.node_outputs`) — the existing truncation
   guard itself and `_MAX_SLIDE_BULLET_CHARS` are unchanged (AC3 still holds); only its visibility
   changes, from a `logger.warning` nobody reads to a persisted, queryable record.

## Scale & Load

**Revised 2026-09-29** after an independent PR reviewer (AkshayDev2905) correctly flagged the
original "N/A ... marginally more output tokens" framing below as unsubstantiated. The six
questions, answered with real numbers instead of an assumption:

1. **Unit of work and its range**: one `slide_generator_node` call produces an entire chapter's
   deck in a single structured-output request — 1 call regardless of chapter size, unchanged by
   this story. Range: as few as 1 segment up to `max_narration_segments` = 24 (the platform's own
   hard cap, D195/D196), each up to `_MAX_SLIDES_PER_SEGMENT` = 8 slides — worst case 192 slides
   in one response.
2. **Fixed budget vs. variable input**: `complete_structured` is called with no `max_tokens`, so
   completion length is bounded only by the model's own output cap — this was already true before
   this story. What changed: bullets now target 60-160 chars (~15-40 tokens) instead of the old
   ~30-char (~8-10-token) fragments, roughly a 3-4x per-bullet growth. At the 192-slide worst case
   and an estimated 3-5 bullets/slide (no hard per-slide bullet count exists), that is on the order
   of 10,000-40,000 completion tokens for bullets alone — a range that can plausibly reach a
   model's completion-token ceiling on the platform's largest targeted chapters. **Registered as
   D214** (`docs/DEFECT-REGISTER.md`) rather than fixed here: batching segments across multiple
   calls, or adding an explicit `max_tokens` + degradation strategy, is a structural change to
   `slide_generator_node`'s single-call design, out of scope for a prompt-wording story (binding
   rule 6). What happens today if the cap is hit: OpenAI's structured-output `parse()` helper
   raises (`LengthFinishReasonError`), which propagates through `_complete_structured_inner`
   (retried 3x by `@with_retry`) and fails the pipeline job loudly — visible in `lesson_jobs`
   status and Sentry. This satisfies CLAUDE.md's "explicit error, not silent" requirement, but is a
   new availability risk on large chapters, honestly recorded rather than hidden behind "N/A."
3. **Scope of the limit**: `max_narration_segments` is a per-lesson (per-generation-attempt) cap,
   set globally via `settings.max_narration_segments` — same scope as before this story, unaffected
   by it.
4. **Unbounded reads/writes**: none introduced. Same single LLM call, same `slide_generator_node`
   Supabase write it already made.
5. **Inherited caps re-derived**: `_MAX_SLIDE_BULLET_CHARS` = 200 (D125) was re-checked, not
   re-derived — it remains a maximum-only ceiling and is unchanged by this story (AC3). The
   *frequency* at which real generations approach it is now higher, which is exactly what D214
   records.
6. **Check-then-act under concurrency**: N/A — a single sequential LLM call per lesson generation,
   no new concurrent access pattern.

Separately, the existing per-bullet 200-char truncation guard (D125) was previously only a
`logger.warning` — a silent-truncation gap CLAUDE.md explicitly forbids, sharpened by this same
reviewer's finding #2 and now actually fixed (not merely registered): `slide_generator_node` now
returns a `slide_bullet_truncations` list (`{segment_id, slide_title, original_chars}` per
truncated bullet), persisted by `package_builder_node` into `lesson_jobs.node_outputs` for admin
visibility, mirroring `section_truncations`' existing pattern (Story 3-39). The one remaining gap —
this new field is not restored on `slide_generator_node`'s own ARQ-retry cache-hit path — is the
same gap class already registered as D191 for a sibling node; registered here as **D215** rather
than fixed opportunistically in this story.

Original (superseded) reasoning, kept for the record: "a pure prompt-wording change ... marginally
more output tokens within the existing budget." The reviewer's arithmetic above shows this
significantly understated the change; superseded, not deleted, per this repo's own practice of
recording a wrong initial read rather than silently overwriting it (see D192 for the precedent).

## Completion notes

Implemented exactly as designed. Reworded `slide_generator_node`'s system prompt in
`apps/api/app/modules/content/pipeline/graph.py` to require one complete, well-formed sentence per
bullet (roughly one-two lines, ~60-160 characters), removing the "not a full sentence or paragraph"
instruction entirely. `_MAX_SLIDE_BULLET_CHARS = 200` and its post-generation truncation guard are
untouched — added a comment there clarifying it remains a maximum-only ceiling (D125).

Added `test_slide_prompt_requires_complete_sentences_not_fragments` next to the existing
`test_slide_prompt_states_the_bullet_length_limit` in `test_slide_generator_node.py`, asserting the
old discouraging language is gone and the new complete-sentence/one-to-two-line instruction is
present. The existing test (AC4) needed no changes — it only asserts the numeric ceiling appears in
the prompt, which is unchanged.

Verified: `test_slide_generator_node.py` 33/33, adjacent regression suite (`test_phase1_economy_nodes.py`,
`test_package_builder_node.py`, `test_lesson_planner_node.py`, `test_node_return_shape.py`,
`test_unbounded_queries.py`) 165/165, `ruff check`/`ruff format --check`/`mypy` all clean. Full
backend suite: 52 pre-existing failures, confirmed unrelated (teachback-endpoint tests lost their
fix along with the just-reverted PR #267; the rest are the same recurring environment-dependent
failures — missing local Redis/tesseract, no OpenAI API key — seen throughout this session, none
touching `slide_generator_node` or this diff).

## Out of scope

- `CaptionOverlay`'s narration captions (bottom bar) — already sentence-based server-side, not
  touched.
- Frontend `SlideRenderer.tsx` rendering/layout (the existing `isDense`/`_DENSE_CONTENT_CHAR_THRESHOLD`
  degradation already handles longer per-slide text content gracefully in the narrow sidebar view;
  no frontend change needed for this story).
- Any new hard minimum-length enforcement in code — prompt guidance only, matching D125's existing
  max-only enforcement pattern.
