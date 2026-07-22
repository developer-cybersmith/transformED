---
baseline_commit: 9dcda1775aaaae3d8a13304c07499541f2fbbb2d
---

# Story 2.19: Populate narration timestamps so the player's slide-sync works

Status: ready-for-dev

> **BUG (HIGH), from the 2026-07-22 Dev1↔Dev2 audit.** `tts_node` ships `narration.timestamps: []` for every segment (Story 2-8 deferred it as "permanent scope"). The player derives `currentSlideId` **solely** from `narration.timestamps` with no fallback, so with `[]` it renders no slide during playback — the splash stays on screen for the whole lesson. This makes the core lesson-player experience non-functional for real pipeline output.

## Story

As a **student playing a generated lesson**,
I want the slides to appear and advance in time with the narration audio,
so that the player shows the lesson content instead of a static splash screen.

Dev 1's content-pipeline module. The frozen `LessonPackage` contract already
defines `NarrationTimestamp = {slide_id, start_ms, end_ms}`
(`packages/shared/lesson_package.schema.json:125-129`,
`packages/shared/types/lesson.ts:40-44`); the pipeline just never populates it.

## Observed Failure (from the audit)

- Producer: `tts_node` builds every `Narration` with `"timestamps": []`
  (`graph.py:3031`, `:3047`).
- Carrier: `package_builder_node` copies `narration` verbatim into each segment
  (`graph.py:3527`).
- Consumer: `AudioTimeline.processTimeUpdate` bails at
  `if (timestamps.length === 0) return` every tick, so `setCurrentSlide` never
  fires; `currentSlideId` stays `null`; `Player.tsx` shows only the splash.
  Every `currentSlideId` write in `player.machine.ts` reads
  `narration.timestamps[0]` with no fallback to `slides[0].slide_id`.

## Fix location & approach

`tts_node`'s input is `narration_scripts` ONLY (AC-1 of Story 2-8) — it does not
have the segment's slides, so it cannot map audio time → slide. **`package_builder_node`
is the correct place:** in its per-segment loop it already has both the segment's
`slides_with_images` (each with `slide_id`) and its `narration` (with `script`).
It synthesizes an **estimated** contiguous timestamp track by distributing the
segment's slides across an estimated narration duration derived from the script's
word count. This is an estimate (no real audio-probe / forced-alignment — that
remains deferred), documented as such, and honors CLAUDE.md's estimate-and-degrade
ethos; it restores slide display and the timestamp-based quiz-boundary at MVP
fidelity.

## Acceptance Criteria

1. **AC-1 — every packaged segment has a non-empty, contract-valid timestamp track.** For each segment `package_builder_node` emits `narration.timestamps` as a list of `{slide_id, start_ms, end_ms}` with exactly one entry per slide in `slides` (in slide order), matching `lesson_package.schema.json`'s `NarrationTimestamp` (`start_ms ≥ 0`, integers). A segment always has ≥1 slide (package_builder already skips segments with no slides), so the list is never empty.
2. **AC-2 — the track is contiguous and monotonic, starting at 0.** The first slide's `start_ms == 0`; each entry's `start_ms == previous end_ms`; `start_ms < end_ms` for every entry; the last entry's `end_ms == the estimated segment duration`. This is what the player's `binarySearchTimestamps` + `timestamps.at(-1).end_ms` require.
3. **AC-3 — duration is estimated from the narration script word count.** `estimated_duration_ms = round(word_count / settings.narration_words_per_minute * 60_000)`, distributed evenly across the segment's N slides. When the script is empty / word_count 0, fall back to `settings.default_ms_per_slide` per slide so the track is still non-degenerate (`start_ms < end_ms`).
4. **AC-4 — new settings, env-overridable, no hardcoded values.** `narration_words_per_minute: int = 150` (`gt=0`) and `default_ms_per_slide: int = 5000` (`gt=0`) added to `config.py` following the existing `Field` pattern.
5. **AC-5 — `tts_node` behavior unchanged.** `tts_node` still emits `timestamps: []` (it lacks slide context); the population happens only in package_builder. No change to tts_node's contract, cost path, or fallback.
6. **AC-6 — Coverage.** New tests: one-timestamp-per-slide; contiguity/monotonicity/first-start-0/last-end-eq-duration; empty-script fallback; multi-slide distribution; and a package-level assertion that a built package's `narration.timestamps` is non-empty and schema-shaped. Existing package_builder tests updated only where they assert the (previously empty) timestamps.
7. **AC-7 — Constraints preserved.** No hardcoded models; providers untouched; degrade-not-fabricate (estimate, never fabricate audio); package_builder still assembles from module-owned state only.

## Tasks / Subtasks

- [ ] Task 1: Config (AC-4) — add `narration_words_per_minute`, `default_ms_per_slide`.
- [ ] Task 2: `_estimate_slide_timestamps(slides, script, *, wpm, default_ms_per_slide)` pure helper (AC-1..AC-3) + wire into `package_builder_node`'s per-segment assembly (set `narration = {**narration, "timestamps": ...}`).
- [ ] Task 3: Tests (AC-6) — RED first.
- [ ] Task 4: Regression — full unit suite + ruff + mypy green.

## Dev Notes

- package_builder per-segment loop: `graph.py:3461-3534`. `narration = audio_by_id.get(segment_id)` (dict with `script`), `slides_with_images` (list with `slide_id`). Set the computed timestamps onto a copy of `narration` before it's written at `:3527`.
- Timestamp contract: `{slide_id: str, start_ms: int ≥ 0, end_ms: int}` — integers, milliseconds. Player: `binarySearchTimestamps(timestamps, ms)` → slide; `timestamps.at(-1).end_ms` → quiz boundary (`AudioTimeline.tsx:41-55`).
- Estimate only — real forced-alignment/word-timing stays deferred (Story 2-8's original scope note). Keep the docstring honest about this.
- Do NOT touch `tts_node`'s `timestamps: []` (AC-5) — it has no slides; moving the logic there would violate its `narration_scripts`-only input contract.

### Constraints (CLAUDE.md)
`settings.*` for tunables; no hardcoded models; degrade-not-fabricate; module-owned state only.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-22 | Bug story from the Dev1↔Dev2 audit (HIGH: empty timestamps break player slide-sync). | Dev 1 (BMAD create-story) |

## Dev Agent Record

_(to be completed during `dev-story`)_
