---
baseline_commit: da7dcfdd248cc4792bbab3b50e555116e7064774
---

# Story 2.27: Auto-Poll Library/Dashboard While a Lesson Is Still Generating

Status: ready-for-dev

## Story

As a student,
I want the Library and Dashboard pages to notice on their own when a lesson finishes generating,
so that a lesson doesn't look permanently stuck at "processing" just because I never manually refreshed the page after navigating away from Upload.

**Source:** user-reported symptom — "when we upload a PDF and move to another page, the lesson generation may stop there; certain lessons in the library are marked processing but never generated." Investigated the full chain end-to-end:

- `UploadFlow.tsx`'s polling loop is scoped to that component's mount lifetime by design (`useEffect` cleanup sets `cancelled = true` on unmount) — this is correct, not a bug. The actual ARQ job (`content_pipeline_job`, enqueued by the initial upload POST) runs entirely server-side, fully decoupled from the browser tab. Navigating away does **not** stop generation.
- The earlier-reported bug where `lessons.status` was never written at all (`docs/backend-issues-2026-07-13.md`) has already been fixed — `content_pipeline_job`'s `_update_lesson_status()` helper now writes to both `lesson_jobs` and `lessons` tables on every terminal transition (success, generic failure, cost-ceiling failure, and even ARQ cancellation).
- **The real, actionable gap**: `useLibrary()` and `useDashboard()` (both SWR hooks) fetch lesson status exactly once per mount, with no `refreshInterval` configured. Once the Library/Dashboard page is open, a lesson sitting in `queued`/`running` will **never update on its own** — SWR only refetches on remount or browser-tab refocus (its defaults). A lesson that genuinely finishes generating while the student is just sitting on the page won't flip to "ready" without a manual navigation/refresh. This is almost certainly the actual cause of the reported symptom, not generation actually stopping.

**Separately, and NOT in scope for this story**: whether a lesson can get genuinely, permanently stuck server-side (retry exhaustion, worker crash/restart) is a backend/infra question already flagged to Dev 1 in `docs/dev1-sprint2-bug-status-correction.md`. This story only fixes the frontend's failure to reflect a real, completed backend state.

## Acceptance Criteria

1. **AC-1** — `useLibrary()` polls (via SWR's `refreshInterval`) while `LibraryData.processing` is non-empty, and stops polling (`refreshInterval` evaluates to `0`) once no lesson is `queued`/`running`.
2. **AC-2** — `useDashboard()` polls while `DashboardData.continueLearning` or any entry in `DashboardData.recentLessons` has status `queued`/`running`, and stops otherwise.
3. **AC-3** — Poll interval is a named constant (`LESSON_STATUS_POLL_INTERVAL_MS`), not a magic number, shared between both hooks.
4. **AC-4** — No behavior change while there is no in-flight lesson: `refreshInterval` must evaluate to `0` (no polling) for an all-terminal result set, matching current behavior exactly (fetch once per mount/refocus, no interval).
5. **AC-5** — No regression to either hook's existing behavior: per-user SWR cache key scoping, `shouldRetryOnError: false`, `null` key when unauthenticated — all untouched.
6. **AC-6** — Tests: both hooks have tests asserting the `refreshInterval` option is a function that returns the poll interval when at least one lesson is non-terminal, and `0` otherwise (including the `undefined`/pre-fetch data case, which must also resolve to `0`, not poll before any data exists).
7. **AC-7** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 3, 4, 6): Add `refreshInterval` to `useLibrary()`, keyed on `LibraryData.processing.length > 0`.
  - [ ] 1.1 RED: write failing tests for the polling-on/off cases and the `undefined`-data case.
  - [ ] 1.2 GREEN: implement.
- [ ] Task 2 (AC: 2, 3, 4, 6): Add `refreshInterval` to `useDashboard()`, keyed on `continueLearning`/`recentLessons` non-terminal status.
  - [ ] 2.1 RED: write failing tests, same shape as Task 1.
  - [ ] 2.2 GREEN: implement.
- [ ] Task 3 (AC: 7): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### Current state of every file this story touches

- **`apps/web/src/hooks/useLibrary.ts`** — `useSWR<LibraryData>(key, fetcher, { shouldRetryOnError: false })`. No `refreshInterval` today.
- **`apps/web/src/hooks/useDashboard.ts`** — same shape, consuming `DashboardData` instead.
- **`apps/web/src/services/library.service.ts`** — `LibraryData.processing` is already `lessons.filter((l) => l.status === 'queued' || l.status === 'running')` — exactly the condition needed, no service change required.
- **`apps/web/src/services/dashboard.service.ts`** — `DashboardData` has `continueLearning: LessonStatusResponse | null` and `recentLessons: LessonStatusResponse[]` — no pre-computed "processing" bucket like `LibraryData`; the hook itself must check `.status` on both.
- **`apps/web/src/services/upload.service.ts`** — `LessonStatus = 'queued' | 'running' | 'ready' | 'failed'` — the type this story's non-terminal check is against.

### What NOT to do

- Do NOT add polling logic to the service layer (`dashboard.service.ts`/`library.service.ts`) — SWR's `refreshInterval` is the correct mechanism, consistent with this codebase's existing "hooks own data-fetching behavior, services own the API call shape" split.
- Do NOT poll unconditionally/always — only while at least one lesson is genuinely non-terminal, to avoid needless backend load once everything has settled.
- Do NOT attempt to also fix a genuinely-stuck backend job in this story — that's a backend/infra investigation already handed to Dev 1 separately.

### Testing standards

Vitest, mocking `swr`'s default export directly (`vi.mock('swr', () => ({ default: useSWRMock }))`), matching `useLibrary.test.ts`/`useDashboard.test.ts`'s existing pattern exactly. Assert on the `refreshInterval` function passed as the third `useSWR` argument by calling it directly with sample `LibraryData`/`DashboardData` shapes (including `undefined`, matching pre-fetch state) and checking its return value — do not attempt to exercise SWR's real internal polling/timer machinery.

### References

- [Source: apps/web/src/hooks/useLibrary.ts, apps/web/src/hooks/useDashboard.ts] — the two files this story modifies.
- [Source: apps/web/src/components/dashboard/upload/UploadFlow.tsx] — confirmed its own polling loop is correctly scoped to component lifetime, not a bug; `POLL_INTERVAL_MS = 5000` there is a precedent for this story's own interval constant, though not necessarily the same value (background page polling vs. the actively-watched upload screen).
- [Source: apps/api/app/workers/jobs/content_pipeline.py] — confirmed the ARQ job is fully decoupled from the browser and `lessons.status` is correctly written on every terminal transition.
- [Source: docs/dev1-sprint2-bug-status-correction.md] — where the separate, out-of-scope backend/infra stuck-job question is tracked for Dev 1.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-27 | Story created after investigating a user-reported "generation stops on navigation" symptom — traced to the real gap (no auto-refresh on Library/Dashboard), not the suspected one (navigation stopping the backend job, which is not possible). Branch `sprint2/s2-27-library-auto-poll` off `main`. | Dev 2 |
