# Story 3-53 — D88 slide overflow + D90 caption overlay

**Branch:** `sprint3/s3-53-d88-d90-player-ui-fixes` (from `main`).
**Trigger:** two real, already-diagnosed defects found live this session by a real stakeholder
watching a real generated lesson play. Assigned D88 and D90 (IDs pre-allocated by the
coordinator).

## Ownership note — flagging for Dev 2's visibility

Per `docs/CLAUDE.md` §21, `apps/web/src/app/lesson/[id]/layout.tsx` and every file under
`apps/web/src/components/player/` are normally **Dev 2's** territory (Next.js, custom player).
Both defects below are implemented directly in this story because the stakeholder handed over
exact, already-diagnosed root causes and fixes at the moment they were found live, rather than
being routed through Dev 2's own backlog first. **This is not a claim on Dev 2's territory** —
it is flagged here explicitly so Dev 2 sees it on their next pass over these files and can
review, adjust styling conventions, or fold the caption toggle enhancement (noted below) into
their own player work as they see fit.

## D88 — slide content overflows the screen

### Context

Real stakeholder report, this session, watching a real generated lesson: on a segment with tall
bullet content, the slide area grows past the browser viewport instead of being clipped to it,
and the whole page scrolls off-screen — breaking the intended full-screen lesson player
experience.

### Root cause (confirmed by reading the code, not re-derived)

Two compounding issues:

1. `apps/web/src/app/lesson/[id]/layout.tsx` uses `min-h-screen` — a *minimum* height that is
   free to grow past the viewport when content inside is tall — instead of a height fixed to the
   viewport.
2. `apps/web/src/components/player/Player.tsx`'s slide-area container
   (`<div className="relative flex-1">`, line 191) is missing `min-h-0`. This is the classic CSS
   flexbox trap: a flex item's default `min-height` is `auto`, meaning it will not shrink below
   its content's natural height even inside a `flex-1` parent. With a tall slide, the container
   grows to fit the content instead of being clipped to its allotted flex space.

`apps/web/src/components/player/SlideRenderer.tsx` already implements the *correct* internal
scroll behavior (`overflow-y-auto overscroll-y-contain`, confirmed present at line 67) — it never
gets the chance to engage because nothing above it in the tree is ever actually bounded to a real
height. Confirmed by reading both files directly before writing this story.

### The fix

1. `layout.tsx`: `min-h-screen` → `h-dvh` (dynamic viewport height — correct over `h-screen` on
   mobile browsers where the visible viewport changes as browser chrome shows/hides; matches this
   being a full-screen lesson player, not a scrolling page).
2. `Player.tsx`: add `min-h-0` to the `relative flex-1` slide-area container (line 191) so the
   flex item can actually shrink to its allotted space, letting `SlideRenderer`'s own
   `overflow-y-auto` engage as designed.

`SlideRenderer.tsx` is **not** touched — its overflow handling is already correct; this fix is
purely about giving it a bounded parent height to work within.

## D90 — no captions, student cannot read what's being narrated

### Context

Same stakeholder report, same session: the player has narration audio but nothing on screen
shows what is being said, so a student who needs (or wants) to read along has no way to.

### Root cause

Confirmed zero caption/subtitle/transcript UI code exists anywhere in `apps/web/src` — grepped
`caption|subtitle|transcript` (case-insensitive) across the whole tree before writing this story.
The only hits are unrelated: `TeachbackSubmission`'s typed-text field explicitly documented as
"no transcript, no audio, no STT" (`apps/web/src/types/assessment.ts:47` and its test), which is
a different feature (teach-back input) with a comment that happens to use the word "transcript."

The full narration script for the current segment already exists in the lesson package at
`segment.narration.script` — a real, non-empty `string` on every real segment
(`packages/shared/types/lesson.ts`'s `Narration.script: string`). `Player.tsx` already has
`const segment = lesson.segments[currentSegmentIndex] ?? null` in scope (line 183).

Word-level or sentence-level *synced* captions are **not** possible yet — the Sarvam TTS
integration deliberately returns empty word-level timestamps (a separate, larger follow-up, not
this story). This fix is deliberately scoped to a simple, always-visible, non-synced caption
panel showing the current segment's full script text, updating whenever the segment changes
(segment already changes reactively via existing player-store state).

### The fix

New component `apps/web/src/components/player/CaptionOverlay.tsx`, mounted inside `Player.tsx`'s
slide area (`relative flex-1` container), anchored to the bottom, alongside where
`AvatarOverlay`/`SlideRenderer` are rendered.

- **Props:** `script: string | null` — `Player.tsx` passes `segment?.narration.script ?? null`.
- **Renders nothing** when `script` is null or empty — mirrors `SlideRenderer.tsx`'s own
  `SlideImage` "render nothing when there is nothing to show" pattern (its early
  `if (!imageUrl && !fallbackUrl) return null;`), for consistency with this codebase's
  conventions.
- **Styling** matches this directory's existing overlay conventions: dark, semi-transparent
  background with backdrop blur for legibility over any slide image
  (`bg-black/60 backdrop-blur-sm`, matching the existing buffering-indicator overlay in
  `Player.tsx`), `text-neutral-*` body text, internally scrollable
  (`overflow-y-auto max-h-*`) so a long script doesn't push past its own box, readable font size.
  No new visual language invented.
- **No toggle/hide control** in this first pass — always visible whenever a segment is active,
  matching exactly what was asked for ("so we can read what it is narrating"). A show/hide
  toggle is a reasonable near-term enhancement; explicitly **out of scope** for this fix.

## What this does NOT do

- No word-level/sentence-level synced captions — the data (word timestamps) does not exist yet;
  a separate, larger follow-up.
- No changes to `AudioTimeline.tsx`, `SlideRenderer.tsx`'s internals, or any player component
  other than `Player.tsx` (mounting `CaptionOverlay` + the `min-h-0` fix) and the two files named
  for D88 (`layout.tsx`, `Player.tsx`).
- No caption show/hide toggle — noted above as a future enhancement, not built here.
- `docs/DEFECT-REGISTER.md` and `docs/dev1-tracker.md` are **not** touched by this story — a
  coordinator registers both defects centrally after this branch is reviewed.

## Scale & Load

Both fixes are pure client-side UI rendering — no new network calls, no new reads/writes, no new
per-lesson/per-user budget, no server-side component at all. Answering the six questions with
`N/A` and the reason for each, per `docs/SCALE-CONTRACT.md`:

1. **Unit of work & range.** N/A — no new unit of work. `CaptionOverlay` renders a string already
   present in the already-fetched, already-size-bounded `LessonPackage` object (narration script
   length is itself already capped upstream by the pipeline's narration character cap — this
   component does not add or remove any bound, it displays existing bounded data).
2. **Fixed budgets vs variable input.** N/A — no new fixed budget introduced. The caption panel
   is internally scrollable (`overflow-y-auto`) specifically so a long-but-already-capped script
   is never silently clipped; the panel grows to a max height and scrolls rather than truncating.
3. **Scope of limits.** N/A — no limit introduced; purely a rendering concern local to one
   mounted component instance per player session.
4. **Unbounded reads/writes.** N/A — no reads or writes at all; `script` is a prop passed down
   from already-loaded state.
5. **Inherited caps re-derived.** N/A — no cap inherited or reused.
6. **Concurrency / check-then-act safety.** N/A — no check-then-act sequence; a pure render of
   already-resolved React state, re-rendering reactively whenever `currentSegmentIndex` changes,
   same as every other segment-scoped element in `Player.tsx`.

## Verification

- `CaptionOverlay.test.tsx` (new, alongside `SlideRenderer.test.tsx`'s existing conventions in
  `apps/web/src/__tests__/components/player/`):
  - renders the segment's narration script text when `script` is a non-empty string.
  - renders nothing (empty container / `null`) when `script` is `null`.
  - renders nothing when `script` is an empty string (`''`).
- D88 is a pure CSS/className change on two files with no existing dedicated test file for
  `layout.tsx` (a Next.js layout, not typically unit-tested in this repo) — verified by reading
  the rendered className output directly (`h-dvh` present on the layout's root div, `min-h-0`
  present alongside `relative flex-1` on `Player.tsx`'s slide-area div) plus a class-presence
  assertion added to `Player.test.tsx` if the existing test file's conventions support it.
- `npm run type-check` and `npm run lint` clean on touched files.
- Full `apps/web` test suite (`npm run test`) — zero pre-existing tests broken.


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
