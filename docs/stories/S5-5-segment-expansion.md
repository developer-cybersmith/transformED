# Story S5-5 — Segment Expansion (make the narration minimum reachable)

**Sprint:** 5
**Story:** S5-5
**Author:** Dev 4
**Status:** Ready for implementation
**Branch:** `sprint5/s5-5-segment-expansion` (branched from S5-4, see Dependency)
**Date:** 2026-09-25

---

## Background

Story S5-4 makes the tier a real, measured, honestly-reported **minimum narration
duration** (T1 ≥ 45 min, T2 ≥ 30, T3 ≥ 15). It does not make that minimum
*reachable*, and on current `main` it is structurally impossible for every tier.

`topic_selection_node` (Story 233, merged 2026-09-25) collapses a chapter into
exactly **1 topic (T3) or 2 topics (T1/T2)** and overwrites `state["sections"]`.
Every Phase-1 call then reads at most `section_body_max_chars = 6,000` characters
of each. So the text the generator can ever see is `n_topics × 6,000`:

| Tier | Topics | Visible chars | Max narration | Minimum required | Reachable? |
|---|---|---|---|---|---|
| T1 | 2 | 12,000 | 13.3 min | 45 min | **No** |
| T2 | 2 | 12,000 | 13.3 min | 30 min | **No** |
| T3 | 1 | 6,000 | 6.7 min | 15 min | **No** |

This is independent of chapter size — a 500-page chapter has the identical
ceiling to a 5-page one. Confirmed end-to-end against a real lesson
(`be32c289-d22e-4f11-afc0-44d529adb48c`, T1/45 min): 26,209 chars of chapter,
**9,930 visible (38%)**, 16,279 silently discarded, 10.57 min of audio delivered
against a 45-minute request.

### Why the fix is not in `coalesce_sections`

An earlier plan added a max-body split pass to `coalesce_sections`. That is dead
on arrival post-233: `coalesce_sections` runs in `structure_node`, and
`topic_selection` merges its output back into 1-2 topics immediately afterwards.
The split would pass its own unit tests and change nothing in production.
Recorded here because the wrong fix is plausible enough that the next person
will propose it again.

### The actual insight

`merge_section_range` is **text-preserving** — after `topic_selection`, every
character of the chapter is still in `state["sections"]`, just concentrated in
1-2 large bodies. Nothing is lost at that stage. **The loss is entirely at the
6,000-char read**, and the window is the right size for one call:

> 900 narration words × 6 chars/word = **5,400 chars** — comfortably inside the
> existing 6,000-char window.

The bug is not that the window is too small. It is that we read it **once per
topic** instead of **once per delivery unit**.

---

## User Story

> As a student who selected 45 minutes, I want the lesson to actually teach me
> for at least 45 minutes when the chapter has enough material — and to be told
> plainly when it does not, instead of being handed 10 minutes and a success
> message.

---

## Approach

Insert one node after `topic_selection`, before the Phase-1 fan-out:

```
extract → structure → chunk → embed → topic_selection → [segment_expansion] → Phase-1 → planner → narration → tts
```

`segment_expansion_node` slices each topic's body into duration-sized units and
overwrites `state["sections"]`, exactly as `topic_selection` already does — so
**every downstream node needs zero changes**; they see a longer list. Each slice
carries `topic_index`/`topic_title`, so the topic grouping Story 233 introduced
is preserved, not undone: topic_selection still decides *what* is taught, this
node decides *how many units* are needed to teach it for the requested time.

**Answering the design question directly:** we generate additional segments from
the same topic range. `topic_selection` is not changed and does not need to
expose more source material — it already carries all of it.

---

## Acceptance Criteria

### A. The minimum is delivered when the source allows

**AC1.** A **15-minute** selection produces ≥ 15 min of narration when the
chapter's source text can support it.

**AC2.** A **30-minute** selection produces ≥ 30 min of narration when the
chapter's source text can support it.

**AC3.** A **45-minute** selection produces ≥ 45 min of narration when the
chapter's source text can support it.

**AC4.** "Can support it" is computed from the chapter's **full** post-topic-
selection text at 1 narration word per source word, using the **configured
primary TTS tier's** effective words-per-minute (60db at `sixtydb_speed` when
credentials are set, else Sarvam at `sarvam_narration_pace`) — the same rate the
delivered audio is measured against, so the plan and the measurement cannot
disagree about the assumption.

### B. Insufficient source is reported, never padded

**AC5.** When the source cannot support the requested minimum, the lesson is
generated to the **achievable** duration and **no content is fabricated or
padded** to hit the clock. The anti-fabrication guardrails are unchanged.

**AC6.** Such a lesson is marked `content_limited` and `duration_report` carries
**`requested_min_minutes`** and **`achievable_minutes`** alongside the existing
measured figures.

**AC7.** That limitation is **surfaced to the student**, not only to the admin
record — a 45-minute request answered with 29 minutes must say so. (S5-4 records
it in `lesson_jobs.node_outputs`; this AC is the user-facing half.)

### C. Slicing is lossless and window-safe

**AC8.** **100% of each topic's text is preserved.** Concatenating a topic's
slice bodies in order reproduces the original topic body **exactly** — asserted
by test, on real multi-paragraph text, not a synthetic string.

**AC9.** Slices are cut at **paragraph boundaries** wherever possible. A single
paragraph longer than the window falls back to a sentence/whitespace boundary,
and only then to a hard cut — each fallback recorded, never silent.

**AC10.** **Every slice body is within `section_body_max_chars`** (6,000). The
global window is **not** raised (product constraint) and no per-node exception is
introduced — slices are sized so the existing window is sufficient.

**AC11.** Slice count per topic is allocated in proportion to that topic's body
length, with **at least one slice per topic**, so a short topic is never erased.

### D. Downstream continues to work

**AC12.** Existing downstream nodes operate unchanged through the expanded
`sections` list: Phase-1 fan-out, `_derive_section_id`, `lesson_planner`, the
S5-4 quiz allocator, narration fan-out, `tts_node`, `package_builder`. No node
signature changes.

**AC13.** `_derive_section_id` yields **unique, storage-safe ids** for slices of
the same topic (they share a title) — a collision would overwrite one slice's
audio with another's in Storage.

**AC14.** The S5-4 **quiz budget stays lesson-level**: expanding 2 topics into 8
slices must not multiply quiz volume by 4. Totals stay 16/10/5.

**AC15.** Slice count is **bounded** — by available content, by
`_MAX_PHASE1_SECTIONS`, and by an explicit per-lesson cap — so a large chapter
cannot fan out unboundedly. See Scale & Load Q1/Q2.

### E. Tests

**AC16.** Concatenation test: for real multi-paragraph input, `"".join(slice
bodies) == original topic body`, byte for byte.

**AC17.** Duration-planning tests for **15 / 30 / 45**, each asserting the
planned slice count × per-slice word target meets or exceeds the tier minimum
when content allows.

**AC18.** Content-limited test using the **real diagnosed chapter**: 26,209 chars
→ ~4,368 source words → **~29.1 min at 150 wpm**. A T1/45-min request must be
reported as `content_limited` at ≈29 min — never as a satisfied 45.

**AC19.** Window test: no slice exceeds 6,000 chars, across topic sizes from one
paragraph to 500,000 chars.

**AC20.** Interaction tests: with the 200-char min-body merge, and with the
15-section cap (both still upstream in `structure_node`).

**AC21.** Guard tests pass, or are updated in the same commit with a stated
reason: `test_fan_out_state_keys.py`, `test_quiz_generator_tier.py`,
`test_lesson_planner_node.py`, `test_topic_selection*.py`, `test_coalesce_sections.py`,
`test_structure_node.py`, `test_node_return_shape.py`, `test_unbounded_queries.py`,
`test_s5_4_duration_budget.py`, `test_s5_4_duration_wiring.py`.

---

## ⚠ PRODUCT DECISION REQUIRED — T1 at 45 minutes exceeds the cost ceiling

**Not an engineering assumption, and deliberately not solved in code.** Slide
count is derived from narration duration, and `image_generator_node` produces one
image per slide at ~$0.067 (Nano Banana):

| Tier | Narration | Slides | Image cost | TTS | vs $3.00 ceiling |
|---|---|---|---|---|---|
| **T1** | 45 min | 38–56 | **$2.51–3.77** | $0.81 | **OVER, on images alone** |
| T2 | 30 min | 17–25 | $1.12–1.68 | $0.54 | ok |
| T3 | 15 min | 5–8 | $0.34–0.50 | $0.27 | ok |

LLM spend for ~8 narration and ~8 slide calls sits on top of this. A real
45-minute lesson **cannot be produced within the current $3.00/lesson ceiling.**

What happens today if nothing is decided: `check_ceiling` in
`image_generator_node` degrades the lesson to text-only mid-generation — a
surfaced degradation, not silent, but a poor experience chosen by accident
rather than by anyone.

**Options (product/CEO call, not the implementer's):**
1. Raise the ceiling for T1 to ~$4.50.
2. Decouple slide count from duration — cap slides per lesson (e.g. 20) so a
   45-minute lesson has longer narration per slide rather than more slides.
3. Stop generating one image per slide (e.g. images only for key slides).
4. Accept text-only degradation for T1 and say so in the UI.

Registered as **D188**. **This story ships the duration fix and does not touch
slide or image volume** — so merging it makes the cost conflict *reachable*,
which is exactly why the decision is needed before T1 is offered to real
students.

---

## Scale & Load

**Q1 — What is ONE unit of work, and what is its range?**
One unit = one chapter lesson generation at one tier. The unit this story
changes is the **narration slice**. Before: 1-2 slices (= topics). After:
`ceil(required_words / words_per_slice)`, bounded three ways — by available
content, by `_MAX_PHASE1_SECTIONS = 60`, and by a new explicit
`max_narration_segments` cap. At the default 900 words/slice: T3 = 3, T2 = 5,
T1 = 8 slices for a chapter with sufficient text; 1 slice minimum for a chapter
with almost none. A 500,000-char topic would want 92 slices and is cut to the
cap — an **explicit, recorded** limit, not silent truncation (Q2).

**Q2 — Which budgets are FIXED while the input VARIES, and what happens past them?**
- `section_body_max_chars = 6,000` (fixed) vs topic body (varies): no longer
  truncates content, because slices are sized under it. It now bounds **one
  call**, which is what it was always for.
- `max_narration_segments` (fixed) vs required slices (varies): past it the
  lesson is generated at the capped length and reported `content_limited` with
  the reason distinguishable from "thin chapter" — a surfaced degradation.
- Tier minimum (fixed) vs chapter length (varies): past it, `content_limited`
  with `requested_min_minutes` vs `achievable_minutes` (AC6), surfaced to the
  user (AC7). **Never padded** (AC5).
- **The $3.00 cost ceiling (fixed) vs narration duration (varies): breached at
  T1 — see the product-decision block above.** This is the one budget this story
  cannot honour and does not pretend to.

**Q3 — What is the SCOPE of every limit?**
`words_per_slice`, `max_narration_segments`, `section_body_max_chars` and the
effective-WPM inputs are **per deployment** (env/module constants, identical on
every replica). Slice count is **per lesson**. None are per-user, so none
multiply by replica count.

**Q4 — Which reads and writes are UNBOUNDED?**
None added. `segment_expansion_node` is pure in-memory slicing of state already
loaded, plus **one** `lesson_jobs` checkpoint read and one write — the same
primary-key pattern `topic_selection_node` already uses. Its checkpoint records
per-slice metadata bounded by `max_narration_segments`.
`tests/unit/test_unbounded_queries.py` must stay green with no new exemption.

**Q5 — Which caps were INHERITED, and have they been re-derived?**
- `section_body_max_chars = 6,000`: inherited (Story 3-39's open item),
  **deliberately unchanged** per product constraint. Re-derived in the sense
  that its *role* is now correct — a per-call budget, not an accidental content
  cap. The 900-words/slice default is chosen so it binds on nothing.
- `_MAX_PHASE1_SECTIONS = 60`: inherited, now genuinely reachable for the first
  time (T1 on a long chapter). Re-derived: 60 slices × ~900 words = 54,000 words
  ≈ 360 min of narration — far beyond any tier, so the new
  `max_narration_segments` cap binds first and 60 remains a DoS backstop.
- `_TIER_MINUTES_PER_SLIDE_BAND` (D87): inherited, and its input changes again
  here (narration minutes rise from S5-4's 29.25 to 45 at T1). **This is the
  cost conflict above** — quantified, escalated, not silently absorbed.
- `narration_words_per_minute` + the TTS pace: inherited from S5-4; re-derived
  only in that AC4 pins the plan and the measurement to the same provider rate.

**Q6 — Is every check-then-act sequence safe under CONCURRENT requests?**
No new check-then-act. Slicing is deterministic and pure: the same topic bodies
and tier always produce the same slices, so a concurrent retry recomputes an
identical list. The node's idempotency checkpoint follows `topic_selection`'s
existing single-sequential-node pattern (no atomic RPC needed — it is not
`Send()`-dispatched). Note `topic_selection` already purges stale Phase-1
checkpoints when topic ids change; the same purge must cover slice ids, since a
retry that crosses this deploy will find checkpoints under ids the new slices
reuse.

---

## Worked example — T1, 45 min, the diagnosed Python Guide chapter

```
topic_selection   →  2 topics, 26,209 chars, 100% preserved
                     (today: 12,000 read, 14,209 discarded)

segment_expansion →  required   = 45 min × 150 wpm         = 6,750 words
                     available  = 26,209 ÷ 6               = 4,368 words
                     n_needed   = ceil(6,750 ÷ 900)        = 8
                     n_possible = ceil(4,368 ÷ 900)        = 5
                     → 5 slices, CONTENT-LIMITED
                     allocated across the 2 topics by body length, ≥1 each
                     each ≈ 5,242 chars, cut at paragraph boundaries,
                     slices tile the body exactly

Phase-1           →  5 units × 6,000 window → 26,209 chars visible (100%)
lesson_planner    →  5 segments, duration_min = 900 ÷ 150 = 6.0 min each
narration         →  5 calls, each "aim for about 900 words", each reading
                     its own slice
tts               →  5 MP3s, real durations measured by tinytag
package_builder   →  measured ≈ 29.1 min
                     outcome = content_limited
                     requested_min 45 · achievable 29.1 · surfaced to the user
```

**29.1 min instead of 10.57** — from reading text we already had. The 45-minute
request is honestly reported as unmeetable rather than silently answered with 10.

Same chapter, other tiers: **T3 (15 min) fully satisfied; T2 (30 min) reaches
97%; T1 (45 min) reaches 65%.**

---

## Dependency

Branched from `feature/230-duration-driven-lessons` (S5-4, PR #243, unmerged),
because it builds on the amended minimum-narration constants. Rebase onto `main`
once S5-4 merges. Nothing here re-litigates S5-4's decisions.

## Out of scope

- **The playback discrepancy** — the diagnosed lesson has 10.57 min of audio but
  was experienced as ~6 min, which is almost exactly segment 0 (952 words ≈ 6.3
  min). Tracked separately; it is a player/advance question, not generation.
- Slide and image volume (the cost conflict above — needs the product decision).
- `section_body_max_chars` re-derivation (Story 3-39's open item).
- Story 233's topic-count design.

## Review

6-agent gate. Three of the six layers are not supplied by the `bmad-code-review`
skill and must be requested explicitly. **Cross-team:** this touches Dev 1's
content pipeline and sits directly on Story 233's node — Dev 1 should review.
