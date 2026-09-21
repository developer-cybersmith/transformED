# Story S5-2 — HIE Lecture-Format System Prompts

**Sprint:** 5  
**Story:** S5-2  
**Author:** Dev 1 / Dev 3 joint  
**Status:** Ready for implementation  
**Branch:** `sprint5/s5-2-hie-format-prompts`  
**Date:** 2026-09-21

---

## Background

The lesson generation pipeline supports three lesson durations: 45 min (T1), 30 min (T2), and 15 min (T3).
The frontend already exposes this choice via `ModeSelection` / `LEARNER_TIER_OPTIONS` (deep/balanced/refresher).

Currently `_TIER_PROMPT_FRAMING` in `graph.py` contains only vague instructions:
- T1: "cover the topic thoroughly, including secondary sub-topics and nuance"
- T2: *missing entirely* — the dict has no "T2" key, so T2 lessons receive zero format framing
- T3: "select only the most essential, foundational sub-topics"

The HIE (Human Inference Engine) curriculum design specifies exact slide structures per duration:
- **T3 (15 min):** 7 slides — HIE Compressed First-Teach Protocol
- **T2 (30 min):** 10 slides — HIE Compressed Dual-Topic Protocol
- **T1 (45 min):** 10 slides — HIE Master Session Structure (with binding per-slide timings)

Additionally, `_TIER_MINUTES_PER_SLIDE_BAND` is severely misaligned with HIE's fixed slide counts:
- T1: current (0.8, 1.2) → for a 45-min lesson, gives budget of 37–56 slides (HIE requires 10)
- T2: current (1.2, 1.8) → for a 30-min lesson, gives budget of 17–25 slides (HIE requires 10)
- T3: current (2.0, 3.0) → for a 15-min lesson, gives budget of 5–7.5 slides (HIE requires 7) ✓

This story replaces the vague framing with the full HIE format specifications and re-derives `_TIER_MINUTES_PER_SLIDE_BAND` to match.

---

## User Story

> As a student who selects a lesson duration (15/30/45 min), I want the generated lesson to
> follow the exact HIE slide structure for that duration, so every lesson has a predictable,
> pedagogically sound format regardless of which chapter I generate.

---

## Acceptance Criteria

### Backend — `graph.py`

**AC1.** `_TIER_PROMPT_FRAMING["T3"]` contains the complete 7-slide HIE Compressed First-Teach
Protocol specification, including the binding slide sequence (Conceptual Framing → Core Teach ×2 →
Split-Screen Demonstration ×2 → Anticipated Q&A → Wrap & Bridge), timing targets, and split-screen
ratio constraint (40/60 visual-to-text, never merged into one panel).

**AC2.** `_TIER_PROMPT_FRAMING["T2"]` contains the complete 10-slide HIE Compressed Dual-Topic
Protocol specification, including the two-topic structure, split-screen slides for each topic, and
Combined Mind-Map as the final slide. T2 previously had **no key** in this dict — it now has one.
A unit test asserts `"T2" in _TIER_PROMPT_FRAMING and len(_TIER_PROMPT_FRAMING["T2"]) > 0`.

**AC3.** `_TIER_PROMPT_FRAMING["T1"]` contains the complete 10-slide HIE Master Session Structure
specification, with all 10 slide titles and their **binding timings** (3:00 + 2:30 + 7:00 + 5:00 +
2:30 + 7:00 + 5:00 + 2:30 + 5:00 + 5:30 = 45:00), and the single-line RULES suffix.

**AC4.** `_TIER_MINUTES_PER_SLIDE_BAND` is updated to values derived from HIE slide counts:
- T1: `(4.0, 5.0)` — 45 min / 10 slides ≈ 4.5 min/slide; band covers 9–11 slides for a 45-min lesson
- T2: `(2.8, 3.5)` — 30 min / 10 slides ≈ 3.0 min/slide; band covers 8.6–10.7 slides for a 30-min lesson
- T3: `(2.0, 2.5)` — 15 min / 7 slides ≈ 2.14 min/slide; band covers 6–7.5 slides for a 15-min lesson

A unit test asserts the new values and verifies that `45 / 5.0 >= 9` (T1 min slides ≥ 9).

**AC5.** The `_planner_system_prompt(tier_framing)` function signature and internal logic are
**unchanged** — no structural code modifications, only the constant dict values change.

**AC6.** No HIE format text is duplicated outside `_TIER_PROMPT_FRAMING`. Any future format
change is a one-dict edit.

**AC7.** Guard tests `test_node_return_shape`, `test_unbounded_queries`, and all `test_no_hardcoded_*`
pass without allowlist changes — this story touches only string constants and a numeric dict, not
node return shapes or hardcoded model identifiers.

### Frontend — `learnerMode.ts`

**AC8.** `LEARNER_TIER_OPTIONS` labels and descriptions are updated to reflect HIE format names:
- `id: 'deep'` → `label: '45 min'`, description references "HIE Master Session (dual-topic)"
- `id: 'balanced'` → `label: '30 min'`, description references "HIE Dual-Topic Protocol"
- `id: 'refresher'` → `label: '15 min'`, description references "HIE First-Teach (single topic)"

**AC9.** `LEARNER_TIER_TO_BACKEND` mapping is **unchanged** (`deep→T1`, `balanced→T2`, `refresher→T3`).
The `LearnerTier` union type is **unchanged**. No `packages/shared/` files are touched.

### Tests

**AC10.** A new test file `apps/api/tests/test_s5_2_hie_prompts.py` (or added to an existing
appropriate file) covers:
- T2 key exists in `_TIER_PROMPT_FRAMING` and is non-empty
- T1 framing contains "10 slides" and "45"
- T2 framing contains "10 slides" and "30"
- T3 framing contains "7 slides" and "15"
- `_TIER_MINUTES_PER_SLIDE_BAND["T1"]` == `(4.0, 5.0)`
- A 45-min T1 lesson (total_duration=45) produces total slide budget in range [9, 12] via
  `_tier_slide_budget_per_segment` with a realistic segment list

---

## Out of Scope

- Restructuring how `structure_detect` groups content into topics (HIE's "2-topic" concept is
  expressed via the planner prompt; segment count remains unchanged).
- Modifying the slide generator node prompt — it already reads the planner's structured output and
  generates slides per segment; the updated slide count budget from AC4 is sufficient.
- Any DB migration or API endpoint changes.
- The chapter-level context form (§4.3) — that is S5-3.

---

## Files Changed

| File | Change |
|------|--------|
| `apps/api/app/modules/content/pipeline/graph.py` | Replace `_TIER_PROMPT_FRAMING` values, update `_TIER_MINUTES_PER_SLIDE_BAND` |
| `apps/web/src/types/learnerMode.ts` | Update `LEARNER_TIER_OPTIONS` labels/descriptions |
| `apps/api/tests/test_s5_2_hie_prompts.py` | New: unit tests for AC2, AC4, AC10 |

---

## Scale & Load

**Q1 — Unit of work and range:**  
One unit = one lesson planner LLM call. `_TIER_PROMPT_FRAMING` is a module-level dict constant; it
is read once per call and appended verbatim. T1 framing ≈ 620 chars, T2 ≈ 570 chars, T3 ≈ 480 chars.
Range: fixed, always exactly one tier framing string per planner call. No variability.

**Q2 — Fixed budgets while input varies:**  
`tier_framing` is concatenated directly into the planner system `base` string before
`merge_book_context` runs. It is NOT subject to `merge_book_context`'s 2,000-char truncation cap
(that cap applies only to the appended book_context block). The combined system prompt
(base ≈ 500 chars + tier_framing ≈ 620 chars + book_context ≤ 2,000 chars) totals ≤ 3,120 chars,
well within GPT-4o's 128k context. No truncation risk. If `_TIER_PROMPT_FRAMING` values ever
exceed ~10,000 chars each, this must be re-evaluated against the context budget.

**Q3 — Scope of every limit:**  
Per LLM call, per lesson, per user. `_TIER_PROMPT_FRAMING` is a read-only constant shared across
all concurrent requests — no per-user or per-instance state.

**Q4 — Unbounded reads/writes:**  
None. `_TIER_PROMPT_FRAMING` and `_TIER_MINUTES_PER_SLIDE_BAND` are module-level constants;
no DB reads or writes in this story.

**Q5 — Inherited caps re-derived:**  
`_TIER_MINUTES_PER_SLIDE_BAND` was sized in Story 2-LM5 with no visibility into HIE's fixed slide
counts (D87 already noted the mismatch for T2/T3 at 15 segments). Re-derived here:
- T1 target: 45 min / 10 slides = 4.5 min/slide → band (4.0, 5.0) gives 9–11 slides at 45 min ✓
- T2 target: 30 min / 10 slides = 3.0 min/slide → band (2.8, 3.5) gives 8.6–10.7 slides at 30 min ✓
- T3 target: 15 min / 7 slides = 2.14 min/slide → band (2.0, 2.5) gives 6.0–7.5 slides at 15 min ✓

**Q6 — Check-then-act under concurrent requests:**  
N/A — this story has no check-then-act sequences. All changes are to read-only constants.

---

## BMAD Pre-Implementation Gate

- [x] Story file created at `docs/stories/S5-2-hie-format-prompts.md`
- [ ] Story-only commit on `sprint5/s5-2-hie-format-prompts`
- [ ] Story-only push to remote
- [ ] Implementation begins (RED phase — failing tests first)
