---
baseline_commit: e34159c
---

# Story 2.40: TutorInterventionCard Component (S3-03)

Status: review

## Story

As a student whose attention or comprehension is dipping mid-lesson,
I want a brief, non-blocking card to tell me what the tutor noticed and nudge me back in,
so that I get re-engaged without my audio/lesson progress ever pausing or resetting.

**Source:** `docs/dev2-sprint-tracker.md` §12, S3-03 (Sprint 3, P0). Epic: `docs/bmad/epics/epic-2-lesson-player.md` (`TutorInterventionCard` is explicitly named in its Component Specification, line 54).

**Dependency note:** `tutor_intervene` is already live on the wire per the frozen `packages/shared/types/ws.ts` contract, but `useLessonSocket.ts:41-43` currently no-ops it with the comment `// Sprint 3 — TutorInterventionCard consumes this; no-op for now.` This story is what turns that no-op into a real dispatch. Whether Dev 4's tutor FSM actually *sends* a real `tutor_intervene` message in production is out of scope here (D30/D29 track that) — this story must work correctly against a manually-dispatched or mocked message regardless of whether the real backend is emitting them yet, matching this codebase's established "build against the frozen contract, flip to real later" pattern (e.g. Story 2-39, S1-05 AvatarOverlay).

## Acceptance Criteria

1. **AC-1** — New `activeIntervention: TutorInterveneMessage['payload'] | null` field + `setActiveIntervention(payload | null)` action added to `player.machine.ts`, following the exact pattern of the existing `tutorState`/`setTutorState` pair. Initial value `null`. Reset to `null` in `loadLesson()`'s state reset block (same place `tutorState` resets to `'IDLE'`) so a fresh lesson never inherits a stale intervention from a previous one.
2. **AC-2** — `useLessonSocket.ts`'s `case 'tutor_intervene':` (line 41-43) calls `usePlayerStore.getState().setActiveIntervention(msg.payload)` instead of no-op'ing. A new message **replaces** any currently-active one (no queue) — matches the backend's own max-3-per-session / 2-min-cooldown throttling (CLAUDE.md §10), so overlap is rare and simple replacement is the correct default.
3. **AC-3** — New `TutorInterventionCard.tsx` (`apps/web/src/components/player/`), self-contained (reads `activeIntervention` + `status` from `usePlayerStore` directly, no props), following the `CheckingInTransition.tsx` pattern (store-driven, edge-triggered visibility, own local timer). Renders `null` when `activeIntervention` is `null` **or** `status === 'TEACH_BACK'` — this is a render-level guard checked on every render, not just at receipt time, so a card already showing must vanish immediately if `status` transitions to `TEACH_BACK` while it's up.
4. **AC-4** — Three visual variants keyed on `activeIntervention.type` (`InterventionType = 'distraction' | 'confusion' | 'fatigue'` from `ws.ts`): `distraction` = warm amber, `confusion` = cool blue, `fatigue` = soft/neutral. Card shows `activeIntervention.message` verbatim (backend-authored copy — do not add, rewrite, or truncate it).
5. **AC-5** — Slides in from the right using `framer-motion` (already a dependency — see `CheckingInTransition.tsx` for the project's existing usage pattern), 200ms ease transition. Positioned as a corner/edge overlay (e.g. `absolute top-24 right-4 z-30`), **not** a full-screen overlay like `CheckingInTransition` — it must not block or dim the slide/audio underneath. `pointer-events` limited to the card itself so the rest of the player stays interactive behind it.
6. **AC-6** — Dismisses two ways: (a) a visible dismiss button calling `setActiveIntervention(null)`, (b) an auto-dismiss timer at exactly 30,000ms from when the card became visible, calling the same action. Timer is cleared on unmount and on manual dismiss (no double-fire, no stale timeout setting `null` after a newer intervention has already replaced it — guard by checking the effect's own closed-over payload reference before clearing, same category of bug `CheckingInTransition.tsx`'s review-fix comment at line 26-29 addresses).
7. **AC-7** — Audio/playback is never paused, never queried, never touched by this component. No `usePlayerStore` action that affects `status`, `audioPositionMs`, or playback is ever called from this component or from the `tutor_intervene` case in `useLessonSocket.ts`.
8. **AC-8** — Mounted in `Player.tsx` alongside `CheckingInTransition`/`AvatarOverlay` inside the `relative flex-1` slide container (near line 306-313), self-contained with no props, consistent with those two.
9. **AC-9** — Tests: the store's new field/action (default `null`, reset on `loadLesson`, replace-not-queue on second `setActiveIntervention` call), the component's full state matrix (hidden when `null`, hidden when `status === 'TEACH_BACK'` even with a non-null payload, correct variant styling per `type`, message text rendered verbatim), both dismiss paths (button click, 30s timer via `vi.useFakeTimers()`), timer cleanup on unmount and on replacement, and `useLessonSocket.ts`'s dispatch on a real `tutor_intervene` message (assert `setActiveIntervention` was called with the exact payload — not just "the mock was called," per `docs/DEFECT-REGISTER.md` binding rule 2). Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean.

## Tasks / Subtasks

- [x] Task 1 (AC: 1): Add `activeIntervention`/`setActiveIntervention` to `player.machine.ts`; reset in `loadLesson()`.
  - [x] 1.1 RED: test asserting default `null`, action sets/replaces the field, `loadLesson()` resets it to `null`.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 2, 7): Wire `useLessonSocket.ts`'s `tutor_intervene` case to dispatch into the store.
  - [x] 2.1 RED: test that a `tutor_intervene` server message calls `setActiveIntervention` with the exact payload, and that no playback/status action is ever called from this path.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 3, 4, 5): Build `TutorInterventionCard.tsx` — render-level guard, three variants, framer-motion slide-in, corner positioning.
  - [x] 3.1 RED: tests for the full visibility matrix (null → hidden, TEACH_BACK-while-active → hidden, each `type` → correct variant class, message text rendered).
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 6): Dismiss button + 30s auto-dismiss timer, with correct cleanup on unmount/replacement.
  - [x] 4.1 RED: tests for button dismiss, timer-based dismiss at exactly 30000ms (fake timers), no dismiss before 30000ms, timer doesn't fire against a message it no longer matches after a replacement.
  - [x] 4.2 GREEN: implement.
- [x] Task 5 (AC: 8): Mount `<TutorInterventionCard />` in `Player.tsx`.
  - [x] 5.1 RED: `Player.test.tsx` assertion that the component is present in the tree.
  - [x] 5.2 GREEN: implement.
- [x] Task 6 (AC: 9): Full suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT make `TutorInterventionCard` a full-screen overlay like `CheckingInTransition` — it must never block the slide/audio visually or via `pointer-events`. This is the one deliberate visual departure from that component's pattern; everything else about the store-driven/edge-triggered/local-timer approach should be copied.
- Do NOT touch `status`, pause audio, or call any playback-affecting store action from this component or from the `tutor_intervene` WS case — AC-7 is a hard constraint straight from the tracker spec ("Audio does NOT pause for interventions").
- Do NOT queue multiple interventions — replace-on-new is the deliberate, simplest-correct behavior given the backend's own throttling (max 3/session, 2-min cooldown per CLAUDE.md §10). Don't build a queue/stack unless a future story asks for it.
- Do NOT gate visibility only at the moment the WS message arrives — the AC explicitly requires a render-level guard so a `status` transition into `TEACH_BACK` *while a card is already showing* hides it immediately, without needing a new WS message.
- Do NOT invent new copy for the three intervention types — `activeIntervention.message` is backend-authored (pre-generated at lesson build time per CLAUDE.md's tutor state machine section: "Intervention messages are PRE-GENERATED at lesson build time... No GPT call at intervention time"). This component only supplies the visual chrome (color/icon/position) per `type`, never the text.

### Testing standards

Follow `CheckingInTransition.test.tsx`'s exact pattern (`apps/web/src/__tests__/components/player/`): `usePlayerStore.setState(...)` to drive state directly, `vi.useFakeTimers()` + `vi.advanceTimersByTime()` for the auto-dismiss timer, `act()` around every state change. Per `docs/DEFECT-REGISTER.md` binding rule 2, the `useLessonSocket.ts` dispatch test must assert the actual store state changed (or that `setActiveIntervention` was called with the real payload), not merely that a mock function was invoked with no shape check.

### References

- [Source: docs/dev2-sprint-tracker.md §12, S3-03 — full spec, AC checklist, three-variant table]
- [Source: docs/bmad/epics/epic-2-lesson-player.md — TutorInterventionCard component spec (line 54), Definition of Done item "TutorInterventionCard renders on receipt of WebSocket intervention message" (line 151)]
- [Source: packages/shared/types/ws.ts — `TutorInterveneMessage`, `InterventionType` (frozen contract, do not modify)]
- [Source: apps/web/src/hooks/useLessonSocket.ts:41-43 — the no-op this story replaces]
- [Source: apps/web/src/components/player/CheckingInTransition.tsx — closest existing precedent: store-driven, edge-triggered, local-timer overlay component, including its own review-fix comment about stale-timer cleanup]
- [Source: apps/web/src/stores/player.machine.ts — `tutorState`/`setTutorState` as the pattern to mirror for `activeIntervention`/`setActiveIntervention`; `loadLesson()`'s reset block]
- [Source: apps/web/src/components/player/Player.tsx:306-313 — mount point alongside `CheckingInTransition`/`AvatarOverlay`]
- [Source: CLAUDE.md — Tutor State Machine guard rules (§10): "Intervention messages are PRE-GENERATED at lesson build time... NEVER interrupt mid-TEACH_BACK"]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-03 | Story created per S3-03 in `docs/dev2-sprint-tracker.md`, cross-referenced against `docs/bmad/epics/epic-2-lesson-player.md`. Branch `sprint3/s3-03-tutor-intervention-card` off `main`. | Dev 2 |
| 2026-08-03 | Implemented all 6 tasks, TDD (RED confirmed before each GREEN). Full `apps/web` suite: 56 files / 598 tests passing. `tsc --noEmit` clean (after clearing a stale, gitignored `.next/` build-cache artifact from an unrelated branch). `eslint` clean on every touched file (removed one unused `useRef` import found during lint; the 3 pre-existing `useLessonSocket.ts` disable-directive warnings verified unrelated via `git stash`). | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Read `useLessonSocket.ts`, `player.machine.ts`, `Player.tsx`, and the closest existing precedent (`CheckingInTransition.tsx` + its test) fully before writing anything, per the story's own Dev Notes.
- `player.machine.ts`: added `activeIntervention`/`setActiveIntervention` mirroring the existing `tutorState`/`setTutorState` pair exactly; reset alongside `tutorState` in `loadLesson()`'s state block.
- `useLessonSocket.ts`: replaced the `tutor_intervene` no-op with a direct `usePlayerStore.getState().setActiveIntervention(msg.payload)` call, matching this file's existing imperative-`getState()` pattern used elsewhere in the same handler (e.g. the `wsSendControl` wiring) rather than adding a new top-level selector for a plain event-handler function.
- `TutorInterventionCard.tsx`: new component, store-driven and edge-triggered like `CheckingInTransition`, but deliberately a corner toast (not full-screen) per AC-5/AC-7 — non-blocking is the one hard visual departure from that precedent. Three variants keyed on `InterventionType` via a `data-variant` attribute (chosen over asserting raw Tailwind classes, for test robustness). The 30s auto-dismiss effect closes over the specific `activeIntervention` reference and re-checks it against the live store value before clearing — this is what makes the replace-not-queue behavior safe: a stale timer from a replaced intervention cannot clear the new one (same defect class `CheckingInTransition.tsx`'s own review-fix comment documents).
- `Player.tsx`: mounted `<TutorInterventionCard />` next to `CheckingInTransition`/`AvatarOverlay`, no props, no other changes.

### Completion Notes

- All 6 tasks complete, all ACs (1-9) satisfied.
- Full `apps/web` suite: 56 files, 598 tests, all passing (11 new: 5 in `player.machine.test.ts`, 1 in `useLessonSocket.test.ts` — plus 1 pre-existing no-op case removed from an `it.each` since `tutor_intervene` is no longer a no-op — 11 in the new `TutorInterventionCard.test.tsx`, 1 in `Player.test.tsx`).
- `tsc --noEmit`: clean. `eslint`: clean on every touched file.
- Encountered and cleared one environment issue unrelated to this story: a stale, gitignored `.next/dev/types/validator.ts` referencing a route (`pending-approval/page.js`) from a different branch's build cache was failing `tsc --noEmit`; confirmed it wasn't caused by this story's changes (not a tracked file, per `apps/web/.gitignore:17`) before deleting it and letting it regenerate clean.
- Confirmed via `git stash` that the 3 `eslint` "unused eslint-disable directive" warnings in `useLessonSocket.ts` (lines 58, 93, 109 — far from this story's one-line change at line ~41) pre-exist on `main` and are not introduced by this story.

### File List

- `apps/web/src/stores/player.machine.ts` (MODIFIED — added `activeIntervention`/`setActiveIntervention`; reset in `loadLesson()`)
- `apps/web/src/hooks/useLessonSocket.ts` (MODIFIED — `tutor_intervene` case now dispatches into the store instead of no-op'ing)
- `apps/web/src/components/player/TutorInterventionCard.tsx` (NEW — the component itself)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — mounts `<TutorInterventionCard />`)
- `apps/web/src/__tests__/stores/player.machine.test.ts` (MODIFIED — new `activeIntervention`/`setActiveIntervention` describe block; fixture reset updated)
- `apps/web/src/__tests__/hooks/useLessonSocket.test.ts` (MODIFIED — removed `tutor_intervene` from the no-op `it.each`; new dedicated dispatch test; fixture reset updated)
- `apps/web/src/__tests__/components/player/TutorInterventionCard.test.tsx` (NEW — full visibility/variant/dismissal test suite)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED — new mount-presence test)
