---
title: "Story 2-62 — Karaoke-Style Active-Narration Highlight (BR-4)"
status: done
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
  a line (progress 0) the line renders as a single unstyled text node inside `caption-unspoken`
  (unchanged from BR-3's plain rendering at that boundary), and at a fully-elapsed line (progress 1)
  the line renders as a single node inside `caption-spoken` — fully highlighted, not plain — since
  the entire line has, by definition, already been spoken. **Corrected 2026-09-10, post-review**:
  this AC originally said progress 1 should also render "unchanged from BR-3" (i.e. unstyled);
  that was imprecise story wording caught by the Acceptance Auditor layer of this story's own
  `/bmad-code-review` — the shipped behavior (full highlight at completion) is the intended one.
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

- **AC1/AC2-DONE.** `lineProgress(line, positionMs)` and `karaokeSpokenWordCount(text, progress)`
  added as pure exported functions, both hand-verified against the real 30-char fixture
  `"Real line one from the server."` at multiple progress fractions before the test assertions were
  written (see test file comments for the hand-computed word end offsets).
- **AC3-DONE.** `CaptionOverlay` computes `spokenText`/`unspokenText` via
  `karaokeSpokenWordCount(activeText, lineProgress(captionLines[activeIndex], audioPositionMs))` on
  the real-timestamp path only; either `<span>` is conditionally omitted when empty, so progress-0
  and progress-1 render as a single undivided text node.
- **AC4-DONE.** Fallback path (`captionLines` undefined/`[]`) is untouched — `hasRealTimestamps`
  gates the entire karaoke branch; a dedicated test confirms neither sub-span testid ever appears on
  that path even at a mid-position.
- **AC5-DONE.** All pre-existing `CaptionOverlay.test.tsx` tests (26, from S4-09 + BR-3) pass
  unmodified — every existing assertion happens to check at a line-start boundary (progress 0),
  confirmed by re-running the full pre-existing test file with zero changes to those tests.
- **AC6-DONE.** 11 new tests: 4 `lineProgress` unit tests, 4 `karaokeSpokenWordCount` unit tests
  (including the hand-computed mid-progress case), 3 `CaptionOverlay` integration tests (mid-line
  split, progress-0 single-span, fallback-path guard).
- **AC7-DONE.** `tsc --noEmit` clean, targeted `eslint` clean. Full frontend suite: 93 files / 1168
  tests (was 93/1157 pre-story), zero regressions.
- **Verification method, disclosed explicitly:** verified via the unit/integration test suite only,
  not a live browser check like BR-3's. This story's data (`captionLines` prop, exact `start_ms`/
  `end_ms` windows) is fully exercised by deterministic tests; a genuine live-browser check would
  need a real backend-generated lesson with populated `caption_lines`, which is out of scope here
  (frontend-only work, no `apps/api` changes or backend runs made for this story).

### File List

- `apps/web/src/components/player/CaptionOverlay.tsx`
- `apps/web/src/__tests__/components/player/CaptionOverlay.test.tsx`

## Review Findings

_6-agent BMAD code review, 2026-09-10, PR #224 — Blind Hunter, Edge Case Hunter, Acceptance
Auditor, Scale & Load Hunter, Story Quality, Test Coverage, AC Completeness, Process Integrity._

- [x] [Review][Defer] Long/single leading word creates a proportional "dead zone" with zero
      karaoke progress before snapping to spoken — deferred, registered as **D-166** in
      `docs/DEFECT-REGISTER.md` per user decision 2026-09-10: accept as a known limitation of the
      character-proportional, whole-word-reveal model rather than change the crediting algorithm
      (e.g. midpoint-crediting) inside a review-response pass.
- [x] [Review][Patch] AC3's own wording ("progress 1 renders... unchanged from BR-3's existing
      behavior") corrected below to describe the actual (correct) implementation — a fully-elapsed
      line collapses into the highlighted `caption-spoken` span as a single node, not an unstyled
      one. Behavior unchanged; only the AC text was wrong.
- [x] [Review][Defer] Dev Agent Record / Completion Notes were appended to this story file in the
      same commit (`ba467ba`) as the implementation code — deferred, per user decision 2026-09-10:
      accept as-is rather than rewrite already-pushed PR branch history; note for future stories to
      land completion-notes updates as a separate trailing commit instead.
- [x] [Review][Patch] `lineProgress`/`karaokeSpokenWordCount` do not guard against `NaN`
      `positionMs` — reachable in production because `player.machine.ts`'s `audioPositionMs` setter
      has no `Number.isFinite` guard (unlike its own localStorage-restore path, which does validate).
      A transient `NaN` silently freezes the karaoke highlight at "nothing spoken" with no error.
      Confirmed independently by Blind Hunter and Edge Case Hunter. **Fixed**: both functions now
      clamp `NaN` (line span or position/progress) to `0` explicitly, without disturbing correct
      existing behavior for out-of-range-but-finite values like `+Infinity` (new regression tests
      added for that distinction). [`apps/web/src/components/player/CaptionOverlay.tsx`]
- [x] [Review][Patch] Character-offset math in `karaokeSpokenWordCount` assumes exactly one space
      between words, but the denominator (`text.length`) counts every literal character — a double
      space, tab, or non-breaking space (plausible in LLM-generated narration; not normalized
      anywhere upstream in `_split_into_caption_lines`) desyncs the two, silently drifting the
      highlight timing ahead of the real narration. Confirmed independently by Blind Hunter, Edge
      Case Hunter, and Scale & Load Hunter (non-dismissible per `docs/SCALE-CONTRACT.md` §2 — a
      `silent-wrong-result` finding). **Fixed**: both the proportional target and the word split now
      use a whitespace-normalizing (`\s+`) split, and the target is computed against the
      reconstructed single-space-joined length rather than raw `text.length`, so the numerator and
      denominator can never desync regardless of source whitespace.
      [`apps/web/src/components/player/CaptionOverlay.tsx`]
- [x] [Review][Patch] The "unspoken" remainder `<span>` has no muted styling at all (no
      `className`) — it renders visually identical to the base caption text, so the karaoke effect
      only ever adds an underline to spoken words and never dims what's ahead, contradicting AC3's
      explicit "rendered muted" requirement. Confirmed by direct code inspection (Acceptance
      Auditor). **Fixed**: `text-neutral-100/50` added, mirroring this file's own existing
      opacity-suffix convention. [`apps/web/src/components/player/CaptionOverlay.tsx`]
- [x] [Review][Patch] Test coverage gaps identified by Test Coverage + AC Completeness layers (all
      independently re-verified, arithmetic and suite results confirmed correct where checked):
      negative-progress/negative-position boundary untested; the exact word-boundary equality case
      (`endOffset === targetChars`) untested; no component-level test for the fully-elapsed
      (progress ≈ 1) boundary mirroring the existing progress-0 test; no single-word-line test; no
      multi-line integration test confirming karaoke state resets correctly across a line
      transition. **Fixed**: 13 new tests added covering all five gaps plus the two review-fix
      regressions (NaN handling, whitespace-desync). Full frontend suite: 93 files / 1181 tests (was
      1168), zero regressions. [`apps/web/src/__tests__/components/player/CaptionOverlay.test.tsx`]

## References

- [Source: docs/dev2-sprint-tracker.md — BR-4] — the task itself, its stated dependency
- [Source: docs/stories/2-61-caption-sync-real-timestamps.md] — BR-3, the line-selection story this
  one extends (same `captionLines` prop, same `hasRealTimestamps` gate)
- [Source: docs/stories/4-29-caption-lines-schema-pipeline.md] — confirms line-level timing is
  final/sufficient (no word-level timing to wait for) and names this feature explicitly
