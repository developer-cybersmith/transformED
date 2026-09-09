---
title: "Story 2-61 — Caption/Subtitle Display: Sync to Real Line-Level Timestamps (BR-3)"
status: in-progress
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-61 — Caption/Subtitle Display: Sync to Real Line-Level Timestamps (BR-3)

## Problem Statement

`CaptionOverlay.tsx` (Story S4-09) already shows one caption line at a time, but with no real
per-line timing anywhere in the pipeline it estimated each line's time window client-side —
splitting the script into ~10-word lines and distributing the segment's total known duration
proportionally by character count (`splitScriptIntoCaptionLines` + `activeCaptionLineIndex`). That
was an explicit, documented approximation, not real sync: pacing, pauses, and emphasis all shift
true timing.

Story 4-29 (BR-6, PR #219, merged to `main` 2026-09-09) closed the missing half of this: the
`package_builder_node` now populates `Narration.caption_lines: CaptionLine[]` — real line text
already split server-side at sentence boundaries, with `start_ms`/`end_ms` distributed
proportionally from the actual `tinytag`-measured audio duration, not an unknown client-side guess.
`caption_lines` is optional/retroactive (empty `[]` when `duration_ms` was unavailable — browser-TTS
fallback or a `tinytag` failure at generation time, and absent entirely on any lesson record
generated before this field existed).

This story is BR-3's own remaining half: make `CaptionOverlay` consume `Narration.caption_lines`
directly when present, and fall back to the existing client-side proportional-split path only when
it is missing or empty — never regressing the caption experience on older or degraded lesson
records.

## Acceptance Criteria

- **AC1** — `CaptionOverlayProps` gains an optional `captionLines?: CaptionLine[]` prop (type
  imported from `packages/shared/types/lesson.ts`, not redeclared locally).
- **AC2** — When `captionLines` is a non-empty array, the active line is selected directly from its
  real `start_ms`/`end_ms` windows (new pure function `activeCaptionLineIndexFromTimestamps`), and
  the displayed text is `captionLines[activeIndex].text` — the client-side `splitScriptIntoCaptionLines`
  / `activeCaptionLineIndex` estimate is not used at all on this path.
- **AC3** — When `captionLines` is `undefined` or `[]`, behavior is byte-for-byte unchanged from
  today: `splitScriptIntoCaptionLines(script)` + `activeCaptionLineIndex(lines, positionMs,
  durationMs)` against `audioPositionMs`/`audioDurationMs`, so every existing passing test for the
  proportional-estimate path keeps passing unmodified.
- **AC4** — `activeCaptionLineIndexFromTimestamps(lines, positionMs)`:
  - Returns `-1` for an empty `lines` array.
  - Returns the index `i` of the first line where `positionMs < lines[i].end_ms` (i.e. `positionMs`
    falls inside `[lines[i].start_ms, lines[i].end_ms)` for a well-formed, gapless, ordered list —
    matching the exact invariant `_split_into_caption_lines` (Story 4-29 AC4) already guarantees:
    contiguous windows, last line's `end_ms` equal to the full segment duration).
  - Clamps to `0` when `positionMs` is before the first line's `start_ms` (only possible during the
    first render tick before playback position updates).
  - Clamps to the last line's index once `positionMs` reaches or exceeds the last line's `end_ms`
    (mirrors the existing proportional path's same clamp-to-last behavior, e.g. during teach-back
    after the segment has ended).
- **AC5** — `Player.tsx` passes `captionLines={segment?.narration.caption_lines}` alongside the
  existing `script={segment?.narration.script ?? null}` — no other change to how `CaptionOverlay` is
  invoked.
- **AC6** — New tests cover: a real-timestamp script advances through 2+ lines as
  `audioPositionMs` crosses each line's `end_ms` boundary; the real-timestamp path is used (not the
  proportional fallback) when `captionLines` is present even if line text differs from a naive
  word-split of `script`; the fallback path is preserved when `captionLines` is `undefined` and
  separately when it is `[]`; `activeCaptionLineIndexFromTimestamps` unit tests for empty input,
  before-first-line clamp, mid-line selection, exact-boundary transition, and after-last-line clamp.
- **AC7** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green, zero regressions.

## Scale & Load

N/A for all six questions — this is a pure rendering/selection change over an already-bounded,
already-generated array (`caption_lines`, itself bounded per Story 4-29's own Scale & Load section
by the existing per-segment narration character cap, in practice ≤ ~51 lines per segment). No new
network call, no new query, no unbounded read/write, no concurrency-sensitive check-then-act — the
component reads two numbers (`audioPositionMs`/`audioDurationMs`) already in the player store and
one array already present on the loaded `LessonPackage`.

## Dev Notes

- Source of the real data: `packages/shared/types/lesson.ts` — `CaptionLine { text; start_ms;
  end_ms }`, `Narration.caption_lines?: CaptionLine[]` (Story 4-29). Import the type, do not
  redeclare an equivalent shape locally.
- `_split_into_caption_lines` (backend, Story 4-29 AC4/AC6f) guarantees contiguous, ordered windows
  with the last line's `end_ms` exactly equal to the measured `duration_ms` — the frontend selection
  function can rely on that invariant rather than re-validating gaps/overlaps itself.
- Do not remove `splitScriptIntoCaptionLines` / `activeCaptionLineIndex` — they remain the correct
  behavior for the documented degraded case (`caption_lines` empty/absent), per Story 4-29 AC5's own
  rationale (an estimate without a measured audio anchor is the honest fallback, not a regression to
  patch over).
- The comment block above `<CaptionOverlay .../>` in `Player.tsx` ("Non-synced caption panel (D90)")
  is stale — predates both S4-09 and this story. Update it to reflect the real-timestamp path now
  that one exists.

## Dev Agent Record

### Completion Notes

_(filled in after implementation)_

### File List

- `packages/shared/types/lesson.ts` (already contains `CaptionLine`/`Narration.caption_lines` from
  Story 4-29 — read-only for this story)
- `apps/web/src/components/player/CaptionOverlay.tsx`
- `apps/web/src/components/player/Player.tsx`
- `apps/web/src/__tests__/components/player/CaptionOverlay.test.tsx`

## References

- [Source: docs/dev2-sprint-tracker.md — BR-3] — the task itself
- [Source: docs/stories/4-29-caption-lines-schema-pipeline.md] — the backend half this story
  consumes (`caption_lines` schema + server-side estimation)
- [Source: apps/web/src/components/player/CaptionOverlay.tsx] — existing proportional-estimate
  implementation (Story S4-09) this story extends, not replaces
