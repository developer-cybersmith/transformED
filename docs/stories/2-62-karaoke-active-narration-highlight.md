---
title: "Story 2-62 — Karaoke-Style Active-Narration Highlight (BR-4)"
status: in-progress
owners: [Dev 2]
sprint: bug-resolution
---

# Story 2-62 — Karaoke-Style Active-Narration Highlight (BR-4)

## Problem Statement

BR-3 (Story 2-61) synced `CaptionOverlay` to the real per-line `start_ms`/`end_ms` windows in
`Narration.caption_lines` (Story 4-29 / BR-6), replacing the old proportional-by-character-count
line-selection estimate with the real thing. BR-4 is the next line item in
`docs/dev2-sprint-tracker.md`: "Highlight/underline the currently-spoken text on the slide, synced
to the same caption timestamps BR-3 consumes" — i.e. *within* the currently-active caption line,
progressively highlight the words already spoken as playback advances through that line's own
`[start_ms, end_ms)` window, karaoke-style.

There is still no word-level timing anywhere in the pipeline (confirmed unchanged by Story 4-29 —
line-level was declared sufficient for both BR-1 and this feature). So, consistent with the
existing character-count-proportional idiom already used twice elsewhere in this codebase
(`_split_into_caption_lines`'s duration distribution, and the pre-BR-3 `activeCaptionLineIndex`'s
line-duration distribution), word-level progress within a line is estimated by allocating the
line's own real, measured duration proportionally across the line's words by character count.

**Design decision — real timestamps only.** This highlight is enabled ONLY on the real-timestamp
path (`captionLines` present and non-empty) — never on the pre-existing proportional-fallback path
(older lesson records, browser-TTS fallback, or a `tinytag` failure at generation time). Layering a
second, word-level estimate on top of an already-approximate, line-level estimate (the fallback's
own line windows are themselves guessed from total segment duration, not measured) would compound
two levels of guesswork into a highlight that visibly drifts from the narration — the opposite of
"karaoke-style." This matches BR-4's own stated dependency ("blocked on Dev 1's caption timestamp
output") literally: no real timestamps, no karaoke highlight, plain line text only (today's BR-3
fallback behavior, unchanged).

## Acceptance Criteria

- **AC1** — New pure function `lineProgress(line: CaptionLine, positionMs: number): number` returns
  the fraction of `[line.start_ms, line.end_ms)` elapsed at `positionMs`, clamped to `[0, 1]`
  (`positionMs <= start_ms` → `0`; `positionMs >= end_ms` → `1`; a zero-or-negative span → `1`).
- **AC2** — New pure function `karaokeSpokenWordCount(text: string, progress: number): number`
  returns how many of `text`'s space-separated words are considered "spoken" at `progress`,
  allocating `progress * text.length` proportionally by character position (same idiom as
  `_split_into_caption_lines`/the pre-existing `activeCaptionLineIndex`) — a word counts as spoken
  once its own end character offset is `<=` the target character offset. `progress <= 0` → `0`;
  `progress >= 1` → all words; empty text → `0`.
- **AC3** — `CaptionOverlay`, only when `hasRealTimestamps` is true, splits the active line's text
  into a "spoken" prefix (rendered with a visible highlight — underline + accent color) and an
  "unspoken" remainder (rendered muted), using `karaokeSpokenWordCount(activeText,
  lineProgress(captionLines[activeIndex], audioPositionMs))` as the split point. Either sub-span is
  omitted entirely (not rendered as an empty element) when it has no words — so at the very start of
  a line (progress 0) or a fully-elapsed line (progress 1) the line still renders as a single text
  node, unchanged from BR-3's existing behavior at those boundaries.
- **AC4** — On the fallback path (`captionLines` undefined or `[]`), rendering is byte-for-byte
  unchanged from BR-3 — the active line's plain text, no spoken/unspoken split, ever.
- **AC5** — All pre-existing `CaptionOverlay.test.tsx` tests (BR-3 and earlier) pass unmodified —
  every existing assertion point happens to land on a line-start boundary (progress 0), which AC3
  guarantees renders as a single, undivided text node exactly like before.
- **AC6** — New tests: `lineProgress` (clamp before start, clamp at/after end, mid-line fraction,
  zero-span line); `karaokeSpokenWordCount` (progress 0, progress 1, empty text, a mid-progress case
  with a hand-computed expected word count); `CaptionOverlay` integration (mid-line position splits
  into a correct spoken prefix + unspoken remainder with distinct, queryable sub-elements; line-start
  position renders no spoken sub-span at all; the fallback path never renders either sub-span even at
  a mid-position, confirming AC4).
- **AC7** — `tsc --noEmit` and targeted `eslint` clean; full frontend suite green, zero regressions.

## Scale & Load

N/A for all six questions — pure client-side rendering/selection logic over data already loaded and
already bounded (Story 4-29's own Scale & Load: ≤ ~51 `caption_lines` per segment in practice; each
line's own word count is bounded by the same per-line character cap, `CAPTION_MAX_CHARS_PER_LINE`,
default 120). No new network call, no new query, no unbounded read/write, no concurrency-sensitive
check-then-act — two additional pure functions over numbers/strings already in scope, re-evaluated
on the same render cadence `activeCaptionLineIndexFromTimestamps` already runs on.

## Dev Notes

- Reuses `packages/shared/types/lesson.ts`'s `CaptionLine` (already imported by `CaptionOverlay.tsx`
  from Story 2-61) — no schema change, no new prop; this story only adds internal logic to the
  existing `captionLines` prop.
- Do not attempt to derive per-word timing from the TTS providers — confirmed in Story 4-29 that
  none of Sarvam/Azure/Browser (nor Vexyl/Fish Audio, out of scope) return word-level timing. The
  proportional-by-character-count estimate is the deliberate, documented approach, matching the
  precedent already accepted twice in this codebase for the exact same reason.
- Visual treatment: underline + `var(--accent-primary)` for the spoken prefix, mirroring
  `SlideRenderer.tsx`'s existing use of that same CSS var for on-brand accent color, rather than
  introducing a new one-off color.
- `karaokeSpokenWordCount`'s word-boundary check (word "spoken" once its own end offset, not
  including a trailing space, is within the proportional target) was verified by hand against the
  fixture line used in `CaptionOverlay.test.tsx` (`"Real line one from the server."`, 30 chars) at
  multiple progress fractions before writing the test assertions — see Dev Agent Record.

## Dev Agent Record

### Completion Notes

_(filled in after implementation)_

### File List

- `apps/web/src/components/player/CaptionOverlay.tsx`
- `apps/web/src/__tests__/components/player/CaptionOverlay.test.tsx`

## References

- [Source: docs/dev2-sprint-tracker.md — BR-4] — the task itself, its stated dependency
- [Source: docs/stories/2-61-caption-sync-real-timestamps.md] — BR-3, the line-selection story this
  one extends (same `captionLines` prop, same `hasRealTimestamps` gate)
- [Source: docs/stories/4-29-caption-lines-schema-pipeline.md] — confirms line-level timing is
  final/sufficient (no word-level timing to wait for) and names this feature explicitly
