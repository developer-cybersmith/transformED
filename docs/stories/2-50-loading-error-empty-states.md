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

- [x] Task 1 (AC: 1, 2, 5): Add error state + Retry to `ProfileTab.tsx`.
  - [x] 1.1 RED: write failing tests for rejected-fetch error UI, Retry re-fetch, and post-unmount safety.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 1, 2, 5): Add error state + Retry to `LearningTab.tsx`.
  - [x] 2.1 RED / 2.2 GREEN (same shape as Task 1).
- [x] Task 3 (AC: 1, 2, 5): Add error state + Retry to `PrivacyTab.tsx`.
  - [x] 3.1 RED / 3.2 GREEN (same shape as Task 1).
- [x] Task 4 (AC: 4, 5): Add the zero-lessons empty-state message to `dashboard/page.tsx`.
  - [x] 4.1 RED: write failing test for the exact AC-4 visibility conditions.
  - [x] 4.2 GREEN: implement.
- [x] Task 5 (AC: 6): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

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

- `ProfileTab.tsx`/`LearningTab.tsx`/`PrivacyTab.tsx` each gained an `error` boolean and a `mountedRef` (replacing the old per-effect `cancelled` local, since Retry needs the same unmount guard outside the mount effect). The mount effect calls a `fetchX()` `useCallback` whose body is only the `settingsService.getX().then(onSuccess, onFailure)` call — no synchronous `setState` before the promise, since that call chain (effect → function → synchronous `setState`) trips this repo's `react-hooks/set-state-in-effect` ESLint rule. The Retry button instead calls a separate `retryLoadX()` callback that synchronously resets `error`/loading state (a real event-handler call, not an effect, so the rule doesn't apply) and then calls the same `fetchX()`.
- `dashboard/page.tsx` gained a single inline empty-state block, gated on `error == null && !continueLearning && recentLessons.length === 0`, placed above the existing grid — deliberately not touching `ContinueLearningCard`/`RecentLessons` themselves, since their `return null` behavior is correct and shared by other future callers.
- Scoped via a read-only 8-flow audit (fork agent) before writing ACs — confirmed 6 of 8 flows already correct from prior sprint work, so no changes were made to Books, Upload, Onboarding, the lesson player, Session Report, or auth forms.

### Completion Notes

- All 5 tasks complete, all ACs (1–6) satisfied.
- `NotificationsTab.tsx`/`useNotificationPreferences.ts` and `AccountTab.tsx` confirmed untouched, per Dev Notes — independently re-verified by reading `useNotificationPreferences.ts` directly (its `loadPreferences()` already has a correct `try/catch` + `finally`, contradicting the initial audit's guess that it shared the same bug).
- Full `apps/web` suite (post-review-round): 80 files / 1002 tests, all passing. `tsc --noEmit` clean. `eslint` on all touched files: 0 errors (1 pre-existing, unrelated warning on `ProfileTab.tsx`'s avatar `<img>` tag, not introduced by this story).
- See **Senior Developer Review** below — an 8-agent adversarial review found 2 real defects (both fixed) and several test-coverage gaps (5 of the 6 fixed via new tests); the rest were triaged as not-actioned with reasons.

### File List

- `apps/web/src/components/settings/tabs/ProfileTab.tsx` (MODIFIED — added `error`/`isFetching` state, `mountedRef`, `fetchProfile`/`retryLoadProfile`, error UI with Retry; review round: `fetchProfile` takes an `isStale()` closure checked alongside `mountedRef`, and the mount effect keeps its own per-invocation `cancelled` local — closes a React Strict Mode dev-only staleness gap the shared ref alone couldn't catch)
- `apps/web/src/components/settings/tabs/LearningTab.tsx` (MODIFIED — same shape as ProfileTab, including the review-round `isStale()` fix)
- `apps/web/src/components/settings/tabs/PrivacyTab.tsx` (MODIFIED — same shape as ProfileTab, including the review-round `isStale()` fix)
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` (MODIFIED — added zero-lessons empty-state block, gated on no error + no continueLearning + empty recentLessons; review round: also gated on `user != null` from `useAuth()`, closing a pre-auth-resolved flash where a returning user with real lessons would briefly see "No lessons yet")
- `apps/web/src/__tests__/components/settings/tabs/ProfileTab.test.tsx` (MODIFIED — 3 new tests from initial implementation + 1 review-round test: Retry button disappears while a retry is in flight)
- `apps/web/src/__tests__/components/settings/tabs/LearningTab.test.tsx` (MODIFIED — same 4 tests)
- `apps/web/src/__tests__/components/settings/tabs/PrivacyTab.test.tsx` (MODIFIED — same 4 tests)
- `apps/web/src/__tests__/app/dashboard/page.test.tsx` (MODIFIED — 4 tests from initial implementation + 2 review-round tests: `continueLearning`-present negative case, and the pre-auth `user: null` case; `useAuth` mock converted from a static object to a resettable `vi.fn()` to support the new test)

## Senior Developer Review (AI)

**Date:** 2026-08-24
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers (8 layers, per CLAUDE.md's BMAD Code Review Gate):** Blind Hunter (diff-only, no project context), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec), Scale & Load Hunter (diff + repo access + `docs/SCALE-CONTRACT.md`), Story Quality, Test Coverage, AC Completeness, Process Integrity.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | High | Edge Case Hunter (independently reproduced by reading `useDashboard.ts`/`AuthContext.tsx` directly) | `useDashboard()`'s SWR key is `null` until `user` resolves, so `isLoading` reports `false` (not "still resolving") during the pre-auth window on every page load — the new AC-4 empty-state condition was all-true in that window, so a **returning user with real lessons** would briefly see "No lessons yet — upload a PDF..." before their real data even had a chance to be requested. | Fixed — `dashboard/page.tsx` now also imports `useAuth()` and gates the empty-state block on `user != null`. New test: "does not show the zero-lessons empty-state before auth has resolved". |
| 2 | Medium | Edge Case Hunter | The refactor from the original per-effect `let cancelled = false` (isolated per invocation) to a shared `mountedRef` broke React Strict Mode's dev-only double-invoke safety net: a phantom mount's own fetch could resolve *after* the real remount had already flipped `mountedRef.current` back to `true`, incorrectly passing the guard and applying stale data/error state from the phantom invocation. Not a production bug (Strict Mode double-invoke is dev-only), but a genuine regression from the original code's correctness property. | Fixed in all 3 tabs — `fetchX` now takes an `isStale()` closure, checked in addition to (not instead of) `mountedRef`; the mount effect keeps its own per-invocation `cancelled` local (closing the Strict Mode gap) while `retryLoadX()` passes `() => false` (real clicks only need the broader `mountedRef` check). |
| 3 | Medium (corroborated 6/8 — Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load Hunter, Story Quality, Test Coverage, AC Completeness) | Multiple | AC-2's "guard against overlapping requests" had zero test coverage across all 3 tabs. Independently confirmed (Scale & Load Hunter, Acceptance Auditor) that the actual protection mechanism is the Retry button *unmounting* the instant it's clicked (branch switches from the error view to the loading view) — not the `disabled={isFetching}`/`disabled={isLoading}` prop, which can never evaluate true while the button is rendered (error and in-flight are mutually exclusive states) and is therefore unreachable dead code. Functionally safe, but untested and not matching its own described mechanism. | Added one test per tab asserting the Retry button is absent (not just disabled) while a retry is in flight, then resolves to real data — this tests the actual mechanism instead of the non-functional `disabled` prop. |
| 4 | Low | Acceptance Auditor, Blind Hunter | AC-4's dashboard test set covered 3 of 4 required negative conditions (`isLoading`, `error`, `recentLessons` non-empty) but never tested "`continueLearning` present AND `recentLessons` empty" — the other half of the AND-gated suppression logic. | Added the missing test. |
| 5 | Low, single-sourced (Test Coverage) | Test Coverage | A successful fetch resolving with `data: null` (as opposed to an error) would render the loading state forever with no distinction from "still fetching" — no test covers it. | Not actioned — currently type-unreachable: `getUserProfile`/`getLearningPreferences`/`getPrivacySettings` (`apps/web/src/mocks/api/settings.ts`) return `ApiResponse<T>` with a non-nullable `data: T`, and always resolve with a real object today. Would need revisiting if a future real backend endpoint's contract ever allowed a null/absent success payload — at which point that would itself be an API contract bug, not a UI gap. |
| 6 | Low, single-sourced (Blind Hunter), refuted by Scale & Load Hunter + Acceptance Auditor's independent reachability analysis | Blind Hunter | Retry button's `disabled={isFetching}`/`disabled={isLoading}` prop is unreachable dead code (see finding #3). | Not actioned — harmless; removing it would add complexity for no functional gain since the real protection (button unmount) is already covered by finding #3's new test. Left as defensive redundancy. |
| 7 | Low, single-sourced (Blind Hunter) | Blind Hunter | New error/empty-state text has no `role="alert"`/`aria-live` region, so screen-reader users get no notification of the async state change. | Not actioned — real accessibility observation, but not one of this story's ACs, and no existing `aria-live` convention was found elsewhere in the reviewed files to match. Logged here as a follow-up, not a blocker. |
| 8 | Low, single-sourced (Blind Hunter), refuted | Blind Hunter | Claimed `ProfileTab.test.tsx`'s new tests were missing `getProfileMock.mockReset()`, unlike the sibling tab test files. | Not a defect — `ProfileTab.test.tsx`'s existing top-level `beforeEach` already calls `getProfileMock.mockReset()` before every test (confirmed by reading the file); Blind Hunter had no project context and couldn't see it. |
| 9 | Low, single-sourced (Blind Hunter) | Blind Hunter | ~90 lines of near-identical fetch/retry/`mountedRef` scaffolding duplicated 3 times across the tabs, rather than factored into a shared hook. | Not actioned — deliberate, per this story's own Dev Notes ("Do NOT introduce a shared `useSettingsResource`-style hook") and CLAUDE.md's anti-premature-abstraction rule; independently confirmed as a considered decision (not an oversight) by the Process Integrity reviewer. |
| 10 | Low | Edge Case Hunter | No fetch timeout — a genuinely hung request (dropped connection, no server response) leaves the component on "Loading…" forever with no Retry affordance at all, since the button only renders once the promise actually settles. | Not actioned — pre-existing characteristic unchanged by this story (the original code had the identical unbounded-hang property, just with no error path at all once it did settle); out of scope for a story whose job was adding the missing failure branch, not a timeout layer. |

### Non-issues independently re-verified

- All "What NOT to do" boundaries (no touching `NotificationsTab`/`useNotificationPreferences`/`AccountTab`, no shared hook, no skeleton redesign) independently confirmed respected by Process Integrity, Acceptance Auditor, and Edge Case Hunter via direct file reads and `git diff`/`git log` scoped to those paths.
- Story-First Gate and Sprint Task Branch Rule confirmed followed by Story Quality and Process Integrity via `git log` — story-only commit (`13f9092`) precedes the implementation commit (`fdff369`), branch name matches the required pattern, cut cleanly from `main`.
- Scale & Load Hunter returned `[]` (no findings) after independently verifying the Retry concurrency claim by tracing the actual state machine, not trusting the story's own Scale & Load section — concluded the design is structurally safe (stronger than a typical `inFlightRef` pattern, since only one request can ever be in flight at all, not merely one "accepted").
- AC-1, AC-3, AC-5(a/b/c) × 3 tabs, and all "What NOT to do" items independently reproduced as SATISFIED by Acceptance Auditor by running the actual suite/`tsc`/`eslint`, not by trusting the Dev Agent Record's prose claims.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-24 | Story created after a read-only 8-flow audit found most flows already solid; scoped to the 2 real gaps found (settings tabs' unhandled GET rejections, dashboard's silent empty-state collapse). Branch `sprint4/s4-10-loading-error-empty-states` off `main`. | Dev 2 |
| 2026-08-24 | Implemented all 5 tasks (TDD, RED then GREEN). 8-agent adversarial review found 2 real defects (both fixed: a pre-auth-resolved empty-state flash, and a React Strict Mode staleness regression from the shared `mountedRef`) and 3 test-coverage gaps (all fixed with new tests); 5 further findings triaged not-actioned with reasons. Final: 80 files / 1002 tests passing, `tsc --noEmit` and `eslint` clean. See Senior Developer Review above. | Dev 2 |
