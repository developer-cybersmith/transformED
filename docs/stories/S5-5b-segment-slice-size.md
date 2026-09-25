# Story S5-5b — Segment expansion must dispatch the units it plans (D195)

**Sprint:** 5
**Story:** S5-5b (defect fix to S5-5, merged as `ad3dd38`)
**Author:** Dev 4
**Status:** Ready for implementation
**Branch:** `sprint5/s5-5-fix-slice-size`
**Date:** 2026-09-25
**Register:** D195 (new), D194 (touched)

---

## Background — production evidence

Lesson `d1d6a4e2-2139-4a6b-8e3c-f3e19ee6ba9f` (T1 / 45 min, generated 17:01Z on
`ad3dd38`, 47 minutes after the deploy) shipped **2 segments and 19.3 min of
narration** against a stored `capacity_min` of 38.39.

| Stage | Evidence | Value |
|---|---|---|
| structure → topic_selection | checkpoint bodies | 2 topics: 5,677 + 28,870 = 34,547 chars |
| `plan_segments` | reproduced on `ad3dd38` | **7 units, `[2, 5]`** |
| `segment_expansion_node` | Phase-1 checkpoint keys | **2 units**, no `(part N)` suffix |
| Phase-1 truncation | `section_truncations` | 0 (correct: 28,870 < 45,000) |
| narration targets | `segment_word_variances` | 3,000 and 2,758 words, one call each |
| narration delivered | same | 1,672 and 1,363 words |

**Root cause.** The node calls
`split_body(body, target_chars=5_400, max_chars=settings.section_body_max_chars)`.
`split_body` returns the body **whole** when `len(body) <= max_chars`, and
`section_body_max_chars` is **45,000**: Story 233 (`d38d884`) raised it from
6,000 when `topic_selection` began collapsing chapters into 1-2 large topics.
S5-5 was written against the 6,000 figure ("900 words ≈ 5,400 chars, inside
it"). Every topic under 45,000 chars came back as one unit, which covers
essentially every chapter. **Expansion was inert in production.** The 36 + 13
S5-5 tests passed because they call `split_body` directly with `max_chars=6000`,
and the only node-level test used bodies larger than 45,000.

That is Scale Contract **Q5**, an inherited cap that was never re-derived. It is
also the register's worst class: a node that runs, checkpoints and logs success
while doing nothing.

## Two concepts that were conflated

1. **Phase-1 window**: `settings.section_body_max_chars` = 45,000. The most
   source text one Phase-1 LLM call is shown. **Unchanged by this story.**
2. **Per-unit slice size**: `narration_words_per_segment × CHARS_PER_WORD`
   = 900 × 6.0 = **5,400 chars**. The source that one delivery unit is sized
   for. It must stay below the window.

## Why "pass 5,400 to `split_body`" is not sufficient

`split_body` takes a size and derives a count. The planner has already
decided the count. Measured with realistic paragraph text (~420-char
paragraphs) at `max_chars = 5,400`:

| Chapter | plan | dispatched | source not taught |
|---|---|---|---|
| T1, diagnosed `[5677, 28870]` | 7 | 7 | **3,238 chars**, in a content-limited lesson |
| T1, `[5000, 30000]` | 7 | **6** | 4,368 chars |

The first row reports `achievable_minutes` that the slices cannot carry. The
second row breaks the invariant outright: a topic smaller than one slice
cannot make two pieces.

A per-topic prefix (`units_i × 5,400`, gated on `content_limited`) also fails.
At 127.5 WPM the same chapter is *not* content-limited: the plan claims 45.16
min, but the prefixes cover only 42.72 min of source. The small topic cannot
use its second allocation, and no rule passes that allocation to the large one.

## Approach

1. `unit_slice_chars(words_per_segment, window_chars)` =
   `min(int(words_per_segment × CHARS_PER_WORD), window_chars)`. Derived from
   the existing shared constant and settings, with no new literal.
2. **Coverage.** The lesson carries `min(total_source, n_units × unit_chars)`
   characters: exactly the source the plan counted on. Each topic first gets
   `min(len_i, units_i × unit_chars)`. Coverage a topic cannot use (it is
   shorter than its allocation) goes to topics with text remaining. No topic's
   coverage may exceed `units_i × window`.
3. **Tiling.** Each topic's covered text is cut into **exactly `units_i`**
   contiguous, lossless pieces (`split_into`). Cuts are balanced and snapped
   to a paragraph break, or failing that whitespace, near the ideal position.
   No piece exceeds the window.
4. **Untaught text is recorded, not silent.** `untaught_chars_per_topic` goes
   in the `segment_expansion` checkpoint. This is D194's prefix case, which is
   now visible per lesson.

Diagnosed T1 chapter at 150 WPM: coverage = min(34,547, 37,800) = the whole
chapter. Topic 0 → 2 × ~2,839; topic 1 → 5 × ~5,774. **7 units, 0 untaught.**

## Acceptance Criteria

1. **AC1:** the node derives the slice size via `unit_slice_chars` from
   `settings.narration_words_per_segment` and `CHARS_PER_WORD`. It introduces
   no new numeric literal for it.
2. **AC2:** `section_body_max_chars` stays 45,000. It serves only as the hard
   per-unit ceiling, never as the slice size.
3. **AC3:** for the diagnosed chapter (`[5677, 28870]`, T1, 150 WPM),
   `plan_segments` returns `[2, 5]` and the node dispatches **7** units with
   0 untaught chars.
4. **AC4:** under the **real** `get_settings()` configuration, dispatched units
   == `sum(per_topic_segments)`, both in the returned state and in the
   checkpoint's `segment_count`. This holds for the diagnosed chapter and
   across a parametrised sweep of topic sizes and tiers.
5. **AC5 (the regression):** a topic body smaller than 45,000 but larger than
   `unit_slice_chars` is split into multiple units whenever the planner
   allocates more than one.
6. **AC6:** every usable topic still receives at least one dispatched unit
   (S5-5 Option A invariant).
7. **AC7:** `cap_overrun`, `max_segments_configured` and `capped_by_max_segments`
   behave and are recorded exactly as before.
8. **AC8:** when the plan's `achievable_minutes` is below the requested
   minimum (content-limited), no source text is left untaught.
9. **AC9:** an explicit guard test fails if the Phase-1 window is ever reused as
   the slice size. It asserts `unit_slice_chars(real settings) < window` and
   that a sub-window topic still expands under real settings.
10. **AC10:** `split_into` is lossless (`"".join(...) == covered text`) and
    returns exactly the requested count for any body at least that long.
11. **AC11:** `untaught_chars_per_topic` is recorded in the checkpoint.
12. **AC12:** the diagnostic reports the 45,000 window, the slice size from
    `unit_slice_chars`, the full-tier narration target, and
    `untaught_chars_per_topic`.
13. **AC13:** existing guard tests pass: `test_node_return_shape.py`,
    `test_unbounded_queries.py` and `test_ces.py`. So do the full gating suite
    (`tests/`), repo-wide `ruff`, and `mypy`.

## Scale & Load

1. **Unit of work.** One lesson's topic bodies: 1-2 topics (topic_selection).
   Typical total is 20-60k chars. Largest measured is 34,547 (this chapter).
   Beyond the window: a topic longer than `units_i × 45,000` has its tail
   recorded as untaught. It is neither dropped silently nor sent over the
   window.
2. **Fixed budgets vs. varying input.** The slice size (5,400) and window
   (45,000) are fixed. The unit count varies with the tier and the source.
   Past the budget there is an explicit, recorded degradation
   (`untaught_chars_per_topic`, `content_limited`).
3. **Scope of limits.** All of them are per lesson. `max_narration_segments`
   applies per lesson, and `_MAX_PHASE1_SECTIONS` remains the deployment-wide
   fan-out backstop.
4. **Unbounded reads/writes.** None added. There is still a single
   `lesson_jobs` read by primary key (`.single()`) and one checkpoint write.
5. **Inherited caps.** This story *is* the re-derivation. The 6,000 assumption
   is removed from the code, docstrings and the diagnostic. The slice size is
   now computed from settings, so it cannot drift from the window silently.
6. **Check-then-act.** Unchanged: this is a sequential node with the existing
   checkpoint idempotency. No new concurrent path.

**"What input makes this silently wrong?"** Before this story: any topic under
45,000 chars, which is nearly all of them. After it, a unit-count mismatch
fails AC4's test, and untaught text shows up in the checkpoint.

## Out of scope

Issue #256 (quiz allocator basis), D193 (cost ceiling), playback, and the
browser-TTS fallback seen on one segment of `d1d6a4e2`.
