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

## Scale & Load

N/A — a pure prompt-wording change to an existing LLM call already made once per lesson generation
(unchanged call count, unchanged model, unchanged max-token/char ceiling). No new I/O, no new
budget, no new per-request cost beyond the existing slide-generation call this prompt already
belongs to. Longer bullets (still capped at 200 chars) do not change LLM pricing meaningfully
(same call, marginally more output tokens within the existing budget) and do not introduce any new
unbounded read/write.

## Out of scope

- `CaptionOverlay`'s narration captions (bottom bar) — already sentence-based server-side, not
  touched.
- Frontend `SlideRenderer.tsx` rendering/layout (the existing `isDense`/`_DENSE_CONTENT_CHAR_THRESHOLD`
  degradation already handles longer per-slide text content gracefully in the narrow sidebar view;
  no frontend change needed for this story).
- Any new hard minimum-length enforcement in code — prompt guidance only, matching D125's existing
  max-only enforcement pattern.
