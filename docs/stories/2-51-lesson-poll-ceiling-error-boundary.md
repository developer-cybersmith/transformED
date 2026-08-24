---
baseline_commit: b169c21fdc1330c476edecda3f8b57a2a17913eb
---

# Story 2.51: Lesson-Status Poll Ceiling + Lesson Route Error Boundary (S4-11)

Status: ready-for-dev

## Story

As a student,
I want a stuck lesson generation to eventually stop silently polling forever, and a genuine crash on the lesson page to show the app's real error screen instead of Next.js's default one,
so that a backend hang or an unexpected render bug doesn't leave my tab quietly working forever or dump me on an unbranded, unhelpful page.

**Source:** a read-only audit of the full lesson-generation flow (upload → book/chapter → generate → poll/WebSocket → lesson-ready/failed), run at the user's request after S4-10. Full flow was found solid except for these 2 concrete gaps — this story fixes exactly those two, nothing else.

**Current state, confirmed by reading every file this story touches:**

- **Gap 1 — `useLesson.ts`'s poll has no ceiling.** `apps/web/src/hooks/useLesson.ts` defines its own `POLL_INTERVAL_MS = 5000` and a standalone `refreshIntervalFor()` that returns `POLL_INTERVAL_MS` unconditionally whenever `status` is `'queued'`/`'running'`, with **no ceiling at all**. Every other polling loop in this codebase (`UploadFlow.tsx`, `useChapters.ts`, `useBooks.ts` ×2, `useDashboard.ts`) calls the shared `nextPollInterval()` from `apps/web/src/lib/lessonStatusPoll.ts`, which tracks elapsed time via a `startedAtRef` and stops polling past `MAX_POLL_DURATION_MS` (~20 minutes) — `useLesson.ts` is the one outlier that reimplements its own interval logic instead of using that shared utility, and it's also the only one with no ceiling. A genuinely stuck `lesson_jobs` row would poll `GET /api/content/lessons/{id}` every 5s forever, for as long as the tab stays open.
  - `useLesson.ts`'s own comment claims `POLL_INTERVAL_MS = 5000` "matches UploadFlow.tsx's existing, already-shipped real polling-interval convention" — **this is stale/incorrect**: `UploadFlow.tsx` calls `nextPollInterval(true, pollWindowRef)` (confirmed by direct read), which resolves to the shared `LESSON_STATUS_POLL_INTERVAL_MS = 8000`, not 5000. All 5 other call sites use the shared 8000ms interval; `useLesson.ts` alone uses a different, undocumented-as-different 5000ms value.
  - `isLessonProcessing()` (already exported from `lessonStatusPoll.ts`) checks exactly `status === 'queued' || status === 'running'` — the identical condition `useLesson.ts`'s own `refreshIntervalFor` re-implements by hand.
- **Gap 2 — `/lesson/[id]` has no error boundary.** `apps/web/src/app/lesson/[id]/` has a `page.tsx` and a `layout.tsx`, but no `error.tsx`. `apps/web/src/app/(dashboard)/error.tsx` exists and covers every dashboard-group route, but the lesson route is **not** under that route group (`apps/web/src/app/lesson/[id]/page.tsx`, a sibling of `(dashboard)`, not inside it) and there is no root `apps/web/src/app/global-error.tsx` either (confirmed via repo-wide glob). An uncaught render exception anywhere in `Player.tsx`/its children (a malformed lesson package slipping past the degrade-not-drop design, or any other render bug) currently falls straight through to Next.js's default, unstyled error page — the one route in this entire flow with zero error-boundary coverage.

## Acceptance Criteria

1. **AC-1** — `useLesson.ts` no longer defines its own `POLL_INTERVAL_MS`/`refreshIntervalFor`. It uses the shared `isLessonProcessing()` + `nextPollInterval()` from `lessonStatusPoll.ts`, via a `pollingStartedAtRef` held in the hook (matching `useDashboard.ts`'s/`useChapters.ts`'s existing pattern), so polling now stops after `MAX_POLL_DURATION_MS` (~20 minutes) of continuous `queued`/`running` status, exactly like every sibling polling loop.
2. **AC-2** — The poll-interval behavior change is observable and tested: polling continues at the shared interval while processing and elapsed time is under the ceiling, and stops (interval resolves to `0`) once elapsed time exceeds the ceiling, using the same `nextPollInterval` unit-level contract already exercised by the other hooks' tests (or a direct test of `useLesson`'s wiring if a suitable test harness exists for it already).
3. **AC-3** — No behavior change to any of `useLesson`'s other exports (`lesson`, `isLoading`, `error`, `status`, `serverError`, `refetch`) or to `PlayerLoader.tsx`'s consumption of them — this story only changes how long polling continues, not what it polls or how results are interpreted.
4. **AC-4** — A new `apps/web/src/app/lesson/[id]/error.tsx` renders a branded error state (matching this app's existing `(dashboard)/error.tsx` pattern: logs the error via `console.error` in a `useEffect`, offers a `reset()`-backed "Try again" action) plus a link back to `/dashboard` (matching `PlayerLoader.tsx`'s own `LessonErrorState`'s existing "Return to Dashboard" affordance, for the case where retrying in place won't help). Must render legibly against the lesson route's dark layout background (`layout.tsx`'s `bg-primary-dark`/`text-slate-50`) — give it its own explicit contrasting surface rather than assuming the surrounding layout's colors.
5. **AC-5** — Tests: a unit/component test for the new `error.tsx` asserting it renders the expected copy, calls `reset` when "Try again" is clicked, and links to `/dashboard`. `useLesson.test.ts` (or equivalent) gets a test covering AC-2's ceiling behavior.
6. **AC-6** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Scale & Load

Answering the six questions (`docs/SCALE-CONTRACT.md`):

1. **Unit of work and range:** one page-mount poll loop for one lesson's status, per browser tab. Range is bounded by design after this fix: at most `MAX_POLL_DURATION_MS` (~20 min) of continuous polling at the shared interval (currently 8000ms, ~150 requests), then it stops. Before this fix the range was unbounded (as long as the tab stayed open).
2. **Fixed budgets vs. variable input:** `MAX_POLL_DURATION_MS` is the fixed budget being newly applied here; past it, polling explicitly stops (interval resolves to `0`) rather than silently continuing forever — this is precisely closing a "no budget at all" gap, not introducing a new truncation risk.
3. **Scope of every limit:** per-browser-tab, per-lesson — each `useLesson(lessonId)` call gets its own `pollingStartedAtRef`, so switching lessons or opening a second tab starts a fresh window, exactly like the existing 5 call sites' behavior.
4. **Unbounded reads/writes:** the fix removes the one unbounded read loop in this flow (Gap 1). No new reads/writes introduced.
5. **Inherited caps re-derived:** N/A — this story adopts an already-correctly-derived cap (`MAX_POLL_DURATION_MS`, already justified and used by 5 other call sites) rather than inventing a new one.
6. **Concurrent check-then-act safety:** N/A — no check-then-act sequence is introduced; this is a client-side polling-interval computation with no write/mutation involved.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 2, 3, 5): Replace `useLesson.ts`'s standalone poll-interval logic with the shared `nextPollInterval`/`isLessonProcessing`.
  - [x] 1.1 RED: write failing tests for the ceiling behavior (polls while under ceiling, stops past it) and confirm no change to the hook's other return values.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 4, 5): Add `apps/web/src/app/lesson/[id]/error.tsx`.
  - [x] 2.1 RED: write failing tests for render/copy, `reset()` wiring, and the dashboard link.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 6): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT change `LESSON_STATUS_POLL_INTERVAL_MS` (8000ms) or `MAX_POLL_DURATION_MS` (~20 min) in `lessonStatusPoll.ts` itself — those are already-established, already-justified shared constants; this story adopts them into `useLesson.ts`, it doesn't re-derive them.
- Do NOT touch `PlayerLoader.tsx`'s existing `LessonErrorState`/`LessonGeneratingState` — those already correctly handle the `failed`/`queued`/`running` *data* states. This story's `error.tsx` is a Next.js route-level error **boundary** for uncaught render exceptions, a distinct mechanism from those data-driven states, and doesn't replace or duplicate them.
- Do NOT add Sentry/observability wiring to the new `error.tsx` beyond a `console.error` call — `(dashboard)/error.tsx` (the pattern this mirrors) doesn't have Sentry wiring either; adding it here alone would be inconsistent, and wiring it everywhere is out of scope for this story.

### Testing standards

Vitest + Testing Library, matching existing conventions in `apps/web/src/__tests__/hooks/useLesson.test.ts` and the sibling hook tests (`useDashboard.test.ts`, `useChapters.test.ts` if present) for the polling-interval assertions, and `apps/web/src/__tests__/app/dashboard` conventions (or a new `apps/web/src/__tests__/app/lesson` directory) for the new `error.tsx` component test.

### References

- [Source: apps/web/src/lib/lessonStatusPoll.ts] — the shared ceiling utility this story adopts into `useLesson.ts`.
- [Source: apps/web/src/app/(dashboard)/error.tsx] — the existing error-boundary pattern this story's new `error.tsx` mirrors.
- [Source: apps/web/src/components/player/PlayerLoader.tsx] — the existing data-driven `LessonErrorState`/`LessonGeneratingState`, confirmed distinct from and untouched by this story.

## Dev Agent Record

### Implementation Plan

- `useLesson.ts`: dropped the standalone `POLL_INTERVAL_MS`/`refreshIntervalFor` entirely (its 5000ms interval turned out not to match anything else in the codebase — its own comment claiming it matched `UploadFlow.tsx` was stale, since that file actually uses the shared 8000ms `LESSON_STATUS_POLL_INTERVAL_MS`). Now uses `nextPollInterval(isLessonProcessing(latestData), pollingStartedAtRef)` via a `useRef` held in the hook, identical shape to `useDashboard.ts`'s/`useChapters.ts`'s existing wiring — this is now the 6th call site of the same shared utility, not a new one.
- New `apps/web/src/app/lesson/[id]/error.tsx`: mirrors `(dashboard)/error.tsx`'s pattern (log via `console.error` in a `useEffect`, `reset()`-backed "Try again"), plus a "Return to Dashboard" link matching `PlayerLoader.tsx`'s `LessonErrorState` copy/icon. Given its own explicit white card surface (not just transparent text) since it renders inside the lesson layout's dark `bg-primary-dark` wrapper — matches `PlayerLoader`'s existing light-card convention, which is what a student would otherwise see on this route.

### Completion Notes

- Both tasks complete, all ACs (1–6) satisfied.
- Full `apps/web` suite (this branch, cut from `main` before S4-10 merged): 81 files / 988 tests, all passing. `tsc --noEmit` clean. `eslint` clean on all touched files (no errors, no warnings).

### File List

- `apps/web/src/hooks/useLesson.ts` (MODIFIED — removed standalone poll interval/ceiling-less logic, now uses shared `nextPollInterval`/`isLessonProcessing`)
- `apps/web/src/app/lesson/[id]/error.tsx` (NEW — route-level error boundary)
- `apps/web/src/__tests__/hooks/useLesson.test.ts` (MODIFIED — added ceiling test)
- `apps/web/src/__tests__/app/lesson/error.test.tsx` (NEW — 3 tests for the new error boundary)

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-24 | Story created after a read-only lesson-generation-flow error-state audit found 2 real gaps (unbounded `useLesson.ts` poll, missing `/lesson/[id]` error boundary). Branch `sprint4/s4-11-poll-ceiling-error-boundary` off `main`. | Dev 2 |
