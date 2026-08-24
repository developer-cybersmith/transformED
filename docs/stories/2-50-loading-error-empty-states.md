---
baseline_commit: b17966012385ebe6d8e26532bc3c0bb0d9c40175
---

# Story 2.50: Loading + Error + Empty States for All Flows (S4-10)

Status: ready-for-dev

## Story

As a student,
I want every page that fetches my data to show a real error message with a way to recover if the fetch fails, instead of an infinite loading spinner or a silently blank section,
so that a transient backend hiccup doesn't strand me on a page that looks broken with no way forward except a manual page refresh I have no reason to think of.

**Source:** Master tracker Sprint 4 item "Loading + error + empty states for all flows" (`docs/master-tracker.md`, Dev 2 section) — this had no dedicated story or S4-number in `docs/dev2-sprint-tracker.md` before now. Assigned **S4-10**.

**Scoping note — this is NOT a sprawling rewrite.** A read-only audit of all 8 major flows (dashboard, books/library, upload, onboarding, lesson player, session report, settings, auth forms) before writing this story found that **most flows already have solid loading/error/empty handling** from prior sprint work (Story 1-7, S1-13's audit, S2-27). Re-doing work that's already correct is explicitly against this codebase's "no premature abstraction / no redundant work" convention. Two concrete, reproducible gaps survived the audit — this story fixes exactly those two, not a page-by-page rewrite.

**Current state, confirmed by reading every file this story touches:**

- **Gap 1 (primary, real defect — infinite loading with no recovery):** `apps/web/src/components/settings/tabs/ProfileTab.tsx` (lines 13-21), `LearningTab.tsx` (lines 13-23), and `PrivacyTab.tsx` (lines 13-23) each call `settingsService.get*().then(...)` in their mount `useEffect` with **no `.catch()` at all**. If the promise rejects (network failure, 500, expired session), the component's `profile`/`preferences`/`settings` state stays `null` forever, `isLoading` (where it exists) never flips to `false`, and the tab is stuck on its "Loading…" text permanently — no error message, no retry affordance, and no console log even for debugging. This is an **unhandled promise rejection** in production code.
  - By contrast, the same 3 files' **update** calls (`updatePreference`/`updateSetting`) already have `.catch()` with optimistic-rollback (from the S1-13 audit pass) — the pattern exists in this codebase for writes but was never applied to the initial reads in these 3 files.
  - **Confirmed NOT affected:** `NotificationsTab.tsx` uses `useNotificationPreferences()` (`apps/web/src/hooks/useNotificationPreferences.ts`), whose `loadPreferences()` (lines 105-137) already has a `try/catch` that degrades to `DEFAULT_PREFERENCES` on read failure and always sets `isLoading` false in a `finally` — this hook is correct today and this story does not touch it. `AccountTab.tsx` has no data fetch at all (static UI + a modal) — not affected.
- **Gap 2 (secondary, cosmetic — not a broken flow):** `apps/web/src/app/(dashboard)/dashboard/page.tsx` renders `ContinueLearningCard` (line 45) and `RecentLessons` (line 68) unconditionally once `isLoading` is `false`. Both components (`ContinueLearningCard.tsx` line 12-14, `RecentLessons.tsx` line 24) return `null` when there's no data, so a brand-new user with zero lessons sees two collapsed sections with no explanation — just blank vertical gaps. **Note: this is NOT a missing-CTA bug** — `QuickActions.tsx` (rendered unconditionally on the same page) already has a real "Upload PDF" CTA linking to `/upload`, so a new user is never actually stuck with zero path forward. The gap is purely that the collapsed sections give no feedback that "empty" is the expected, successful state rather than something not having loaded.
- **Confirmed already correct, not touched by this story** (per the audit): Books/Library list + detail, Upload flow (`UploadFlow.tsx`'s explicit `idle/processing/completed/error` state machine), Onboarding (`OnboardingFlow.tsx`'s `Phase` type including `"error"`), the lesson player (`PlayerLoader.tsx`'s `LessonGeneratingState`/`LessonErrorState`), Session Report (`SessionReport.tsx`'s `LoadingState`/`ErrorState`), and the sign-in/sign-up forms' inline error handling.

## Acceptance Criteria

1. **AC-1** — `ProfileTab.tsx`, `LearningTab.tsx`, and `PrivacyTab.tsx` each gain an `error` boolean/state alongside their existing `profile`/`preferences`/`settings` state. The mount-effect fetch adds a `.catch()` (or `try/catch` around the `await`, matching whichever of the two idioms the file already uses elsewhere) that sets `error: true` and — where the file doesn't already have one — sets `isLoading: false`. The existing `cancelled` guard must wrap the catch path too, exactly as it already wraps the success path, so an unmounted component never sets state after the fact.
2. **AC-2** — Each of the 3 tabs renders a real error state when `error` is `true` (and data is still `null`): a short message ("Couldn't load your \<profile/preferences/privacy settings\> — check your connection and try again." or equivalent per-tab wording) plus a **Retry** button that re-runs the same fetch. Retry must guard against overlapping requests — while a retry is in flight, a second click is a no-op (disable the button or an in-flight ref check), matching the concurrency-safety convention already used elsewhere in this codebase (e.g. `useNotificationPreferences`'s `inFlightRef`).
3. **AC-3** — No change to the existing "Loading…" text/styling for the ordinary in-flight case, and no change to any working success-path rendering. This story only adds the previously-missing failure branch — it does not redesign the loading UI into a skeleton (that's a separate, lower-priority visual-consistency item, not a defect, and out of scope here to avoid scope creep on what is a bug-fix story).
4. **AC-4** — `dashboard/page.tsx`: when `isLoading` is `false`, `error` is `null`, `dashboardData?.continueLearning` is falsy, AND `dashboardData?.recentLessons` is empty, render a single small inline empty-state message in place of where `ContinueLearningCard`/`RecentLessons` would go (e.g. "No lessons yet — upload a PDF to get your first lesson started."). This must NOT appear while `isLoading` is `true`, when `error` is set (the existing error banner already covers that case), or when the user has at least one lesson in either `continueLearning` or `recentLessons`.
5. **AC-5** — Tests: each of the 3 settings tabs gets a new test asserting (a) a rejected fetch shows the error message + Retry button, not an infinite loading state; (b) clicking Retry re-invokes the service call and, on success, renders the real data; (c) a rejected fetch after unmount does not throw or warn (`cancelled` guard holds). `dashboard/page.tsx` (or its test file) gets a new test asserting the empty-state message renders only under the exact AC-4 conditions and not otherwise.
6. **AC-6** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file. `useNotificationPreferences.ts` and `AccountTab.tsx` are unmodified (confirmed already correct — see Dev Notes).

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** one page-mount fetch of one user's own settings row (Profile/Learning/Privacy) or one user's dashboard payload. Always exactly one row per fetch, scoped by the authenticated user's own ID — there is no "N items" dimension here at all, unlike a list/pagination endpoint.
2. **Fixed budgets vs. variable input:** none introduced. This story adds a failure branch to an existing single-row fetch; it does not add pagination, batching, or any new size-bounded field.
3. **Scope of every limit:** N/A — no new limit introduced. The underlying reads are already per-user (RLS-scoped), unaffected by this story.
4. **Unbounded reads/writes:** none. Still a single-row read per tab, same as before this story.
5. **Inherited caps re-derived:** N/A — no cap carried over; this is new failure-handling code, not a resized existing budget.
6. **Concurrent check-then-act safety:** the one genuine concurrency surface this story adds is the **Retry button** — a student could click it more than once before the in-flight request resolves. AC-2 requires this be guarded (disable-while-in-flight or an in-flight ref, matching `useNotificationPreferences`'s existing `inFlightRef` convention) so two overlapping retries can't race and leave stale state after both settle.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 2, 5): Add error state + Retry to `ProfileTab.tsx`.
  - [ ] 1.1 RED: write failing tests for rejected-fetch error UI, Retry re-fetch, and post-unmount safety.
  - [ ] 1.2 GREEN: implement.
- [ ] Task 2 (AC: 1, 2, 5): Add error state + Retry to `LearningTab.tsx`.
  - [ ] 2.1 RED / 2.2 GREEN (same shape as Task 1).
- [ ] Task 3 (AC: 1, 2, 5): Add error state + Retry to `PrivacyTab.tsx`.
  - [ ] 3.1 RED / 3.2 GREEN (same shape as Task 1).
- [ ] Task 4 (AC: 4, 5): Add the zero-lessons empty-state message to `dashboard/page.tsx`.
  - [ ] 4.1 RED: write failing test for the exact AC-4 visibility conditions.
  - [ ] 4.2 GREEN: implement.
- [ ] Task 5 (AC: 6): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT touch `useNotificationPreferences.ts` or `NotificationsTab.tsx` — confirmed already correct (degrades to defaults, logs, always clears `isLoading`). Re-implementing a fix here would be solving an already-solved problem.
- Do NOT touch `AccountTab.tsx` — no data fetch exists there.
- Do NOT introduce a shared `useSettingsResource`-style hook to de-duplicate the 3 tabs' near-identical fetch shape. Three similar small blocks is the existing, already-established pattern in this codebase (`LearningTab`/`PrivacyTab` were already structurally near-identical before this story) — per CLAUDE.md's "no premature abstraction" rule, don't introduce one now for a fourth near-copy. If a reviewer wants this extracted, that's a follow-up, not blocking this story.
- Do NOT redesign the loading state into a skeleton matching the rest of the app's `animate-pulse` convention. That's a real, separate visual-consistency observation (logged here, not actioned): every other flow in this app uses an `animate-pulse` div shaped like its content; these 3 tabs use plain centered text. It's cosmetic, not broken, and out of scope for a story whose job is fixing the missing error path.
- Do NOT treat Gap 2 (dashboard empty state) as a missing-CTA bug — `QuickActions.tsx`'s "Upload PDF" card already covers that. This AC is purely about not leaving two silently-collapsed sections with no explanation.

### Testing standards

Vitest + Testing Library, matching existing conventions in `apps/web/src/__tests__/components/settings/` (create if it doesn't yet exist a per-tab test file, following the naming of existing dashboard/player test files) and `apps/web/src/__tests__/**/dashboard` equivalents. Mock `settingsService` methods to reject for the error-path tests, matching how `useNotificationPreferences`'s own tests (if any) or other SWR-error tests in this repo simulate a rejected fetch.

### References

- [Source: docs/master-tracker.md, Dev 2 Sprint 4 section] — origin of this task, assigned S4-10 here since it had no story or tracker number before.
- [Source: apps/web/src/hooks/useNotificationPreferences.ts] — the correct-pattern reference this story's fix should match in spirit (catch, degrade, always clear loading), confirmed already correct and NOT touched by this story.
- [Source: docs/stories/2-27-library-dashboard-auto-poll.md and the 2026-07-27 App-Wide Audit (`docs/app-audit-2026-07-04.md`)] — established precedent for treating "silent mock/stale data" and "silent collapse to nothing" as real findings worth fixing, same category as this story's two gaps.

## Dev Agent Record

### Implementation Plan

_(filled in during implementation)_

### Completion Notes

_(filled in during implementation)_

### File List

_(filled in during implementation)_

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-24 | Story created after a read-only 8-flow audit found most flows already solid; scoped to the 2 real gaps found (settings tabs' unhandled GET rejections, dashboard's silent empty-state collapse). Branch `sprint4/s4-10-loading-error-empty-states` off `main`. | Dev 2 |
