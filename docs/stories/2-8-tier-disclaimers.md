---
baseline_commit: "8a99789a5d6ab4bf0d0f5ebcab81fde5f01676a8"
---

# Story 2-8: Tier Disclaimers

Status: review

## Story

As a student choosing a Learner Mode tier,
I want to see a short inline warning on the Balanced and Refresher cards explaining their trade-off,
so that I understand what I'm giving up before I commit to a faster/lighter lesson.

## Context

This is Sprint 2 task **S2-08** from `docs/dev2-sprint-tracker.md` §11 — the second of four **Learner Mode** tasks (S2-07–S2-10). Original tracker sketch: *"Tier disclaimers (T2 time-deficit, T3 refresher-only; T1 none) — inline warning style."*

This story directly extends **S2-07** (`docs/stories/2-7-mode-selection-screen.md`, status `done`), which deliberately left the disclaimer slot unbuilt for this story to add (see S2-07's "What NOT to do": *"Keep `ModeSelection.tsx`'s current props/shape easy to extend... but don't build the disclaimer UI preemptively either"*).

**Scope boundary (explicit, do not exceed):** this story only adds the disclaimer copy/UI to the existing 3 cards. It does **not**:
- wire the selected tier into any backend call (**S2-09** — still no tier field in `POST /api/content/lessons`)
- add a tier badge to the player or session report (**S2-10**)
- change the cards' click-to-select behavior, focus management, focus-visible styling, or the `'selecting-mode'` screen's cancel/reset logic — all of that is already correct as of S2-07's review-patch pass and must not regress

**Branch:** `sprint2/s2-8-tier-disclaimers`, branched from `feature-learner-mode` (not `main`, not `sprint2-master`) — because `feature-learner-mode` already has S2-07's `ModeSelection.tsx`/`learnerMode.ts` merged in, which this story needs to extend. Same convention confirmed with the user for S2-07. When done, this task branch (kept local) merges into `feature-learner-mode`, which alone gets pushed.

### What's already there to build on (read directly from the current files, not assumed)

- `apps/web/src/types/learnerMode.ts` — exports `LearnerTier` (`'deep' | 'balanced' | 'refresher'`), `LearnerTierOption` interface (`{ id, label, description }`), and `LEARNER_TIER_OPTIONS` (the canonical, ordered array: deep, balanced, refresher). No `disclaimer` field exists yet.
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx` — renders `LEARNER_TIER_OPTIONS.map(...)` as 3 `<button>` cards, each showing `option.label` (`<h4>`) and `option.description` (`<p>`). Also (from S2-07's review-patch pass): a `firstCardRef` that autofocuses the first card on mount, and `focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20` on every card — do not touch either of these.
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx` — 6 existing passing tests: 3 cards render with label+description (1), each card's `onSelect` fires correctly (3), focus-visible ring present on every card (1), first card autofocuses on mount (1). None of these assert on disclaimer content today, so none should need to change — only new tests are added.
- No shared "Alert"/"Warning" UI component exists anywhere in `apps/web/src/components/ui/` (confirmed by directory listing) — this codebase doesn't have a reusable `<Alert>` primitive. Build the disclaimer as a small inline block directly in `ModeSelection.tsx`, following the visual language already used for status/warning icons elsewhere in this codebase (`lucide-react` icons + Tailwind color utilities — e.g. `AlertCircle` for the error state in `UploadFlow.tsx`). Use `AlertTriangle` from `lucide-react` (already a project dependency) for the disclaimer icon, with amber tones (`amber-50`/`amber-100`/`amber-700`) — there is no existing amber "warning" component elsewhere in this codebase to match exactly, so this establishes the pattern; keep it simple (icon + one line of text in a lightly-tinted rounded box), don't over-design it.

## Acceptance Criteria

1. **`LearnerTierOption` gains an optional `disclaimer` field** in `apps/web/src/types/learnerMode.ts`: `disclaimer?: string;`. Existing `LearnerTier`/`LEARNER_TIER_OPTIONS` ordering and the other 2 fields (`label`, `description`) are unchanged.
2. **Per-tier disclaimer copy, exactly:**
   - `deep`: no `disclaimer` field (omitted entirely, not an empty string) — Deep shows no disclaimer.
   - `balanced`: a one-sentence **time-deficit** warning — copy must communicate that content may be trimmed/condensed to fit the time-boxed format (exact wording is the dev's call, but must include the time-constraint trade-off explicitly, not just restate the existing `description`).
   - `refresher`: a one-sentence **refresher-only** warning — copy must communicate that this assumes prior mastery / is not a first-pass lesson (again, distinct from the existing `description`, not a restatement).
3. **`ModeSelection.tsx` renders the disclaimer inline, warning-styled, only when present:**
   - When `option.disclaimer` is set, render it inside the card below the description, visually distinguished from the description (icon + tinted background — not just plain text), using `AlertTriangle` from `lucide-react`.
   - When `option.disclaimer` is `undefined` (the `deep` case), render nothing extra — no empty warning box, no icon.
4. **No regression to S2-07's existing behavior:**
   - Clicking a card still calls `onSelect(tier.id)` exactly once, same as before — the disclaimer is not itself clickable/interactive and must not intercept or stop the card's own `onClick`.
   - Focus-visible ring and mount-autofocus-first-card behavior (from S2-07's review-patch pass) are unchanged.
   - All 6 existing `ModeSelection.test.tsx` tests continue to pass unmodified.
5. **Tests — `ModeSelection.test.tsx` additions:**
   - Deep's card renders no disclaimer element (assert the balanced/refresher disclaimer text is not present within the Deep card, or more simply: assert exactly 2 disclaimer elements exist in the whole render, not 3).
   - Balanced's card shows its disclaimer text.
   - Refresher's card shows its disclaimer text.
6. **No changes anywhere outside `learnerMode.ts` / `ModeSelection.tsx` / `ModeSelection.test.tsx`** — specifically, `UploadFlow.tsx` and its tests are untouched (the disclaimer is entirely `ModeSelection`'s concern; `UploadFlow` just renders `<ModeSelection onSelect={handleTierSelect} />` and doesn't need to know disclaimers exist).

## Tasks / Subtasks

- [x] Task 1: Extend the tier type/data (AC: #1, #2)
  - [x] 1.1 Add `disclaimer?: string` to `LearnerTierOption` in `apps/web/src/types/learnerMode.ts`
  - [x] 1.2 Add the `balanced`/`refresher` disclaimer copy; leave `deep` without the field
- [x] Task 2: Render the disclaimer in `ModeSelection.tsx` (AC: #3, #4)
  - [x] 2.1 Write failing tests first (RED) — Deep has no disclaimer, Balanced/Refresher each show their own disclaimer text; re-run the 6 existing tests to confirm no regression
  - [x] 2.2 Implement the conditional disclaimer block (GREEN)
- [x] Task 3: Full verification (AC: #5, #6)
  - [x] 3.1 Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean (0 new warnings)
  - [x] 3.2 Confirm `UploadFlow.tsx`/`UploadFlow.test.tsx` are untouched (git diff shows no changes to either)
- [x] Task 4: Tracker update
  - [x] 4.1 Mark S2-08 in `docs/dev2-sprint-tracker.md` as done, update the Sprint 2 dashboard row and header

## Dev Notes

### Files this story touches

- `apps/web/src/types/learnerMode.ts` (MODIFY — add `disclaimer?: string` field + 2 copy strings)
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx` (MODIFY — conditional disclaimer render)
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx` (MODIFY — 3 new tests added)
- `docs/dev2-sprint-tracker.md` (MODIFY — mark S2-08 done on completion)

### What NOT to do

- Do NOT touch `UploadFlow.tsx` or `UploadFlow.test.tsx` — this story is entirely contained within `ModeSelection.tsx` and its type/test files.
- Do NOT wire disclaimers into any tier-selection analytics/backend call — no such call exists yet (S2-09).
- Do NOT change the card's click behavior, focus-visible styling, or mount-autofocus from S2-07 — the disclaimer is purely additive content inside the existing card markup.
- Do NOT build a generic, reusable `<Alert>`/`<Warning>` component for this — no such abstraction exists elsewhere in the codebase yet, and one 2-variant inline block doesn't justify introducing one. Keep it local to `ModeSelection.tsx`.
- Do NOT give `deep` an empty-string or whitespace `disclaimer` — the field must be entirely absent (`undefined`) so the "no disclaimer" branch is unambiguous or an accidental empty box.

### Project Structure Notes

Purely additive to two already-existing files plus their test file. No conflicts with `packages/shared` frozen contracts. No interaction with `UploadFlow.tsx`'s state machine (`'idle'`/`'selecting-mode'`/`'processing'`/etc.) — that file isn't touched at all by this story.

### References

- [Source: docs/dev2-sprint-tracker.md#S2-08 — Tier Disclaimers] (original sketch)
- [Source: docs/stories/2-7-mode-selection-screen.md] (the story this one directly extends; see its "What NOT to do" section for why the disclaimer slot was deliberately left unbuilt)
- [Source: apps/web/src/types/learnerMode.ts] (file to extend with the new field)
- [Source: apps/web/src/components/dashboard/upload/ModeSelection.tsx] (file to extend with the disclaimer render)
- [Source: apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx] (existing 6 tests that must keep passing unmodified)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Task 2 RED confirmed: 3 new tests failed before implementation — `Refresher shows a refresher-only disclaimer` and `renders exactly 2 disclaimer elements total` failed as expected (no disclaimer markup existed yet); `Deep shows no disclaimer` passed trivially even pre-implementation (nothing to fail), which is expected and correct for a negative assertion. All 10 tests (6 existing + 4 new) GREEN after implementing the conditional disclaimer block.

### Completion Notes List

- All 4 tasks completed; every AC satisfied.
- Added `disclaimer?: string` to `LearnerTierOption`; `deep` has no `disclaimer` key at all (not an empty string), `balanced`/`refresher` each have distinct one-sentence copy that doesn't restate their existing `description`.
- `ModeSelection.tsx` renders the disclaimer via a `data-testid="tier-disclaimer"` block (icon + tinted background) only when `option.disclaimer` is truthy — used a real DOM query (`querySelectorAll`) rather than text-matching alone to assert exactly 2 render (not 3), which is a stronger regression guard than text assertions alone.
- Did not build a reusable `Alert`/`Warning` component, per the story's explicit instruction — the block is local to `ModeSelection.tsx`.
- Confirmed via `git diff --stat` that `UploadFlow.tsx` and `UploadFlow.test.tsx` have zero changes — this story never touched them.
- No regression: all 6 pre-existing `ModeSelection.test.tsx` tests (3-card render, 3 click-to-select tests, focus-visible ring, mount-autofocus) still pass unmodified.

### File List

**Files MODIFIED:**
- `apps/web/src/types/learnerMode.ts` — added `disclaimer?: string` to `LearnerTierOption`; added disclaimer copy for `balanced`/`refresher`
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx` — added `AlertTriangle` import and a conditional disclaimer block per card
- `apps/web/src/__tests__/components/dashboard/upload/ModeSelection.test.tsx` — added 4 new tests (Deep has none, Balanced/Refresher each show theirs, exactly 2 disclaimer elements total)
- `docs/dev2-sprint-tracker.md` — S2-08 marked done, Sprint 2 dashboard row updated

### Change Log

- 2026-07-14: Story created — Sprint 2 Learner Mode task 2 of 4 (S2-08), branch `sprint2/s2-8-tier-disclaimers` off `feature-learner-mode`.
- 2026-07-14: All 4 tasks implemented in RED→GREEN order; 4 new tests (10 total in `ModeSelection.test.tsx`); full `apps/web` suite 341/341 passing; `tsc --noEmit` clean; `eslint` clean (0 new warnings); confirmed `UploadFlow.tsx`/its tests untouched; story marked `review`.
