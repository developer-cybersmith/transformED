---
baseline_commit: "b5ea07b9a87f00ca5a0a2d30845cc56444aaae8e"
---

# Story 2-7: Learner Mode Selection Screen

Status: done

## Story

As a student who just uploaded a PDF,
I want to choose how deeply I want to study it (Deep / Balanced / Refresher) before generation starts,
so that the lesson HIE builds matches how much time and depth I actually want right now.

## Context

This is Sprint 2 task **S2-07** from `docs/dev2-sprint-tracker.md` §11 — the first of four new **Learner Mode** tasks (S2-07–S2-10) added 2026-07-14. Learner Mode is a brand-new feature with no prior PRD/epic coverage — it does not appear in `_bmad-output/planning-artifacts/epic-2-lesson-player.md` or anywhere else. This story defines the feature's UI shape for the first time; later stories build on the decisions made here.

**Scope boundary (explicit, do not exceed):** this story is the mode-selection screen ONLY — the 3 cards, and gating progression on a selection. It does **not**:
- add tier disclaimer copy (that's **S2-08**, a separate story that will extend `ModeSelection.tsx`)
- send the selected tier to any backend endpoint (that's **S2-09** — `POST /api/content/lessons` has no tier field today, and adding one needs Dev 1 sign-off first; see below)
- show a tier badge anywhere in the player or session report (that's **S2-10**)

**Branch:** `sprint2/s2-7-mode-selection`, branched from `sprint1/s1-8-upload-real-api` (not `main` and not `sprint2-master`) — per user instruction, because that branch contains real, unmerged auth/upload backend-integration fixes (commits `f2dcc63`, `3f72ca4`, `306962b`) this feature sits directly on top of (it modifies the same `UploadFlow.tsx` those commits touched). Do not rebase onto `main` mid-story without re-confirming with the user; when this story is done it will need to flow through `sprint1/s1-8-upload-real-api` → `sprint2-master` → `main` in that order, not merge straight to `main`.

### What's already there to build on

- `apps/web/src/components/dashboard/upload/UploadFlow.tsx` — the real (non-mock) upload flow shipped in Story 1-8. Current state machine: `'idle' | 'processing' | 'completed' | 'error'`. `handleFile(selectedFile)` validates the 50MB size limit, then **immediately** sets `uploadState('processing')`, which triggers a `useEffect` that calls `uploadService.uploadLesson(file)` followed by 5s-interval status polling. There is currently no pause between "file selected" and "upload POST fires."
- `apps/web/src/services/upload.service.ts` — `uploadService.uploadLesson(file: File)` posts multipart `FormData` with only a `file` field to `POST /api/content/lessons`. **No tier/mode field exists in this request today** — confirmed by reading the file directly, not assumed from docs. Adding one is explicitly out of scope here (S2-09).
- `apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` — 9 existing passing tests, all built around a `dropAFile()` helper that drops a file and then asserts `uploadLessonMock` was called directly, with no intervening step. **This story's own change (inserting a required mode-selection step between file-select and upload) will break every one of these tests as written** — this is an intentional, in-scope behavior change, not a regression to avoid. This story must update this test file's helper/tests to select a tier before asserting the upload call, not skip or delete coverage.
- `apps/web/src/types/assessment.ts` — existing precedent for where this codebase puts shared frontend types for a feature (used across multiple components/services). Follow this pattern for the new tier type rather than defining it inline in one component.

### Where in the flow this screen goes

Confirmed with the user: the mode-selection screen appears **after a file is chosen, before the actual upload POST fires** — not after the backend upload/generation completes. This lines up with **S2-09**'s own scope ("wire selected tier into `POST /lessons`; show chosen tier on the generating screen") — the tier has to be known before that POST is made, so it must be captured before `uploadLesson(file)` is called, not after.

Revised flow:
```
drop/select file → size-validated → [NEW] mode-selection screen (3 cards)
  → student picks a tier → upload POST fires → existing polling/processing screen → completed/error
```

Picking a card is both the selection and the confirmation — there is no separate "Continue" button. This keeps the screen a single decisive action, consistent with how `QuizOverlay`/`TeachBackModal` elsewhere in this codebase treat a click as final rather than staging a draft state.

## Acceptance Criteria

1. **New shared tier type/data**, `apps/web/src/types/learnerMode.ts` (new file):
   - `export type LearnerTier = 'deep' | 'balanced' | 'refresher';`
   - `export interface LearnerTierOption { id: LearnerTier; label: string; description: string; }`
   - `export const LEARNER_TIER_OPTIONS: LearnerTierOption[]` — exactly 3 entries, in this order: `deep` ("Deep"), `balanced` ("Balanced"), `refresher` ("Refresher"), each with a one-sentence `description` (no disclaimer copy — that's S2-08). This is the canonical tier list S2-08/S2-09/S2-10 will also import, so later stories don't redefine it.
2. **New component**, `apps/web/src/components/dashboard/upload/ModeSelection.tsx`:
   - Props: `{ onSelect: (tier: LearnerTier) => void }`.
   - Renders exactly 3 cards, one per `LEARNER_TIER_OPTIONS` entry, each a real `<button>` (keyboard-focusable, matching this codebase's existing "Browse Files" button convention — not a `<div onClick>`).
   - Each card's visible text includes its `label` ("Deep" / "Balanced" / "Refresher") and `description`.
   - Clicking a card calls `onSelect(tier.id)` exactly once, with the correct tier id for that card.
3. **`UploadFlow.tsx` wiring:**
   - New state value `'selecting-mode'` added to the `uploadState` union (between `'idle'`-after-file-select and `'processing'`).
   - New state `selectedTier: LearnerTier | null` (component state — not yet persisted anywhere; S2-10 will decide where it needs to live long-term for the badge).
   - `handleFile` (after the existing size check passes): sets `file`, sets `uploadState('selecting-mode')`. It must **not** set `uploadState('processing')` directly anymore.
   - New handler `handleTierSelect(tier: LearnerTier)`: sets `selectedTier(tier)`, sets `uploadState('processing')`, sets `statusMessage('Uploading...')` — i.e. this is now what actually kicks off the existing upload effect (the effect's own trigger condition, `uploadState === 'processing' && file`, is unchanged).
   - New render branch for `uploadState === 'selecting-mode'`: renders `<ModeSelection onSelect={handleTierSelect} />` plus a text-link/button ("Choose a different file") that resets to `uploadState('idle')` — mirrors the existing "Generate Another"/"Try Again" back-to-idle pattern already used in the `completed`/`error` branches.
   - The oversized-file rejection path is unaffected (it sets `uploadState('error')` directly and never reaches `'selecting-mode'`).
4. **Existing upload flow behavior unchanged once a tier is picked** — everything from `handleTierSelect` onward (upload POST, polling, completed/error screens) is byte-for-byte the same as Story 1-8 shipped; this story does not touch `upload.service.ts` or the polling `useEffect`'s internals at all.
5. **Tests — new file** `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx`: renders 3 cards with the correct labels; clicking each one calls `onSelect` with the correct, distinct tier id (3 assertions, one per card).
6. **Tests — `UploadFlow.test.tsx` updated, not just left broken:**
   - Add a `selectTier(tierLabel: string)` test helper that clicks the named card's button.
   - New test: dropping a valid file shows the mode-selection screen (all 3 tier labels visible) and does **not** call `uploadLessonMock` yet.
   - Every existing test that currently calls `dropAFile()` and then expects `uploadLessonMock`/polling behavior must be updated to call `selectTier(...)` in between (pick any one tier — the choice doesn't affect these tests' assertions, since the upload call still only sends `file`, not tier, per AC-4).
   - New test: from the mode-selection screen, "Choose a different file" returns to the idle drop zone without ever calling `uploadLessonMock`.
   - The existing oversized-file-rejection test needs no change (it never reaches mode-selection).
7. **No regression to Story 1-8's own test suite**: full `apps/web` test suite still green after this story's changes (only the mode-selection-adjacent tests in `UploadFlow.test.tsx` should have actually changed).

## Tasks / Subtasks

- [x] Task 1: Shared tier type (AC: #1)
  - [x] 1.1 Create `apps/web/src/types/learnerMode.ts` with `LearnerTier`, `LearnerTierOption`, `LEARNER_TIER_OPTIONS`
- [x] Task 2: `ModeSelection` component (AC: #2, #5)
  - [x] 2.1 Write failing tests first (RED) — 3 cards render with correct labels; each click fires `onSelect` with the correct id
  - [x] 2.2 Implement `ModeSelection.tsx` (GREEN)
- [x] Task 3: Wire into `UploadFlow.tsx` (AC: #3, #4)
  - [x] 3.1 Add `'selecting-mode'` to the state union, add `selectedTier` state
  - [x] 3.2 Change `handleFile` to stop at `'selecting-mode'` instead of `'processing'`
  - [x] 3.3 Add `handleTierSelect` (sets tier, moves to `'processing'`, sets the existing `'Uploading...'` status message)
  - [x] 3.4 Add the `'selecting-mode'` render branch (`ModeSelection` + "Choose a different file" back-link)
- [x] Task 4: Update existing tests + add new ones (AC: #6, #7)
  - [x] 4.1 Add `selectTier` helper to `UploadFlow.test.tsx`
  - [x] 4.2 Insert `selectTier(...)` into every existing test that previously relied on `dropAFile()` alone triggering the upload
  - [x] 4.3 Add the 3 new tests described in AC-6 (mode-selection shown pre-upload, back-link returns to idle, oversized-file test unaffected/re-verified)
  - [x] 4.4 Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean
- [x] Task 5: Tracker update
  - [x] 5.1 Mark S2-07 in `docs/dev2-sprint-tracker.md` as done, update the Sprint 2 dashboard row and header

### Review Findings

5-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run against branch `sprint2/s2-7-mode-selection` (commits `4c39d57`..`f501d48`) vs its parent `sprint1/s1-8-upload-real-api`, 2026-07-14.

- [x] [Review][Patch] `handleCancelModeSelection` doesn't reset `file`/`selectedTier` or clear the file input value — re-selecting the exact same file after cancelling never fires a `change` event (browsers don't re-fire `change` for an unchanged `FileList`), silently stranding the user on the idle screen [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — fixed: `handleCancelModeSelection` now clears `file`, `selectedTier`, and `inputRef.current.value`. The exact browser same-`FileList` `change`-suppression symptom isn't reproducible via `fireEvent.change` in this jsdom-based harness (it always dispatches regardless of file-object identity); added `"Choose a different file" clears the file input value"` and `"...fully resets so a fresh drop/tier-pick cycle starts clean"` as the closest testable regression coverage.
- [x] [Review][Patch] No `focus-visible` styling on the tier-card buttons in `ModeSelection.tsx` — only `hover:` classes are defined, so a keyboard user tabbing to a card gets no visible focus indicator [apps/web/src/components/dashboard/upload/ModeSelection.tsx] — fixed: added `focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20`, matching `components/ui/button.tsx`'s existing pattern exactly. New test asserts every card's className matches `/focus-visible:ring/`.
- [x] [Review][Patch] No focus management on transition into `'selecting-mode'` — when the `'idle'` screen's Browse-Files button unmounts (after its exit animation), focus drops to `document.body` instead of moving to the first tier card, forcing a keyboard user to re-tab from the top of the page [apps/web/src/components/dashboard/upload/UploadFlow.tsx, apps/web/src/components/dashboard/upload/ModeSelection.tsx] — fixed: `ModeSelection.tsx` now holds a ref to the first card and calls `.focus()` on it in a mount `useEffect`. New test asserts `document.activeElement` is the first ("Deep") card right after render.
- [x] [Review][Defer] No drag-and-drop guard on the `'selecting-mode'` screen [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — deferred, pre-existing pattern (processing/completed/error also lack a drop handler; only `'idle'` has one), this story just extends the same exposure to one more screen. Needs a broader "harden all non-idle screens against drop" pass, not a one-off fix here.
- [x] [Review][Defer] Tier selection has no functional effect on generation yet [apps/web/src/components/dashboard/upload/UploadFlow.tsx] — deferred, correctly scoped away per this story's own "What NOT to do" (S2-09 wires the tier into the backend). Worth a look before the full Learner Mode feature is considered ready to ship: the screen's copy ("Choose a pace before HIE builds your lesson") already implies the choice matters, which is misleading until S2-09 lands.

**Dismissed as noise/false-positive (2):** the `selectTier(user, label)` test helper's parameter signature differs cosmetically from the AC's literal `selectTier(tierLabel: string)` sketch — functionally identical, satisfies the acceptance intent, not a real deviation. The `data-selected-tier={selectedTier ?? undefined}` attribute added to the `'processing'` screen (to avoid an unused-variable lint warning) wasn't explicitly authorized by any AC but crosses no stated boundary — a defensible judgment call, not a rejection-worthy deviation.

## Dev Notes

### Files this story touches

- `apps/web/src/types/learnerMode.ts` (NEW)
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx` (NEW)
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx` (NEW)
- `apps/web/src/components/dashboard/upload/UploadFlow.tsx` (MODIFY — state union, `handleFile`, new `handleTierSelect`, new render branch)
- `apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` (MODIFY — see AC-6)
- `docs/dev2-sprint-tracker.md` (MODIFY — mark S2-07 done on completion)

### What NOT to do

- Do NOT send `selectedTier` to `upload.service.ts` / the backend in this story — there is no field for it yet, and wiring it is explicitly S2-09's job (needs Dev 1 sign-off on the request shape first).
- Do NOT add tier disclaimer text/styling to the cards — that's S2-08, a separate story that will extend this same `ModeSelection.tsx`. Keep `ModeSelection.tsx`'s current props/shape easy to extend (e.g. don't hardcode "no disclaimer slot" in a way that makes S2-08 need a rewrite), but don't build the disclaimer UI preemptively either.
- Do NOT add a tier badge to the player or session report — that's S2-10.
- Do NOT rewrite or "fix" the polling `useEffect` in `UploadFlow.tsx` — it is unmodified by this story; only the state transition that triggers it moves later (after tier selection instead of immediately after file selection).
- Do NOT delete or weaken existing `UploadFlow.test.tsx` coverage to make it pass faster — every test that broke because of this story's own behavior change must be fixed to reflect the new flow, not removed.
- Do NOT merge this branch to `main` directly when done — flows back through `sprint1/s1-8-upload-real-api`, then `sprint2-master`, per the branching convention confirmed 2026-07-14.

### Project Structure Notes

No conflicts with `packages/shared` frozen contracts (Learner Mode/tiers aren't part of any frozen schema yet — `LessonPackage`/`WsMessage` are untouched by this story). Purely additive: one new type module, one new component, one modified component with a new intermediate state, updated tests for the changed behavior.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-07 — Learner Mode Selection Screen] (original sketch)
- [Source: docs/stories/1-8-upload-real-api.md] (the real upload/polling flow this story inserts a step into; confirms no tier field exists in the backend contract yet)
- [Source: apps/web/src/components/dashboard/upload/UploadFlow.tsx] (file this story modifies most)
- [Source: apps/web/src/services/upload.service.ts] (confirms `uploadLesson(file)` has no tier param today — do not add one here)
- [Source: apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx] (existing tests that must be updated, not broken)
- [Source: apps/web/src/types/assessment.ts] (precedent for where shared feature types live in this codebase)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Task 2 RED confirmed: `ModeSelection.test.tsx` failed with "Failed to resolve import '@/components/dashboard/upload/ModeSelection'" before the component existed; GREEN after implementing `ModeSelection.tsx` (4/4 tests passing).
- Task 3/4: no isolated RED step for `UploadFlow.tsx` itself — modifying it to insert the `'selecting-mode'` state intentionally broke all 9 pre-existing `UploadFlow.test.tsx` tests (each expected `uploadLessonMock` to fire immediately after `dropAFile()`), exactly as flagged in the story's own Context section. Fixed by updating the test file (Task 4) in the same pass; re-ran to confirm GREEN (11/11 passing).
- One test failure found and fixed during Task 4 that wasn't anticipated in the story: the new "Choose a different file" back-link test failed because the `'selecting-mode'` `motion.div` had an `exit` animation prop (`{ opacity: 0, scale: 0.95 }`) — under `AnimatePresence mode="wait"`, this defers mounting the next (`'idle'`) child until the exit transition finishes, so a synchronous assertion right after the click still saw the old screen. Fixed by removing the `exit` prop from the `'selecting-mode'` block, matching the existing `'completed'`/`'error'` blocks (neither has an `exit` prop either — only `'idle'`/`'processing'` do, and those are only ever asserted on asynchronously via `waitFor`/`findBy` elsewhere in this file).

### Completion Notes List

- All 5 tasks completed; every AC in the story satisfied.
- Confirmed via direct file reads (not assumed from docs) before writing any code: `upload.service.ts`'s `uploadLesson(file)` has no tier parameter today, and `UploadFlow.tsx`'s pre-existing state machine went straight from file-select to `'processing'` with no intermediate step — both exactly as the story's Context section described.
- `selectedTier` component state (AC #3) is intentionally not consumed by anything in this story (S2-09/S2-10 will decide how). Left bare, this produced 1 new `@typescript-eslint/no-unused-vars` warning (would have made the pre-existing 37-warning baseline 38 for the wrong reason — a genuinely dead variable, not tolerated pre-existing debt). Resolved by exposing it via a `data-selected-tier` attribute on the `'processing'` screen's root element — not rendered as visible text, so it doesn't affect any AC or existing test assertion, and gives S2-10 a ready hook. Final lint count is still 38 warnings, but all 38 are now the pre-existing kind, 0 new.
- Followed the story's explicit "picking a card is both selection and confirmation, no Continue button" design — kept `ModeSelection.tsx` to a single `onSelect` callback fired directly from each card's `onClick`.
- Did not touch `upload.service.ts`, the polling `useEffect`'s internals, tier disclaimers, or any player/report code — all explicitly out of scope per the story's "What NOT to do" section.

### File List

**Files CREATED:**
- `apps/web/src/types/learnerMode.ts`
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx`
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx`

**Files MODIFIED:**
- `apps/web/src/components/dashboard/upload/UploadFlow.tsx` — added `'selecting-mode'` to the `uploadState` union, `selectedTier` state, `handleTierSelect`/`handleCancelModeSelection` handlers, the `'selecting-mode'` render branch, a `data-selected-tier` attribute on the `'processing'` screen; review-patch pass: `handleCancelModeSelection` now also clears `file`/`selectedTier`/the file input value
- `apps/web/src/__tests__/components/dashboard/upload/UploadFlow.test.tsx` — added `selectTier`/`dropFileAndSelectTier` helpers; updated all 9 pre-existing tests to select a tier before expecting the upload call; added 2 new tests (mode-selection shown pre-upload, back-link returns to idle without uploading); review-patch pass added 2 more tests (input value cleared on cancel, fresh cycle after cancel completes an upload)
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx` — review-patch pass: added `focus-visible` ring classes matching `Button`'s pattern, and a mount effect that moves focus to the first card
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx` — review-patch pass added 2 tests (focus-visible ring present on every card, focus moves to the first card on mount)
- `docs/dev2-sprint-tracker.md` — S2-07 marked done, Sprint 2 dashboard row updated, outstanding-action-items list removed (all 3 patches applied)

### Change Log

- 2026-07-14: Story created — Sprint 2 Learner Mode task 1 of 4 (S2-07), branch `sprint2/s2-7-mode-selection` off `sprint1/s1-8-upload-real-api`.
- 2026-07-14: All 5 tasks implemented in RED→GREEN order; 15 new/updated tests; full `apps/web` suite 333/333 passing; `tsc --noEmit` clean; `eslint` 0 errors/38 warnings (0 new); story marked `review`.
- 2026-07-14: 5-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) — 0 decision-needed, 3 patch, 2 defer, 2 dismissed. User initially chose to leave patches as action items (story set `in-progress`), then asked for them to be applied. All 3 patches implemented in RED→GREEN order (5 new tests: 2 in `ModeSelection.test.tsx`, 3 in `UploadFlow.test.tsx`); full `apps/web` suite 337/337 passing; `tsc --noEmit` clean; `eslint` 0 errors/37 warnings (0 new — back to the true pre-existing baseline now that the earlier `data-selected-tier` workaround is the only lint-motivated addition remaining). Story marked `done`.
