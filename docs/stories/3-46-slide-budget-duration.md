# Story 3-46 — Per-segment slide budget must be proportional to segment duration, not a flat count-based split (D85)

**Branch:** `sprint3/s3-46-slide-budget-duration` (from `main`).
**Owner:** Dev 1.
**Trigger:** Real, observed defect from a real production lesson generation this session —
already root-caused before this story was opened; this story implements the pre-specified fix,
it does not re-derive the diagnosis.

## Process note — order of work

As with prior Dev 1 stories this sprint (3-40/3-42/3-44/3-45), the implementation and its
RED-GREEN test verification were done first, feasibility-checked against the pre-specified fix
design before this story file was written up — this file documents that already-verified work.
Committed alone, before the implementation commit, so the two stay separately reviewable per this
project's binding story-first rule.

## Context

`slide_generator_node` (`apps/api/app/modules/content/pipeline/graph.py`) builds 1-8 slides per
segment, governed by a per-segment `slide_budget` `{min, max}` that `lesson_planner_node`
computes and attaches to each segment before `slide_generator_node` runs. The band is derived
from `_tier_slide_budget_per_segment(tier, ...)`, which divides a FIXED tier-wide total-lesson
slide band (`_TIER_TOTAL_SLIDE_BAND`: T1=(20,25), T2=(12,15), T3=(6,8)) across the segments.

## The real defect (D85)

Before this fix, `_tier_slide_budget_per_segment(tier: str, segment_count: int) -> tuple[int,
int]` divided the tier's total band evenly across `segment_count` via ceiling division, clamped
to the structural per-segment band (`_MIN_SLIDES_PER_SEGMENT=1`, `_MAX_SLIDES_PER_SEGMENT=8`),
and returned a SINGLE `(min, max)` pair shared by every segment in the lesson — segment duration
played no part at all.

At `structure_max_sections=15` (the real, common case for a content-dense chapter, confirmed via
a real live generation this session), this collapsed to `(1,1)` for BOTH T2 (the default tier:
`ceil(12/15)=1, ceil(15/15)=1`) and T3 (`ceil(6/15)=1, ceil(8/15)=1`) — EVERY segment got exactly
one slide (T1 got `(2,2)`). Directly observed in a real generated lesson: 15 real segments with
real measured narration durations ranging 1.23-3.48 minutes, EVERY ONE getting exactly one
slide — a single static image+bullet-list sitting on screen for over 3 minutes for the longest
segments while the SAME budget applied to a 1.23-minute segment. A segment's slide count had zero
relationship to how long its narration actually ran.

Real per-segment duration estimates already exist in the pipeline at the exact point this
function is called: `lesson_planner_node` calls it right after getting `response` (the
lesson_planner LLM's structured output), whose `response.segments` entries each already carry a
real `duration_min: float` (already used two lines later to compute `total_duration_min`) — this
was being thrown away in favor of a flat `len(segment_summaries)` count.

## The fix

`_tier_slide_budget_per_segment`'s signature changed from
`(tier: str, segment_count: int) -> tuple[int, int]` to
`(tier: str, segment_durations_min: list[float]) -> list[tuple[int, int]]` — one `(min, max)`
pair per segment, in the same order as the input list, proportional to each segment's share of
the total estimated lesson duration instead of a flat division by count:

1. Look up `total_min, total_max` from `_TIER_TOTAL_SLIDE_BAND` exactly as before (same fallback
   to T2 for unknown tiers).
2. `n = len(segment_durations_min)`; `n <= 0` returns `[]`.
3. `total_duration = sum(segment_durations_min)`.
4. If `total_duration <= 0` (no real duration signal — malformed/all-zero input): fall back to
   the OLD flat ceiling-division formula, using `n` in place of the old `segment_count`, returned
   as `n` identical tuples — never divides by zero, never fabricates a distribution with no basis.
5. Otherwise, for each segment's `dur`: `share = dur / total_duration`; `seg_min =
   clamp(round(share * total_min), 1, 8)`; `seg_max = clamp(round(share * total_max), seg_min,
   8)`.

The one call site in `lesson_planner_node` now builds `segment_durations` from the same
`llm_segment_by_id` lookup dict already used for title/summary two lines above (guaranteeing the
same authoritative `segment_summaries` order — see
`test_segment_order_follows_input_not_llm_response_order`), and indexes into the returned list
per segment instead of reusing one shared pair.

## Verified-reality finding — the fix does not resolve D85 for T2/T3 at the exact evidence scale

Implementing the exact specified algorithm and running it against the exact real 15-segment
dataset that motivated D85 (durations 1.23-3.48 min, see `_D85_REAL_DURATIONS_MIN` in the test
file) surfaces a mathematical ceiling the design did not anticipate: **for T2 specifically, at
exactly 15 segments, every segment still comes out `(1,1)` — identical to the pre-fix bug's own
output.**

T2's `total_max=15` equals the segment count (15), so the average max-budget-per-segment is
exactly 1.0. A segment needs **> 10% of total duration share** to round up to a second slide
(`round(share * 15) >= 2` requires `share >= 1.5/15 = 0.10`). This dataset's largest share (index
8, 3.48 min of a 40.40 min total) is 8.6% — under the threshold. T3 (band 6-8) is equally
saturated at 15 segments for the same reason. Only T1 (band 20-25, more headroom) differentiates
this same dataset.

This is not an implementation bug — it was confirmed by direct execution of the shipped function,
not hand math, and the mechanism itself is verified correct (it differentiates by duration
whenever there is proportional headroom; see `test_slide_budget_proportional_to_real_d85_durations`'s
T1 assertion). It is a **tier-band-vs-segment-count sizing question**: T2's and T3's total-lesson
slide bands were sized without regard to how many segments a real content-dense chapter produces,
and at 15 segments those bands are too tight relative to segment count for ANY per-segment
rounding scheme to differentiate — the total budget itself is smaller than (T3) or equal to (T2)
the segment count.

**This is being surfaced explicitly, not silently smoothed over**, per this project's binding
rule that a documented limitation needs a decision, not a comment. Recommended follow-up for the
coordinator (not implemented here — out of scope, "implement exactly this design, do not
redesign" was explicit): either (a) widen `_TIER_TOTAL_SLIDE_BAND` for T2/T3 relative to
`structure_max_sections`, or (b) replace independent per-segment `round()` with a
largest-remainder / integer allocation method that can still differentiate when the total budget
is tight. Filed for the coordinator to register as a decision alongside D85's closure.

## What this does NOT do

- Does not change `_TIER_TOTAL_SLIDE_BAND`, `_MIN_SLIDES_PER_SEGMENT`, `_MAX_SLIDES_PER_SEGMENT`,
  or any other tier constant.
- Does not touch `slide_generator_node`'s own validation/truncation logic — it already correctly
  reads whatever `slide_budget` it's given per-segment.
- Does not touch `docs/DEFECT-REGISTER.md` or `docs/dev1-tracker.md` — registered centrally by
  the coordinator after this branch is reviewed.

## Scale & Load

1. **Unit of work & range.** One lesson's segment-duration list — `list[float]`, length equal to
   the lesson's segment count. Range: 1 segment (single-topic chapter) to
   `structure_max_sections=15` (the current hard cap on segments per chapter generation) — the
   real evidence case for this defect. Beyond 15 segments the existing `structure_max_sections`
   cap governs (unchanged by this story); this function itself has no additional ceiling on `n`
   beyond what it's given.
2. **Fixed budgets vs variable input.** The fixed budget is still the tier's `total_min/total_max`
   band from `_TIER_TOTAL_SLIDE_BAND` — unchanged by this story, now allocated proportionally by
   duration instead of flatly by count. The zero-total-duration fallback path never divides by
   zero (explicit `total_duration <= 0` guard) and never fabricates a duration-based distribution
   from no signal — it degrades to the prior, well-defined flat-division behavior instead of
   raising or silently truncating.
3. **Scope of the limit.** Per-lesson — unchanged from before this story.
4. **Unbounded reads/writes.** None introduced. This is a pure function over an in-memory list
   already present in `PipelineState`; no new Supabase reads/writes.
5. **Inherited caps re-derived.** This IS the re-derivation the Scale Contract requires (Q5): the
   OLD count-based flat division was the un-re-derived inherited assumption — it silently assumed
   segment duration was irrelevant to slide count, which was never true and was never checked
   against real segment-duration variance. This story re-derives the allocation against the real
   signal (duration) that was already available and unused. The "Verified-reality finding" section
   above documents that the re-derivation is *partial*: the per-segment allocation logic is now
   duration-aware, but the tier-band constants it allocates from (`_TIER_TOTAL_SLIDE_BAND`) were
   explicitly out of scope for this story and remain un-re-derived against `structure_max_sections`
   — flagged above as a follow-up, not silently left implicit.
6. **Concurrency.** No change — this function is pure (no shared state, no I/O), called once per
   `lesson_planner_node` invocation; unaffected by concurrent pipeline runs for different lessons.

## Verification

- RED-GREEN verified via the Edit tool (implementation stashed, new tests confirmed to fail with
  a `TypeError` on the old two-argument signature and with stale flat-shared-tuple values on the
  old body; implementation restored, tests confirmed green).
- New tests in `apps/api/tests/unit/test_lesson_planner_node.py`:
  - `test_slide_budget_proportional_to_real_d85_durations` — the exact real 15-segment D85
    dataset; asserts 15 entries, every pair within `[1,8]`, and documents + asserts the
    verified-reality T2 finding above, plus a T1 assertion demonstrating the core
    duration-proportional property where it IS reachable for this data.
  - `test_slide_budget_zero_total_duration_falls_back_to_flat_division` — proves the
    zero-total-duration fallback reproduces the exact old flat ceiling-division formula, with no
    `ZeroDivisionError`, across three different tier/segment-count combinations.
  - `test_default_tier_produces_t2_slide_budget_and_no_framing`,
    `test_tier_t1_produces_full_depth_framing_and_wider_budget`,
    `test_tier_t3_produces_refresher_framing_and_narrower_budget`,
    `test_unknown_tier_value_falls_back_to_t2_budget_and_framing` — updated in place: these
    pre-existing tests asserted one shared `(min,max)` pair for all 3 segments; their fixture's
    default per-segment durations (4.0/6.0/5.0 min, unequal) now produce three DIFFERENT
    per-segment pairs under the proportional algorithm, so each assertion was updated to the
    exact new per-segment list, computed by direct execution of the shipped function (not hand
    math) and cross-checked against each other (T1 >= T2 >= T3 per segment).
  - `test_tier_t3_five_segments_never_undercuts_total_min` — rerouted to call
    `_tier_slide_budget_per_segment` directly (not via `lesson_planner_node`, which now rejects
    any non-positive `duration_min` before this logic runs) with all-zero durations, to keep
    exercising the exact ceiling-division guarantee it was written for. Documents explicitly, in
    its own docstring, that the new proportional path (real, non-zero, equal-share durations)
    does NOT preserve this guarantee in general — 5 equal-duration T3 segments each round down to
    a `seg_min` of 1, summing to 5, one below the tier's advertised floor of 6. This is the same
    class of shortfall the 2026-07-17 review fix eliminated for the old code, reintroduced via
    rounding instead of floor division — flagged here and in the "Verified-reality finding"
    section above rather than silently left uncovered.
- Full repo-wide regression: run and diffed against the established baseline in this worktree
  before merge — see final report for the exact before/after counts.
