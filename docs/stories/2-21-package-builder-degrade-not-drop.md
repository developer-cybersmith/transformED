---
baseline_commit: 52ff4df76a580a45b540f33d569206977a6672e3
---

# Story 2.21: package_builder degrades a segment instead of dropping it whole

Status: ready-for-dev

> **BUG (MED), from the 2026-07-22 audit.** `package_builder_node` requires complexity AND narration AND interventions AND slides for each plan segment (`graph.py:3478`); if any is missing (an economy node returned `[]` on an LLM refusal), it **skips the entire segment** — discarding the parts that DID succeed (quiz, summary, slides). If enough segments drop, it raises "produced zero usable segments" **after the full Phase-1 + planner + tts + image spend**.

## Root cause & fix

Only `slides` is genuinely mandatory (the `Segment` schema requires `min_length=1` slides — a slideless segment can't render). complexity / narration / interventions can be **backfilled with neutral, valid defaults** so a segment with slides is never discarded:
- missing `narration` → browser-fallback `Narration` (`script=""`, `audio_url=""`, `audio_provider="browser"`, timestamps estimated from the slides) — the same "no audio" state `tts_node` itself emits on failure.
- missing `complexity` → neutral `SegmentComplexity` (level `medium`, sensitivity 0.5).
- missing `interventions` → neutral `SegmentInterventions` (3 generic encouragement messages per type).

Each backfill is logged as a degrade. "zero usable segments" now only fires when **no** segment has slides (a genuine empty-lesson failure).

## Acceptance Criteria

1. **AC-1** — a segment with slides is kept even when complexity / narration / interventions are missing; missing fields are backfilled with the neutral valid defaults above and the assembled `Segment` validates against the frozen schema.
2. **AC-2** — a segment with **no** slides is still skipped (schema `min_length=1`), logged.
3. **AC-2b** — the succeeded parts (quiz, summary, slides, jargon) of a degraded segment are preserved, not discarded.
4. **AC-3** — each backfilled field is logged at WARNING with the segment_id and which fields were degraded.
5. **AC-4** — "produced zero usable segments" raises only when every plan segment lacked slides.
6. **AC-5** — Coverage: a segment missing narration (only) is kept with browser-fallback narration + its quiz/slides intact; missing complexity → default; missing interventions → default; no-slides → skipped; all-no-slides → raises. Existing happy-path tests unmodified.
7. **AC-6** — degrade-not-fabricate honored (defaults are neutral/valid, logged; no invented analysis content); no hardcoded models.

## Tasks / Subtasks
- [ ] Task 1: default builders `_default_complexity()`, `_fallback_narration(slides)`, `_default_interventions()`.
- [ ] Task 2: rework the per-segment gate — skip only on no-slides; backfill + log otherwise.
- [ ] Task 3: Tests (AC-5). RED first.
- [ ] Task 4: Regression green.

## Dev Notes
- Gate is at `graph.py:3478`; zero-raise at `graph.py:3532`. `SegmentComplexity`/`Narration`/`SegmentInterventions` shapes in `app/schemas/lesson.py:66-173`. Reuse `_estimate_slide_timestamps` for the fallback narration's timestamps.
- Complexity dict is written with `segment_id` stripped (`graph.py:3525`); build the default already-stripped.

## Change Log
| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story from the Dev1↔Dev2 audit (MED: whole-segment drop discards succeeded work + zero-segments after spend). | Dev 1 |

## Dev Agent Record
_(to be completed during dev-story)_
