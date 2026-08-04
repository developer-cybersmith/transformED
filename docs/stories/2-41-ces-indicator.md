---
baseline_commit: cd776fe
---

# Story 2.41: CES Indicator Component (S3-04)

Status: done

## Story

As a student in an active lesson,
I want a subtle, glanceable sense of how engaged I appear to the tutor,
so that I'm not blindsided by an intervention, without the display becoming a distracting score I obsess over.

**Source:** `docs/dev2-sprint-tracker.md` §12, S3-04 (Sprint 3, P2). Epic: `docs/bmad/epics/epic-2-lesson-player.md` names `CESIndicator` as a Lesson Player component; not in that doc's own component table (added later in the Sprint 3 tracker), but it slots into the same `components/player/` family.

**Dependency note:** `ces_update` is already live on the wire per the frozen `packages/shared/types/ws.ts` contract (`{ session_id, ces, window_index }`), but `useLessonSocket.ts`'s handler currently no-ops it with the comment `// Not emitted by any live path yet (Dev 3 owns it); no-op.` This story turns that no-op into a real dispatch, the same way Story 2-40 (S3-03) did for `tutor_intervene`. Whether Dev 3's CES formula and Dev 4's tutor FSM actually *emit* a real `ces_update` in production is out of scope here — this story must work correctly against a manually-dispatched or mocked message regardless, matching this codebase's "build against the frozen contract, flip to real later" pattern.

**Branch note:** built from `main` at `cd776fe`, which does **not** yet include Story 2-40's `activeIntervention` store field or its `useLessonSocket.ts`/`Player.tsx` changes (those live on `sprint3/s3-03-tutor-intervention-card` / `sprint3-master`, not yet merged to `main`). This story must not assume 2-40's code exists — implement independently, following the same *pattern*, not the same diff. Expect a trivial, non-conflicting merge when both land in `sprint3-master` (different fields, same file, same shape of change).

## Acceptance Criteria

1. **AC-1** — New `cesScore: number | null` field + `setCesScore(score: number | null)` action added to `player.machine.ts`, following the exact pattern of the existing `tutorState`/`setTutorState` pair. Initial value `null`. Reset to `null` in `loadLesson()`'s state reset block (same place `tutorState` resets to `'IDLE'`) so a fresh lesson never inherits a stale score from a previous one.
2. **AC-2** — `useLessonSocket.ts`'s `case 'ces_update':` calls `usePlayerStore.getState().setCesScore(msg.payload.ces)` instead of no-op'ing, guarded the same way the sibling `state_change` case is guarded (`msg.payload?.session_id === sid`) — a stale/foreign-session update must not overwrite the current score. This path must never touch `status` or any playback field — it only ever calls `setCesScore`.
3. **AC-3** — New `CESIndicator.tsx` (`apps/web/src/components/player/`), self-contained (reads `cesScore` + `status` from `usePlayerStore` directly, no props). Renders `null` when `cesScore` is `null` **or** `status !== 'PLAYING'` — checked on every render (render-level guard, not just at receipt time), so the indicator disappears immediately if `status` changes away from `PLAYING` (e.g. into `QUIZ`) even without a new WS message.
4. **AC-4** — Shows a **qualitative label only**, never the raw float: `cesScore < 0.4` → `"Low"`, `0.4 <= cesScore <= 0.7` → `"Engaged"`, `cesScore > 0.7` → `"Focused"`. The raw `cesScore` number must never appear in the rendered DOM text (verify with a test that greps rendered text for a decimal pattern and finds none). This mirrors the same "never show a raw score" convention already established for CES/teach-back on `SessionReport.tsx` (S2-10 tracker note).
5. **AC-5** — Small and non-intrusive: max 40px in either dimension (a colored dot or a subtle progress arc), positioned in a player corner that doesn't collide with the existing tier badge (`top-3 left-3`) or `TutorInterventionCard`'s corner (`top-24 right-4`, once 2-40 lands) — use `top-3 right-3` or similar, distinct from both.
6. **AC-6** — Updates on every `ces_update` receipt; no client-side smoothing/debouncing beyond simply re-rendering with the latest value — Dev 3's CES formula already owns any smoothing server-side, this component just displays whatever it's told.
7. **AC-7** — Tests: the store's new field/action (default `null`, `setCesScore` sets it, `loadLesson()` resets it to `null`), the component's full visibility/label matrix (hidden when `null`, hidden when `status !== 'PLAYING'` even with a non-null score, hides immediately on a `status` change away from `PLAYING`, correct label per each of the three bands including the exact `0.4`/`0.7` boundary values), and `useLessonSocket.ts`'s dispatch on a real `ces_update` message (assert `cesScore` actually changed to the real value, plus the session-id guard rejecting a foreign-session update — per `docs/DEFECT-REGISTER.md` binding rule 2, not just "the mock was called"). Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean.

## Tasks / Subtasks

- [x] Task 1 (AC: 1): Add `cesScore`/`setCesScore` to `player.machine.ts`; reset in `loadLesson()`.
  - [x] 1.1 RED: test asserting default `null`, action sets the field, `loadLesson()` resets it to `null`.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 2): Wire `useLessonSocket.ts`'s `ces_update` case to dispatch into the store, with the same `session_id` guard as `state_change`.
  - [x] 2.1 RED: test that a `ces_update` server message for the current session sets `cesScore`; a message for a different `session_id` is ignored; no playback/status action is ever called from this path.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 3, 4, 5): Build `CESIndicator.tsx` — render-level guard, qualitative label mapping, ≤40px corner placement.
  - [x] 3.1 RED: tests for the full visibility/label matrix (null → hidden, `status !== 'PLAYING'` → hidden even with a score, status change away from PLAYING hides immediately, each band's label, boundary values at exactly 0.4 and 0.7).
  - [x] 3.2 GREEN: implement.
- [x] Task 4 (AC: 6): Mount `<CESIndicator />` in `Player.tsx`.
  - [x] 4.1 RED: `Player.test.tsx` assertion that the component is present in the tree and updates on a `cesScore` change.
  - [x] 4.2 GREEN: implement.
- [x] Task 5 (AC: 7): Full suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

### Review Findings

- [x] [Review][Patch] **Resolved by user decision:** shrink `CESIndicator` to a fixed 40×40px colored badge; the qualitative label moves to a native `title` tooltip (shown on hover/focus) instead of permanently visible text, resolving the AC-5 (≤40px) vs AC-4 (visible label) conflict. Added a real size assertion (`w-10 h-10` class present). [apps/web/src/components/player/CESIndicator.tsx]
- [x] [Review][Patch] No validation of the `ces` payload value — a malformed/NaN/out-of-range value silently resolves to "Focused" (the most reassuring, worst-case-wrong default) instead of being rejected [apps/web/src/hooks/useLessonSocket.ts:44-50, apps/web/src/components/player/CESIndicator.tsx (bandFor)]
- [x] [Review][Patch] No `window_index` ordering guard — an out-of-order/delayed `ces_update` for the same session can overwrite a newer score with a stale one [apps/web/src/hooks/useLessonSocket.ts:44-50]
- [x] [Review][Patch] Stale `cesScore` persists across a PLAYING → QUIZ/TEACH_BACK → PLAYING cycle — the old score/band reappears instantly on return to PLAYING, before any fresh `ces_update` arrives [apps/web/src/stores/player.machine.ts (enterQuiz)]
- [x] [Review][Patch] No test verifies `data-band` maps to the correct color — a swapped `BAND_COLORS`/`BAND_LABELS` mapping would pass every existing test [apps/web/src/__tests__/components/player/CESIndicator.test.tsx]
- [x] [Review][Defer] No `cancelled` guard on `handleServerMessage` — a message from an already-torn-down socket instance can still mutate global store state after the hook has moved to a new session [apps/web/src/hooks/useLessonSocket.ts:31-72] — deferred, pre-existing gap shared by every case in this switch (same class as Story 2-40's identical deferred finding), not unique to this diff
- [x] [Review][Defer] No accessibility affordances (aria-live/role=status, color-only band cues) [apps/web/src/components/player/CESIndicator.tsx] — deferred, tracked separately as a dedicated future accessibility pass (S4-04), same treatment as Story 2-40's identical finding

## Dev Notes

### What NOT to do

- Do NOT render the raw `cesScore` float anywhere, in text, `title`, `aria-label`, or a `data-*` attribute a test might accidentally treat as "not really showing it" — the hard constraint is the number never reaches the DOM in human-readable form. (A `data-band="focused"`-style attribute for testability is fine, matching S3-03's `data-variant` pattern — that's not the raw score.)
- Do NOT touch `status`, pause audio, or call any playback-affecting store action from this component or from the `ces_update` WS case.
- Do NOT add client-side smoothing, rolling averages, or debounce logic — display exactly what the server sends, whenever it sends it.
- Do NOT gate visibility only at receipt time — AC-3 explicitly requires a render-level guard so a `status` change away from `PLAYING` hides the indicator immediately without needing a new WS message (same pattern Story 2-40 used for its `TEACH_BACK` guard).
- Do NOT assume Story 2-40's `activeIntervention`/`TutorInterventionCard` code exists in this branch's `player.machine.ts`/`useLessonSocket.ts`/`Player.tsx` — it doesn't yet (see Branch note above). Add this story's field/case/mount independently; don't try to "extend" code that isn't there.

### Testing standards

Follow `CheckingInTransition.test.tsx`'s pattern (`apps/web/src/__tests__/components/player/`): `usePlayerStore.setState(...)` to drive state directly, `act()` around every state change. For the "never shows the raw score" AC, assert on the rendered text content directly (e.g. a regex like `/\d\.\d/` should NOT match anything in the container) rather than only checking for the presence of the qualitative label — a test that only checks the label appears would pass even if the raw number were *also* rendered alongside it. Per `docs/DEFECT-REGISTER.md` binding rule 2, the `useLessonSocket.ts` dispatch test must assert the actual store state changed, not merely that a mock function was invoked with no shape check.

### References

- [Source: docs/dev2-sprint-tracker.md §12, S3-04 — full spec: colored dot/arc, ≤40px, qualitative label, hidden outside PLAYING]
- [Source: packages/shared/types/ws.ts — `CesUpdateMessage` (frozen contract: `{ session_id, ces, window_index }`), do not modify]
- [Source: apps/web/src/hooks/useLessonSocket.ts — the `ces_update` no-op case this story replaces, and the `state_change` case's `session_id === sid` guard to mirror]
- [Source: apps/web/src/stores/player.machine.ts — `tutorState`/`setTutorState` as the pattern to mirror for `cesScore`/`setCesScore`; `loadLesson()`'s reset block]
- [Source: apps/web/src/components/player/CheckingInTransition.tsx — closest existing precedent: store-driven, render-level-guarded overlay component]
- [Source: apps/web/src/components/player/Player.tsx:191-200 — tier badge occupies `top-3 left-3`; pick a non-colliding corner]
- [Source: docs/dev2-sprint-tracker.md's S2-10 note — "never show a raw score" convention already established for CES/teach-back elsewhere in this codebase]
- [Source: docs/stories/2-40-tutor-intervention-card.md — sibling Sprint 3 story, same "build against frozen contract, flip to real later" pattern, not yet merged to `main` as of this story's baseline]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-04 | Story created per S3-04 in `docs/dev2-sprint-tracker.md`. Branch `sprint3/s3-04-ces-indicator` off `main`. | Dev 2 |
| 2026-08-04 | Implemented all 5 tasks, TDD (RED confirmed before each GREEN). Full `apps/web` suite: 56 files / 598 tests passing. `tsc --noEmit` clean. `eslint` clean on every touched file (3 pre-existing `useLessonSocket.ts` disable-directive warnings, unrelated, same as Story 2-40). Status → review. | Dev 2 |
| 2026-08-04 | 3-agent adversarial code review. 1 decision resolved by user (fixed 40×40 badge, title tooltip), 4 patches applied, 2 deferred, 5 dismissed. Full suite 56 files / 610 tests passing, `tsc --noEmit` clean, `eslint` clean. Status → done. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Read `useLessonSocket.ts`, `player.machine.ts`, and `Player.tsx` fresh from this branch's `main` baseline (deliberately did NOT assume Story 2-40's unmerged `activeIntervention` code existed, per the story's own Branch note) before writing anything.
- `player.machine.ts`: added `cesScore`/`setCesScore` mirroring the existing `tutorState`/`setTutorState` pair exactly; reset alongside `tutorState` in `loadLesson()`'s state block.
- `useLessonSocket.ts`: replaced the `ces_update` no-op with a `session_id`-guarded dispatch (`msg.payload?.session_id === sid`), mirroring the `state_change` case's existing guard — a stale/foreign-session update is silently ignored rather than overwriting the current score.
- `CESIndicator.tsx`: new component, store-driven with a render-level guard (hidden when `cesScore` is `null` OR `status !== 'PLAYING'`, recomputed every render — same pattern as `TutorInterventionCard`'s `TEACH_BACK` guard in Story 2-40). Three-band label mapping (`< 0.4` Low, `0.4-0.7` inclusive Engaged, `> 0.7` Focused) via a small `bandFor()` helper; `data-band` attribute for testability, never the raw float. Positioned `top-3 right-3` to avoid colliding with the tier badge (`top-3 left-3`).
- `Player.tsx`: mounted `<CESIndicator />` next to `CheckingInTransition`, no props, no other changes.
- Test for "never renders the raw numeric score" explicitly checks both `textContent` (regex for a decimal pattern) and `innerHTML` (exact string), per the story's own Testing Standards note about not trusting a label-only check.

### Completion Notes

- All 5 tasks complete, all ACs (1-7) satisfied.
- Full `apps/web` suite: 56 files, 598 tests, all passing (17 new: 4 in `player.machine.test.ts`, 2 in `useLessonSocket.test.ts` — plus 1 pre-existing no-op case removed from an `it.each` since `ces_update` is no longer a no-op — 11 in the new `CESIndicator.test.tsx`, 1 in `Player.test.tsx`).
- `tsc --noEmit`: clean. `eslint`: clean on every touched file.
- Verified this story's code does not assume or depend on Story 2-40's unmerged `activeIntervention`/`TutorInterventionCard` changes — built and tested entirely against this branch's actual `main` baseline. Expect a trivial merge into `sprint3-master` alongside 2-40 (different store fields/WS cases, same files, non-overlapping edits).

### File List

- `apps/web/src/stores/player.machine.ts` (MODIFIED — added `cesScore`/`setCesScore`; reset in `loadLesson()`)
- `apps/web/src/hooks/useLessonSocket.ts` (MODIFIED — `ces_update` case now dispatches into the store instead of no-op'ing, with a `session_id` guard)
- `apps/web/src/components/player/CESIndicator.tsx` (NEW — the component itself)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — mounts `<CESIndicator />`)
- `apps/web/src/__tests__/stores/player.machine.test.ts` (MODIFIED — new `cesScore`/`setCesScore` describe block; fixture reset updated)
- `apps/web/src/__tests__/hooks/useLessonSocket.test.ts` (MODIFIED — removed `ces_update` from the no-op `it.each`; new dedicated dispatch + foreign-session tests; fixture reset updated)
- `apps/web/src/__tests__/components/player/CESIndicator.test.tsx` (NEW — full visibility/label/raw-score-never-shown test suite)
- `apps/web/src/__tests__/components/player/Player.test.tsx` (MODIFIED — new mount-presence test)

### Review Round (2026-08-04) — 3-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor)

1 decision-needed resolved, 4 patches applied, 2 deferred (see `docs/stories/deferred-work.md`), 5 dismissed as noise (bare-string session_id auth is the existing WS trust model not a new gap, an unverifiable-from-diff-alone comment claim, untested layout-overlap consistent with existing codebase norms, a false test-inconsistency claim — the async-wait pattern in the foreign-session test matches the pre-existing `state_change` test's identical pattern — and out-of-range boundary tests folded into the validation-guard fix instead of standing alone).

**Decision resolved by user:** AC-5 (≤40px in either dimension) directly conflicted with AC-4 (visible qualitative label) — a dot+visible-text pill cannot fit "Engaged" within 40px width. User chose: shrink to a fixed 40×40px badge, move the label to a native `title` tooltip (hover/focus-revealed, also read by screen readers) instead of permanently-visible text.

**Fixes applied:**
- `useLessonSocket.ts`: `ces_update` now validates `ces` is a finite number in `[0, 1]` before storing (a malformed/NaN/out-of-range value is silently rejected instead of resolving to the falsely-reassuring "Focused" band via `bandFor()`'s comparison semantics), and tracks `window_index` per effect-run to reject an out-of-order/delayed frame for the same session.
- `CESIndicator.tsx`: redesigned to the fixed-40×40px/title-tooltip shape (see decision above); added a real `w-10 h-10` size assertion.
- `player.machine.ts`: `enterQuiz()` now also clears `cesScore` — the score/band no longer reappears stale when `PLAYING` resumes after quiz/teach-back.
- New test: `data-band` ↔ color-class consistency, so a swapped `BAND_COLORS`/`BAND_LABELS` mapping can't silently pass.

Full `apps/web` suite after the review round: **56 files, 610 tests** (598 + 12 net new), all passing. `tsc --noEmit` clean. `eslint` clean on every touched file (same 3 pre-existing, unrelated `useLessonSocket.ts` warnings as Story 2-40).
