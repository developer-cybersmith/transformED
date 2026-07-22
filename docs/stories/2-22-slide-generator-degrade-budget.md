---
baseline_commit: 52ff4df76a580a45b540f33d569206977a6672e3
---

# Story 2.22: slide_generator degrades per-segment on off-budget slide count (no wholesale reject)

Status: ready-for-dev

> **BUG (MED), from the 2026-07-22 audit.** `slide_generator_node` raises `RuntimeError` on the **first** segment whose slide count falls outside its `slide_budget` (`graph.py:1597`), discarding every valid slide-set and failing the whole premium node — after `lesson_planner` and all Phase-1 spend. Unlike `lesson_planner` (which batches) and Phase-1 (which degrades per section), it trusts one large multi-segment completion to be exactly right for every segment.

## Root cause & fix

The slide_budget is a soft target, not an integrity invariant. Replace the wholesale `raise` with a **per-segment clamp**: if a segment returns more than `seg_max` slides, truncate to `seg_max` (respects the cost intent, logged); if fewer than `seg_min`, accept as-is (a soft-min miss is not worth failing a lesson, logged). The **integrity** guards (count mismatch, unknown id, duplicate id, blank slide title) are UNCHANGED — those still reject wholesale (they indicate a genuinely broken response, not a budget miss).

## Acceptance Criteria

1. **AC-1** — a segment with `len(slides) > seg_max` is truncated to `seg_max` (first `seg_max` slides kept), logged at WARNING; the node does not raise.
2. **AC-2** — a segment with `len(slides) < seg_min` is accepted as-is, logged; the node does not raise (a segment must still have ≥1 slide — the schema/blank-title guards cover that).
3. **AC-3** — the other segments' valid slide-sets are preserved (one off-budget segment no longer discards the deck).
4. **AC-4** — integrity guards unchanged: count-mismatch / unknown-id / duplicate-id / blank-slide-title still `raise` (a genuinely wrong response is still rejected).
5. **AC-5** — Coverage: an over-budget segment is truncated (others intact); an under-budget segment is accepted; a count-mismatch/unknown/duplicate still raises. Existing tests updated only where they asserted the budget `raise`.
6. **AC-6** — constraints preserved (no hardcoded models; degrade-not-fabricate — truncation drops excess, never invents slides).

## Tasks / Subtasks
- [ ] Task 1: replace the budget `raise` (`graph.py:1597-1601`) with clamp-and-warn; keep integrity guards.
- [ ] Task 2: Tests (AC-5). RED first.
- [ ] Task 3: Regression green.

## Dev Notes
- Budget check at `graph.py:1589-1601`; integrity guards at `:1571-1587`; blank-title guard at `:1602-1607`. Truncate BEFORE the blank-title loop so a truncated set is still title-validated.
- Existing `test_slide_generator_node.py` has an off-count test that expects a raise — update it to assert the clamp (truncate) / accept behavior; keep the count/unknown/duplicate raise tests.

## Change Log
| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story from the Dev1↔Dev2 audit (MED: one off-budget segment fails the whole deck). | Dev 1 |

## Dev Agent Record
_(to be completed during dev-story)_
