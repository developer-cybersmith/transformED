---
baseline_commit: 6fccd6aab98d76a3f4bcd2e554684a96f28a0e69
---

# Story 2.14: Wire Dashboard & Library to the Real `GET /lessons` Endpoint

Status: review

## Story

As a student,
I want the dashboard and library to show my actual generated lessons instead of hardcoded sample data,
so that a lesson I just generated (like the "SQL Injection" one tested live this session) actually appears somewhere I can find it again.

**Source:** live end-to-end testing this session found that a freshly-generated lesson never appears on `/dashboard` or `/library`. Investigated and corrected a wrong assumption along the way: `docs/master-tracker.md`'s "Wire library/dashboard to GET /api/content/lessons — will return empty/501 until Dev 1 implements Supabase query" is **stale**. Read `apps/api/app/modules/content/router.py:369-392` directly — `GET /lessons` is already fully implemented: real per-user Supabase query, paginated (`limit`/`offset`), ordered `created_at desc`. **This is a frontend gap, not a backend one** — `apps/web/src/services/dashboard.service.ts` and `library.service.ts` were never wired to it; they still call their mock functions.

**The real constraint this story has to design around:** the real `LessonStatusResponse` (`lesson_id, status, title, error, created_at, completed_at` — confirmed via `apps/web/src/services/upload.service.ts`, which already declares this type matching the backend exactly) does **not** carry several fields the current mock-driven UI displays: `chapterTitle`, `durationSeconds`, `progressPercent`, `lastAccessed`, `thumbnailUrl`. None of these exist anywhere in the real pipeline/schema — there is no lesson-thumbnail concept at all, and per-user viewing/resume progress is tracked nowhere server-side yet (that's the separate, already-escalated `GET /api/sessions/latest` gap, blocked on Dev 4's Redis session state — not something this story can or should fabricate).

Per this project's own established convention (degrade gracefully, never fabricate data — the same discipline behind `AudioTimeline`'s empty-`audio_url` handling and `SlideRenderer`'s image fallback), this story **removes or honestly simplifies** the UI elements that depend on data that doesn't exist, rather than inventing placeholder values. Decided with the user: `ContinueLearningCard` is wired to real data too (not deferred), using the most-recently-created `ready` lesson as a genuine "jump back into your latest lesson" shortcut — but its fabricated progress ring/percentage is replaced with a plain "Ready to continue" state, since a real resume-position isn't available.

## Acceptance Criteria

1. **AC-1** — `dashboard.service.ts` and `library.service.ts` call the real `GET /lessons` endpoint (via `api.get`) instead of their mock functions. `learningPulse` (Dev 3's analytics domain, unrelated to lesson data) is explicitly **out of scope** — it stays on its existing mock call, composed alongside the real lesson data so `DashboardPage`'s existing `dashboardData?.learningPulse` consumption is unaffected.
2. **AC-2** — Real backend statuses (`queued`/`running`/`ready`/`failed`) are used directly — no continued reliance on the mock's `MockLesson.status` vocabulary (`'completed'|'in_progress'|'processing'|'failed'`), which conflated *generation* status with *viewing* status.
3. **AC-3** — `RecentLessons.tsx`: renders real `title`/`status`, drops the fabricated progress bar (replaced with a simple status label: "Ready" / "Processing" / "Failed"), and drops the `chapterTitle`/thumbnail-driven layout elements that have no real data source. Clicking a card still navigates to `/lesson/{lesson_id}`.
4. **AC-4** — `LibraryView.tsx`/`LibraryCard`: tabs are renamed from `All / In Progress / Completed / Processing` to `All / Ready / Processing / Failed` — honestly reflecting the only status vocabulary that actually exists server-side (`queued`+`running` both bucket into "Processing"). The per-card progress bar (which needs `progressPercent`, unavailable) is removed — the existing top-right status badge (Ready/Processing/Failed) is sufficient and already present in the component. Thumbnail `<img>` is removed (no real image source) rather than pointed at a broken/empty URL.
5. **AC-5** — `ContinueLearningCard.tsx`: receives the most-recently-created lesson with `status === 'ready'` (already true from the backend's own `created_at desc` ordering — the first `ready` entry in the list is the most recent). Renders title and a "Ready to continue" state instead of a percentage ring; "Resume" still navigates to `/lesson/{lesson_id}`. Renders nothing (`null`) when there is no `ready` lesson yet.
6. **AC-6** — A failed `GET /lessons` call degrades to the same graceful "couldn't load" messaging both pages already show today for a failed mock call — not a hard crash/generic error boundary.
7. **AC-7** — No fabricated data anywhere: no placeholder percentage, no placeholder thumbnail URL, no invented "chapter" grouping. Every rendered value traces to a real API field.
8. **AC-8** — Tests updated: all 3 components' existing test suites are rewritten against the new real-data shape and simplified UI (thumbnail/progress-bar-specific tests removed since those elements no longer exist); new tests cover the status-label rendering, the tab-relabeling, and the `ContinueLearningCard` null-when-no-ready-lesson case.
9. **AC-9** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 2, 6): Rewrite `dashboard.service.ts` and `library.service.ts` to call the real `GET /lessons` endpoint.
  - [x] 1.1 RED: tests asserting each service calls `api.get('content/lessons', ...)` and returns the real, unwrapped shape (no `ApiResponse`/`.success`/`.data` envelope — matching `onboarding.service.ts`/`upload.service.ts`'s existing real-service convention, not the mock's `createSuccessResponse` wrapper).
  - [x] 1.2 GREEN.
- [x] Task 2 (AC: 3, 7, 8): `RecentLessons.tsx` — drop progress bar/chapterTitle/thumbnail, add status label.
  - [x] 2.1 RED: rewrite `RecentLessons.test.tsx` against the real `LessonStatusResponse` shape; remove the now-inapplicable thumbnail-specific tests; add a status-label test.
  - [x] 2.2 GREEN.
- [x] Task 3 (AC: 4, 7, 8): `LibraryView.tsx`/`LibraryCard` — rename tabs, drop progress bar/thumbnail.
  - [x] 3.1 RED: rewrite `LibraryView.test.tsx` against the real shape and the new `Ready/Processing/Failed` tab set.
  - [x] 3.2 GREEN.
- [x] Task 4 (AC: 5, 7, 8): `ContinueLearningCard.tsx` — real "latest ready lesson" shortcut, no fabricated ring.
  - [x] 4.1 RED: rewrite `ContinueLearningCard.test.tsx`; add a null-render test for no-ready-lesson.
  - [x] 4.2 GREEN.
- [x] Task 5 (AC: 6): `dashboard/page.tsx` and `library/page.tsx` — adjust to the new (unwrapped) service return shape while preserving the existing graceful failed-load messaging.
  - [x] 5.1 GREEN (no dedicated new test beyond the service-level failure tests from Task 1 and the existing page structure — these are Server Components not currently unit-tested individually, matching the codebase's existing convention for this file).
- [x] Task 6 (AC: 9): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/api/app/modules/content/router.py:369-392`** (`list_lessons`, read-only, backend) — fully real: `supabase.table("lessons").select("*").eq("user_id", user_id).order("created_at", desc=True).range(offset, offset+limit-1)`. Response model `list[LessonStatusResponse]` (`lesson_id, status, title, error, created_at, completed_at` — `content` deliberately omitted at list level "to avoid an N-lessons x M-assets signing storm", per its own docstring at line 66-69).
- **`apps/web/src/services/upload.service.ts`** — already declares `LessonStatusResponse` matching the backend exactly (confirmed field-for-field this session while auditing Story 2-13's neighboring code). Reuse this type — do not re-declare a fourth copy.
- **`apps/web/src/services/dashboard.service.ts`** (current, 5 lines): `{ getDashboard: () => dashboardApi.getDashboardData() }` — fully mock.
- **`apps/web/src/services/library.service.ts`** (current, 5 lines): `{ getLibrary: () => libraryApi.getLibrary() }` — fully mock.
- **`apps/web/src/mocks/api/dashboard.ts`/`library.ts`** — NOT deleted by this story (still referenced for `learningPulse`'s mock in the dashboard case; deleting the library mock's `LibraryData`/`MockLesson` types entirely is out of scope — only the *services* stop calling them for lesson data).
- **`apps/web/src/components/dashboard/sections/RecentLessons.tsx`**, **`ContinueLearningCard.tsx`**, **`apps/web/src/components/library/LibraryView.tsx`** — all read in full this session; current `MockLesson`-shaped props and exact fields consumed are documented in the Story/Context section above.
- **`apps/web/src/app/(dashboard)/dashboard/page.tsx`** — Server Component, `const response = await dashboardService.getDashboard(); const dashboardData = response.data;` — the `.data` unwrap must be removed once the service stops returning an `ApiResponse` envelope.
- **`apps/web/src/app/(dashboard)/library/page.tsx`** — Server Component, `LibraryDataFetcher` async function checks `if (!response.success || !response.data)` for the graceful failed-state message — must be adapted to a try/catch around the real (throwing) `api.get` call instead, preserving the same user-facing message.

### What NOT to do

- Do NOT touch `learningPulse`/`mocks/data/reports.ts` — Dev 3's analytics domain, unrelated to this story.
- Do NOT fabricate a `progressPercent`, `thumbnailUrl`, `chapterTitle`, or `durationSeconds` value (e.g., a hardcoded `0%` or a placeholder image URL) — remove the UI element instead. Matches this project's established "degrade gracefully, never fabricate" convention.
- Do NOT attempt to build real per-user viewing-progress tracking in this story — that needs Dev 4's session/Redis work (`GET /api/sessions/latest`, already escalated in `docs/master-tracker.md`), genuinely out of scope here.
- Do NOT touch the backend (`list_lessons` is already correct and sufficient for this story's scope).
- Do NOT delete `apps/web/src/mocks/data/lessons.ts`/`MockLesson` type outright — it may still be referenced elsewhere (e.g. `InteractivePlayer.tsx`'s mock stub, confirmed unrelated/out of scope); only stop the 3 components in this story's scope from depending on it.

### Testing standards

Vitest + `@testing-library/react` + `@testing-library/user-event`, matching every other component test in this codebase. For the two services, follow `onboarding.service.ts`/`upload.service.ts`'s existing real-API test pattern (mock `@/lib/api`'s `get`, assert the real endpoint path and params, assert the returned shape) — not the old mock-file's `ApiResponse` wrapper pattern.

### References

- [Source: this session's live end-to-end test] — the reported gap ("generated lessons don't appear in dashboard/library")
- [Source: apps/api/app/modules/content/router.py:369-392] — confirmed-real `list_lessons` endpoint, corrects `docs/master-tracker.md`'s stale note
- [Source: apps/web/src/services/upload.service.ts] — the already-defined `LessonStatusResponse` type this story reuses
- [Source: docs/master-tracker.md] — the separate, still-genuinely-blocked `GET /api/sessions/latest` (Dev 4) gap, explicitly not part of this story's scope
- [Source: docs/stories/2-11-quiz-feedback-field-fix.md, 2-13-assessment-test-fixes.md] — the "reuse the real type, don't re-declare a drifting copy" precedent this story follows for `LessonStatusResponse`

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-24 | Story created after live testing found generated lessons never appear on dashboard/library. Corrected a stale tracker assumption — the real `GET /lessons` backend endpoint already exists and works; the gap is purely frontend wiring. Scoped what's honestly achievable given several mock-only fields (thumbnail, duration, progress%, chapterTitle) have no real backend analog — decided with the user to wire `ContinueLearningCard` too, using a real "latest ready lesson" shortcut rather than deferring it or faking resume-progress. Branch `sprint2/s2-14-real-dashboard-library` off `sprint2-master`. | Dev 2 |
| 2026-07-24 | Implemented all 6 tasks (RED→GREEN throughout). Rewrote both services to call the real `GET /lessons` endpoint (reusing `upload.service.ts`'s existing `LessonStatusResponse` type); rewrote `RecentLessons`/`LibraryView`+`LibraryCard`/`ContinueLearningCard` to render real data with graceful degradation (status labels instead of fabricated progress bars, no thumbnail `<img>`, `Ready/Processing/Failed` library tabs instead of the old viewing-progress-based tabs); updated `dashboard/page.tsx` and `library/page.tsx` for the new unwrapped, throwing service contract while preserving the existing graceful failed-load UI (also fixed a pre-existing `LibraryDataFetcher` test that predated this story and still exercised the old `ApiResponse` shape). Full suite 50 files / 448 tests passing, `tsc --noEmit` and `eslint` clean. Status → review. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- **Task 1** — both services now `api.get<LessonStatusResponse[]>('content/lessons', { params: {...} })` directly, matching `onboarding.service.ts`/`upload.service.ts`'s real-service convention (no `ApiResponse` envelope). `dashboardService.getDashboard()` composes real lesson data with the still-mocked `learningPulse` (Dev 3's unrelated analytics domain) via `Promise.all`, preserving `DashboardPage`'s existing consumption shape as much as possible.
- **Tasks 2-4** — each component's mock-only fields (`chapterTitle`, `durationSeconds`, `progressPercent`, `lastAccessed`, `thumbnailUrl`) were removed rather than backfilled with placeholder values, per this project's established degrade-gracefully-never-fabricate convention. `LibraryView`'s tabs renamed `All/In Progress/Completed/Processing` → `All/Ready/Processing/Failed` to honestly reflect the only status vocabulary that exists server-side (generation status, not per-user viewing progress).
- **Task 5** — `dashboard/page.tsx`/`library/page.tsx` wrap the now-throwing real service calls in try/catch, assigning to a variable before any JSX is constructed (an `eslint` `react-hooks/error-boundaries` rule flagged an initial attempt at constructing JSX directly inside the `try` block in `library/page.tsx` — fixed by capturing the result first, matching `dashboard/page.tsx`'s pattern).
- Found and fixed a pre-existing test file (`__tests__/app/library/page.test.tsx`) not listed in this story's original file survey — it exercised `LibraryDataFetcher` against the old `{success, data, message}` mock envelope; updated to the new plain-return/throw-on-failure contract.

### Completion Notes

- All 6 tasks complete, all ACs (1–9) satisfied.
- Full `apps/web` test suite: 50 files, 448 tests, all passing (+12 net new/rewritten tests across this story's 7 touched test files, +2 from the pre-existing `library/page.test.tsx` fix).
- `tsc --noEmit`: clean. `eslint` on all touched files: clean.
- No backend changes — `list_lessons` was already correct and sufficient.
- `mocks/data/lessons.ts`/`MockLesson` and `mocks/api/dashboard.ts`/`library.ts` were NOT deleted (still referenced by `learningPulse`'s mock and potentially other unrelated consumers) — only the 2 real services stopped depending on them for lesson data.

### File List

- `apps/web/src/services/dashboard.service.ts` (MODIFIED)
- `apps/web/src/services/library.service.ts` (MODIFIED)
- `apps/web/src/components/dashboard/sections/RecentLessons.tsx` (MODIFIED)
- `apps/web/src/components/dashboard/sections/ContinueLearningCard.tsx` (MODIFIED)
- `apps/web/src/components/library/LibraryView.tsx` (MODIFIED)
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` (MODIFIED)
- `apps/web/src/app/(dashboard)/library/page.tsx` (MODIFIED)
- `apps/web/src/__tests__/services/dashboard.service.test.ts` (NEW)
- `apps/web/src/__tests__/services/library.service.test.ts` (NEW)
- `apps/web/src/__tests__/components/dashboard/sections/RecentLessons.test.tsx` (MODIFIED — rewritten)
- `apps/web/src/__tests__/components/dashboard/sections/ContinueLearningCard.test.tsx` (MODIFIED — rewritten)
- `apps/web/src/__tests__/components/library/LibraryView.test.tsx` (MODIFIED — rewritten)
- `apps/web/src/__tests__/app/library/page.test.tsx` (MODIFIED — updated to the new service contract; pre-existing, not in the original file survey)
