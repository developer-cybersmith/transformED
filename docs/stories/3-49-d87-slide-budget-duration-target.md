# Story 3-49 — D87: slide budget targets minutes-per-slide, not a fixed lesson-wide total

**Branch:** `sprint3/s3-49-d87-slide-budget-duration-target` (from `main`).
**Owner:** Dev 1.
**Trigger:** the D85 follow-up explicitly deferred at close — this is that follow-up.

## Context

D85 (closed, partial) fixed HOW `_tier_slide_budget_per_segment` allocates a tier's slide
budget — proportional to each segment's estimated duration instead of a flat division by
segment count. It deliberately did NOT fix WHAT total each tier allocates: `_TIER_TOTAL_SLIDE_BAND`
(`T1=(20,25)`, `T2=(12,15)`, `T3=(6,8)`) is still a **fixed total for the whole lesson**,
independent of segment count. At `structure_max_sections=15` (the real, common case), T2's and
T3's totals are already `<=` the segment count — so proportional redistribution has nothing to
redistribute; every segment is already pinned to the structural floor of 1. Re-verified directly
against the real 15-segment demo-lesson dataset (D85's own test data): T2 and T3 both still
produce `(1, 1)` for every segment, identical to the pre-D85 bug, while T1 (real headroom above
15) does differentiate — confirming the mechanism works, the VALUES don't fit real content.

**Confirmed before designing this fix, not assumed:** the LLM is not silently ignoring a wider
budget — `slide_generator_node`'s prompt sends the real per-segment range in plain text
(`f"(produce {min} to {max} slides for this segment)"`), so a `(1, 1)` budget produces exactly 1
slide because that is the literal instruction, not a model-compliance issue. Widening the range
is sufficient on its own; no separate prompt fix is needed.

**Real cost check before proposing numbers, not assumed:** from the real T3 demo lesson, TTS was
~70% of total lesson cost (per `decisionupdate.md`'s "67-73%" claim) at ~$0.89, implying total
lesson cost ≈ $1.27 and image+LLM spend ≈ $0.38 for 15 images (~$0.025/image). A few additional
slides per lesson adds cents, not dollars — nowhere near the $3.00 ceiling. Cost is not the real
constraint here, the same conclusion D76/D78 reached for the narration cap.

## The fix

Replace the fixed `_TIER_TOTAL_SLIDE_BAND` (a lesson-wide slide COUNT) with
`_TIER_MINUTES_PER_SLIDE_BAND` (a minutes-per-slide RATIO range per tier):

```python
_TIER_MINUTES_PER_SLIDE_BAND: dict[str, tuple[float, float]] = {
    "T1": (0.8, 1.2),
    "T2": (1.2, 1.8),
    "T3": (2.0, 3.0),
}
```

`_tier_slide_budget_per_segment` now derives `total_min`/`total_max` from the lesson's REAL
estimated total duration (`total_duration = sum(segment_durations_min)`, already computed) divided
by the tier's ratio range, instead of a fixed lookup — `total_min = total_duration / max_per_slide`,
`total_max = total_duration / min_per_slide`. The per-segment proportional-allocation loop D85
already built is otherwise **unchanged** — same `share = dur / total_duration`, same clamping to
the structural `[1, 8]` band. This is a minimal, additive change on top of D85, not a rewrite.

Worked example, the real 40.4-minute T3 demo lesson (15 segments, durations 1.23-3.48 min):
- **Before this fix:** every segment → `(1, 1)`, identical to the pre-D85 bug.
- **After this fix (T3, 2.0-3.0 min/slide):** longest segment (3.48 min) → `(1, 2)`; shortest
  (1.23 min) → `(1, 1)`. Real differentiation, proportionate to content, still lean (T3's job).
- Same dataset at T2 (1.2-1.8 min/slide): longest → `(2, 3)`; shortest → `(1, 1)`.
- Same dataset at T1 (0.8-1.2 min/slide): longest → `(3, 4)`; shortest → `(1, 2)`.

The zero-total-duration fallback (malformed/all-zero input — already proven unreachable through
`lesson_planner_node` itself by D85's own test, since the node's `duration_min > 0` guard runs
first; only reachable calling the function directly) simplifies to the safest lean default,
`(_MIN_SLIDES_PER_SEGMENT, _MIN_SLIDES_PER_SEGMENT)` for every segment — the old fixed-band-based
fallback formula no longer has a fixed band to fall back to, and this edge case never produces a
real distribution to preserve anyway.

## What this does NOT do

- Does not touch the per-segment proportional-allocation loop itself (D85, unchanged) — same
  `share`-based math, same `[1, 8]` structural clamp.
- Does not touch `slide_generator_node`'s prompt, validation, or truncation logic — confirmed
  unnecessary (see Context: the LLM already follows an explicit numeric instruction).
- Does not add a new total-lesson ceiling — the existing per-segment `_MAX_SLIDES_PER_SEGMENT=8`
  clamp, applied per segment regardless of the computed total, already bounds the worst case
  (15 segments x 8 = 120 slides structurally, unchanged by this fix).
- Does not touch `_MIN_SLIDES_PER_SEGMENT`/`_MAX_SLIDES_PER_SEGMENT` themselves.

## Scale & Load

1. **Unit of work & range.** One lesson's total estimated duration (minutes), already computed
   from real per-segment LLM estimates before this function runs — no new data required.
2. **Fixed budgets vs variable input.** `_TIER_MINUTES_PER_SLIDE_BAND` is the new fixed ratio;
   the computed total now SCALES with real content length instead of being capped at a number
   sized for a different, smaller assumed segment count — this IS the re-derivation D85 deferred,
   per Scale Contract Q5. The structural per-segment `[1,8]` clamp remains the real safety ceiling.
3. **Scope of the limit.** Per-lesson, per-tier — unchanged.
4. **Unbounded reads/writes.** None introduced.
5. **Inherited caps re-derived.** This IS the re-derivation — `_TIER_TOTAL_SLIDE_BAND`'s fixed
   totals were sized with no visibility into a real 15-segment lesson (D85's own finding); this
   story replaces them with a target that scales with real duration instead of needing
   re-derivation again the next time segment counts or lesson lengths change materially.
6. **Concurrency.** No change — pure function, no shared state.

## Verification

- RED-GREEN: existing D85 tests (`test_slide_budget_proportional_to_real_d85_durations`,
  `test_slide_budget_zero_total_duration_falls_back_to_flat_division`) updated to assert the NEW
  expected behavior (T2/T3 now DO differentiate on the real dataset — the opposite of what D85's
  test intentionally proved at the time); reverted the implementation via the Edit tool, confirmed
  the updated tests fail against the old fixed-band code with the exact predicted `(1,1)`-for-both
  mismatch, restored, confirmed green.
- New test asserting the worked-example numbers above for T2 and T1 (not just T3), so all three
  tiers are directly verified, not just the one the user observed.
- Full repo-wide regression against the established baseline, zero new failures.
- `ruff`/`mypy` clean on touched files.
