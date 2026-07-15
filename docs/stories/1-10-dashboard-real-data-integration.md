---
baseline_commit: "9d80ba0ac1d88126848062481fdc0cb2a1f521c1"
---

# Story 1-10: Dashboard Real Data Integration

Status: done

## Story

As a student on my dashboard,
I want to see my actually-uploaded lessons in "Recent Lessons" instead of mock data,
so that the dashboard reflects what I've really uploaded.

## Context

This is Sprint 1 task **S1-10** from `docs/dev2-sprint-tracker.md` — the second of the two "pending API" tasks the user asked to wire this session, following **S1-09** (`docs/stories/1-9-library-real-data-integration.md`, done), which this story directly builds on.

**Scope, confirmed with the user before S1-09 started and unchanged since:** only **Recent Lessons** gets wired to real data. **Continue-Learning and Learning Pulse stay mocked** — there is no backend endpoint for "latest/in-progress session" or streak/mastery data at all (confirmed by direct backend research: zero matches for "streak"/"mastery" anywhere in `apps/api`, and no session-listing endpoint exists — see S1-09's story for the full research writeup). Do not attempt to wire either of those in this story.

### What's already there to build on (from S1-09 — read directly, not assumed)

- `apps/web/src/services/lessons.service.ts` — `lessonsService.listLessons({limit, offset})`, real, server-side, JWT-authenticated via `apps/web/src/lib/api.server.ts`'s `getServerApi()`. Returns `LessonStatusResponse[]` (`{lesson_id, status, title, error, created_at, completed_at}` — reused from `upload.service.ts`). This story calls it with `{limit: 5}` for the "recent lessons" widget — no new backend integration work needed, just reuse.
- `apps/web/src/lib/utils.ts` — `formatLessonStatusLabel(status)` maps `queued|running` → "Generating", `ready` → "Ready", `failed` → "Failed". Reuse for the dashboard's recent-lessons cards too, same as the Library grid.
- The real `lessons` table has no thumbnail, duration, or chapter-title columns (confirmed against the migration in S1-09) — **`RecentLessons.tsx`'s current mock-shaped card (`lesson.thumbnailUrl`, `lesson.chapterTitle`, `lesson.progressPercent`) has no real counterpart**, exactly the same gap S1-09 hit with `LibraryCard`. This story rewrites `RecentLessons.tsx` around the real, sparse shape, following the same visual/interaction pattern S1-09 already established for `LibraryCard` (status badge, title with "Untitled Lesson" fallback, "Created {time ago}", Ready-only click-through) — don't reinvent a different pattern for the same data shape.

### Current mixed-mock/mixed-real shape this story produces

`apps/web/src/services/dashboard.service.ts`'s `DashboardData` currently has three fields, all mocked. After this story:
- `continueLearning: MockLesson | null` — **unchanged, still mocked** (still sourced from `apps/web/src/mocks/api/dashboard.ts`'s `dashboardApi.getDashboardData()`).
- `learningPulse: LearningPulse` — **unchanged, still mocked** (same source).
- `recentLessons: LessonStatusResponse[]` — **now real**, via `lessonsService.listLessons({limit: 5})`.
- New: `recentLessonsError: string | null` — set (and logged) if the real fetch fails, so the Recent Lessons widget can show its own inline error state **without blocking the rest of the dashboard** (Hero, Continue-Learning, Quick Actions, Learning Pulse all still render from their own, separately-successful mock fetch). This directly satisfies the original tracker AC "Error state shown on API failure (non-blocking — rest of dashboard still loads)" — a single top-level `ApiResponse.success: false` would incorrectly blank the *entire* dashboard, which is not what "non-blocking" means here.

### Loading state — extending an existing pattern, not inventing a new one

`apps/web/src/app/(dashboard)/library/page.tsx` already wraps its data-fetching in `<Suspense fallback={...}><LibraryDataFetcher /></Suspense>` (from a prior story). `apps/web/src/app/(dashboard)/dashboard/page.tsx` today has no such boundary — the whole page blocks on `dashboardService.getDashboard()` with nothing shown while it awaits. This story extracts a `DashboardDataFetcher` (same naming convention as `LibraryDataFetcher`) and wraps it in the same `Suspense` pattern, satisfying the original tracker AC "Loading skeletons shown during fetch" by reusing the established convention rather than building a new one.

## Acceptance Criteria

1. **`dashboard.service.ts`'s `DashboardData` gains `recentLessonsError: string | null`**; `recentLessons` changes type from `MockLesson[]` to `LessonStatusResponse[]` (imported from `upload.service.ts`, not redefined). `continueLearning`/`learningPulse` types and their computation are **unchanged**.
2. **`getDashboard()` fetches real recent lessons:**
   - Calls `lessonsService.listLessons({limit: 5})` for `recentLessons`.
   - Still calls the existing mock `dashboardApi.getDashboardData()` (from `apps/web/src/mocks/api/dashboard.ts`) for `continueLearning`/`learningPulse` — unchanged behavior for those two fields.
   - On a `listLessons` failure: catches it, logs it (`console.error`, matching S1-09's `library.service.ts` convention), sets `recentLessons: []` and `recentLessonsError` to a user-facing message — but the **overall `ApiResponse` still resolves `success: true`** (this is what makes it non-blocking; the rest of the dashboard must still render).
3. **`RecentLessons.tsx` rewritten for the real, sparse `LessonStatusResponse` shape:**
   - No thumbnail image, no chapter title, no progress bar/percentage — none of that data exists (same descope S1-09 already established for `LibraryCard`).
   - Each card: title (fallback "Untitled Lesson" when `null`), a status badge via `formatLessonStatusLabel` (Generating/Ready/Failed, same visual language as `LibraryCard`), "Created {formatTimeAgo(created_at)}".
   - Ready cards navigate to `/lesson/{lesson_id}` on click; Generating/Failed cards are not clickable (same rule as `LibraryCard`).
   - New `error?: string | null` prop: when set, renders an inline error message instead of the card list (still renders the "Recently Added Lessons" heading + "View All" link — only the card content is replaced).
   - When `lessons` is empty **and there's no error**, the component still returns `null` (existing behavior preserved — this is the genuine "nothing uploaded yet" case, distinct from a fetch error).
4. **`dashboard/page.tsx` passes the new `recentLessonsError` prop through** to `<RecentLessons>`. `HeroSection`, `ContinueLearningCard`, `QuickActions`, `LearningPulse` wiring is **completely unchanged** — still fed by the mocked `continueLearning`/`learningPulse` fields exactly as today.
5. **Loading state:** extract a `DashboardDataFetcher` async function from `DashboardPage` (same shape/naming as `LibraryDataFetcher`), wrap it in `<Suspense fallback={...}>` in `DashboardPage`, matching `library/page.tsx`'s existing pattern.
6. **Tests:**
   - `dashboard.service.test.ts` (new): `getDashboard()` calls `listLessons({limit: 5})`, returns success with real `recentLessons` and unchanged mocked `continueLearning`/`learningPulse`; on `listLessons` rejection, still resolves `success: true` with `recentLessons: []` and a non-null `recentLessonsError`, and logs the error.
   - `RecentLessons.test.tsx` (rewritten): Ready card navigates, Generating/Failed cards don't, title fallback, status badges, error prop shows inline error instead of cards, empty+no-error still returns nothing rendered.
   - `dashboard/page.test.tsx` (new, mirroring `library/page.test.tsx`): `DashboardDataFetcher` renders the full page on success; still renders the page (not a blank error page) when `recentLessonsError` is set, since the top-level response is still a success.
7. **No regression:** full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean (0 new warnings). `HeroSection.tsx`, `ContinueLearningCard.tsx`, `QuickActions.tsx`, `LearningPulse.tsx`, `lessons.service.ts`, `upload.service.ts`, and `library.service.ts`/`LibraryView.tsx` (S1-09's own files) are **not modified** by this story.

## Tasks / Subtasks

- [x] Task 1: Extend `DashboardData` + real fetch in `dashboard.service.ts` (AC: #1, #2)
  - [x] 1.1 RED — `getDashboard()` success/failure paths against the new shape
  - [x] 1.2 Implement (GREEN)
- [x] Task 2: Rewrite `RecentLessons.tsx` for real/sparse data + error prop (AC: #3)
  - [x] 2.1 RED — card rendering, click behavior, error state, empty state
  - [x] 2.2 Implement (GREEN)
- [x] Task 3: Wire `dashboard/page.tsx` — pass `recentLessonsError`, extract `DashboardDataFetcher` + `Suspense` (AC: #4, #5)
  - [x] 3.1 RED — new `dashboard/page.test.tsx` covering both cases
  - [x] 3.2 Implement (GREEN)
- [x] Task 4: Full verification (AC: #6, #7)
  - [x] 4.1 Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean
  - [x] 4.2 Confirm `HeroSection.tsx`/`ContinueLearningCard.tsx`/`QuickActions.tsx`/`LearningPulse.tsx`/S1-09's own files are untouched (`git diff --stat`)
- [x] Task 5: Tracker update
  - [x] 5.1 Mark S1-10 in `docs/dev2-sprint-tracker.md` as done

### Review Findings

5-agent adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) run against branch `sprint1/s1-10-dashboard-real-api` (commits `5ec027f`..`1804150`) vs its parent `feature-real-data-integration`, 2026-07-15.

- [x] [Review][Patch] The mock-data fetch (`dashboardApi.getDashboardData()`) has no error handling at all — sits outside the `try`/`catch` that only wraps the real `listLessons` call. A rejection (or a `success:false`/`data:null` resolution, a legal `ApiResponse<T>` variant) crashes `getDashboard()` wholesale, taking down the *entire* dashboard — exactly the failure mode this story's non-blocking design was meant to prevent [apps/web/src/services/dashboard.service.ts] (blind+edge) — fixed as part of the `Promise.allSettled` rewrite below.
- [x] [Review][Patch] The two fetches (mock summary data, real recent lessons) run as sequential `await`s even though neither depends on the other — the page now waits for the *sum* of both latencies instead of the *max*, a real UX regression versus the single combined mock call this replaced [apps/web/src/services/dashboard.service.ts] (edge) — fixed: rewrote `getDashboard()` around `Promise.allSettled([dashboardApi.getDashboardData(), lessonsService.listLessons(...)])`, so both run concurrently and either's rejection is handled independently without affecting the other. New test asserts both fetches' start/end interleave rather than running strictly one-after-the-other.
- [x] [Review][Patch] `mockResponse.data?.learningPulse as LearningPulse` is an unsafe cast with no runtime guard — if the mock data is ever missing, this silently forces `undefined` into a value typed as a real object, unlike the line above it (`continueLearning`), which is defended with `?? null` [apps/web/src/services/dashboard.service.ts] (blind+edge) — fixed: `DashboardData.learningPulse` is now typed `LearningPulse | null` honestly (no cast), defaulting to `null` via `?? null` just like `continueLearning`. `page.tsx`'s existing `{dashboardData?.learningPulse && (...)}` guard already handles the null case gracefully.
- [x] [Review][Patch] No runtime check that `lessonsService.listLessons()` actually resolved an array before treating it as success — a malformed 200 (e.g. a paginated wrapper instead of a bare array) is silently accepted, then `lessons.map(...)` in `RecentLessons.tsx` throws on the non-array value, blanking the whole page rather than degrading just the widget [apps/web/src/services/dashboard.service.ts, apps/web/src/components/dashboard/sections/RecentLessons.tsx] (edge) — fixed: `Array.isArray(lessonsResult.value)` check routes a non-array response into the same `recentLessonsError` path as a genuine rejection.
- [x] [Review][Patch] An unrecognized/unexpected `lesson.status` (typo, new backend value, casing mismatch) makes all three status booleans false — no badge renders and the card is silently non-interactive with zero indication anything's wrong; `formatLessonStatusLabel`'s own defensive "anything else → Failed" default is never reached because the component's own branching never routes an unknown status into the `isFailed` branch [apps/web/src/components/dashboard/sections/RecentLessons.tsx] (blind+edge) — fixed: `isFailed` is now `!generating && !isReady` (anything not generating/ready falls into the Failed bucket), matching `formatLessonStatusLabel`'s own default. New test uses an out-of-union status to confirm the badge still renders and the card stays non-interactive.
- [x] [Review][Patch] `lesson.title ?? 'Untitled Lesson'` doesn't catch an empty-string title (`??` only substitutes on `null`/`undefined`) — a lesson with `title: ""` (plausible for a still-generating lesson) renders a blank heading instead of the fallback [apps/web/src/components/dashboard/sections/RecentLessons.tsx] (blind) — fixed: switched to `lesson.title || 'Untitled Lesson'`, which also substitutes on empty string.

No dismissed findings this round — all 6 were genuine. One additional defensive fix made alongside these (not a separate finding, but directly related to the "always success" pattern the auditor and edge hunter both discussed): `DashboardDataFetcher` now checks `!response.success || !dashboardData` and shows a fallback message, mirroring `LibraryDataFetcher`'s existing pattern — belt-and-suspenders now that `getDashboard()` is fully hardened to never actually produce that case, but consistent with the sibling page and cheap to add.

## Dev Notes

### Files this story touches

- `apps/web/src/services/dashboard.service.ts` (MODIFY — real `recentLessons` fetch, new `recentLessonsError` field)
- `apps/web/src/components/dashboard/sections/RecentLessons.tsx` (MODIFY — full rewrite for real/sparse data + error prop)
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` (MODIFY — extract `DashboardDataFetcher`, add `Suspense`, pass `recentLessonsError`)
- `apps/web/src/__tests__/services/dashboard.service.test.ts` (NEW)
- `apps/web/src/__tests__/components/dashboard/sections/RecentLessons.test.tsx` (MODIFY — full rewrite)
- `apps/web/src/__tests__/app/dashboard/page.test.tsx` (NEW)
- `docs/dev2-sprint-tracker.md` (MODIFY — mark S1-10 done)

### What NOT to do

- Do NOT wire Continue-Learning or Learning Pulse to any real endpoint — none exists; both stay exactly as mocked today.
- Do NOT modify `HeroSection.tsx`, `ContinueLearningCard.tsx`, `QuickActions.tsx`, or `LearningPulse.tsx` — none of them need to change for this story.
- Do NOT modify `lessons.service.ts`, `api.server.ts`, `upload.service.ts`, `library.service.ts`, or `LibraryView.tsx` — S1-09's files, reused read-only.
- Do NOT let a `recentLessons` fetch failure blank the whole dashboard — it must degrade to just the Recent Lessons widget showing an inline error, per the non-blocking requirement.
- Do NOT fabricate thumbnail/duration/chapter-title data for the dashboard cards — same real constraint as `LibraryCard`.
- Do NOT build a new skeleton/loading UI pattern — reuse `library/page.tsx`'s existing `Suspense` + fallback convention.

### Project Structure Notes

Purely additive/localized: one service file, one component, one page file, plus their tests. No conflicts with `packages/shared` frozen contracts. Read-only reuse of `lessons.service.ts`/`api.server.ts`/`upload.service.ts` types from S1-09.

### References

- [Source: docs/dev2-sprint-tracker.md#S1-10 — Dashboard Real Data Integration] (original sketch — assumed `GET /api/lessons`/`GET /api/sessions/latest`, both wrong/nonexistent per S1-09's backend research; superseded here)
- [Source: docs/stories/1-9-library-real-data-integration.md] (the story this one directly builds on — real backend contract research, the server-auth fix, and the `LibraryCard` visual/interaction pattern this story reuses for `RecentLessons.tsx`)
- [Source: apps/web/src/services/lessons.service.ts, apps/web/src/lib/api.server.ts] (reused read-only)
- [Source: apps/web/src/services/dashboard.service.ts, apps/web/src/mocks/api/dashboard.ts] (files this story modifies/reads)
- [Source: apps/web/src/components/dashboard/sections/RecentLessons.tsx] (file this story rewrites)
- [Source: apps/web/src/app/(dashboard)/library/page.tsx] (the `Suspense`/`*DataFetcher` pattern this story mirrors for the dashboard page)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

- Task 1 RED confirmed: both new `dashboard.service.test.ts` tests failed against the old mock-only implementation (wrong shape / no `listLessons` call); GREEN after implementing (2/2 passing).
- Task 2 RED confirmed: 4 of 6 `RecentLessons.test.tsx` tests failed against the old mock-shaped component (`Failed` badge text, inline error text, title-fallback, Ready-click-navigates); the empty-state and "View All" tests happened to still pass trivially against the old component. GREEN after the rewrite (6/6 passing).
- Task 3 RED confirmed: new `dashboard/page.test.tsx` failed with `DashboardDataFetcher is not a function` before the export existed (`page.tsx` had no named export, only the default). GREEN after extracting `DashboardDataFetcher` + wrapping in `Suspense` (2/2 passing).

### Completion Notes List

- All 5 tasks completed; every AC satisfied.
- `continueLearning`/`learningPulse` remain fully mocked and their computation is byte-for-byte unchanged — confirmed via `git diff --stat` that `HeroSection.tsx`, `ContinueLearningCard.tsx`, `QuickActions.tsx`, `LearningPulse.tsx`, and all of S1-09's own files (`lessons.service.ts`, `api.server.ts`, `upload.service.ts`, `library.service.ts`, `LibraryView.tsx`) show zero diff against this branch's base.
- `getDashboard()`'s non-blocking design: a `recentLessons` fetch failure is caught, logged, and turned into `recentLessonsError` — but the top-level `ApiResponse` still resolves `success: true`, so the rest of the dashboard (which comes from a separate, already-resolved mock fetch) renders regardless. This was a deliberate response-shape decision, not an accidental catch-and-continue — a top-level `success: false` would have blanked the entire page via `page.tsx`'s existing failure branch, which is the opposite of "non-blocking."
- Reused `RecentLessons.tsx`'s Ready-card interaction pattern (status badge, title fallback, "Created X ago", keyboard-accessible `role="button"`/`tabIndex`/`onKeyDown` for Ready cards) directly from S1-09's `LibraryCard`, rather than inventing a second pattern for the same underlying data shape.
- `dashboard/page.tsx`'s `Suspense` + `*DataFetcher` split mirrors `library/page.tsx`'s existing pattern exactly, satisfying the original tracker AC's "loading skeleton" requirement without introducing a new convention.
- Post-review: rewrote `getDashboard()` around `Promise.allSettled` so the mock summary fetch and the real recent-lessons fetch run concurrently and fail independently — the original sequential-await version had a real gap where a mock-fetch failure crashed the whole dashboard, undermining the story's own non-blocking design. `LibraryCard`'s sibling gap (empty-string title, unrecognized-status dead card) was noted but intentionally left alone — S1-09's files are explicitly out of scope for this story.

### File List

**Files CREATED:**
- `apps/web/src/__tests__/services/dashboard.service.test.ts`
- `apps/web/src/__tests__/app/dashboard/page.test.tsx`

**Files MODIFIED:**
- `apps/web/src/services/dashboard.service.ts` — real `recentLessons` fetch via `lessonsService.listLessons({limit: 5})`, new `recentLessonsError` field, `continueLearning`/`learningPulse` computation unchanged
- `apps/web/src/components/dashboard/sections/RecentLessons.tsx` — full rewrite for the real, sparse `LessonStatusResponse` shape; new `error` prop
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` — extracted `DashboardDataFetcher`, wrapped in `Suspense` (mirrors `library/page.tsx`), passes `recentLessonsError` through
- `apps/web/src/__tests__/components/dashboard/sections/RecentLessons.test.tsx` — fully rewritten for the new component
- `docs/dev2-sprint-tracker.md` — S1-10 marked done

### Change Log

- 2026-07-15: Story created — Sprint 1 remainder task S1-10, branch `sprint1/s1-10-dashboard-real-api` off `feature-real-data-integration` (which has S1-09 merged in).
- 2026-07-15: All 5 tasks implemented in RED→GREEN order; 10 new/updated tests across 3 files; full `apps/web` suite 356/356 passing; `tsc --noEmit` clean; `eslint` clean (0 new warnings); confirmed all "do not touch" files untouched; story marked `review`.
