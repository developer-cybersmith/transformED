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
- Full `apps/web` suite (this branch, cut from `main` before S4-10 merged, post-review-round): 82 files / 992 tests, all passing. `tsc --noEmit` clean. `eslint` clean on all touched files (0 errors; 2 pre-existing, unrelated warnings on unused mock-setup params in `PlayerLoader.test.tsx`, not introduced by this story).
- See **Senior Developer Review** below — an 8-agent adversarial review found 2 real defects (both fixed) beyond the initial implementation's scope, plus a stray z-index gap (fixed) and several findings triaged not-actioned with reasons.

### File List

- `apps/web/src/hooks/useLesson.ts` (MODIFIED — removed standalone poll interval/ceiling-less logic, now uses shared `nextPollInterval`/`isLessonProcessing`; review round: added `pollTimedOut` state, set once the ceiling is reached while still processing, cleared by `refetch()`)
- `apps/web/src/app/lesson/[id]/error.tsx` (NEW — route-level error boundary; review round: added `relative z-10` to match `page.tsx`'s own stacking convention)
- `apps/web/src/app/lesson/[id]/page.tsx` (review round: keys `<PlayerLoader>` by `lessonId`, matching the existing `<Player key={lesson.lesson_id}>` precedent one level down — closes a staleness gap where this hook instance wasn't guaranteed to unmount on navigation between two lessons)
- `apps/web/src/components/player/PlayerLoader.tsx` (review round: `LessonGeneratingState` shows an explicit "taking longer than expected" message + Check again button when `pollTimedOut` is true, instead of a spinner that could silently freeze forever once polling gives up)
- `apps/web/src/__tests__/hooks/useLesson.test.ts` (MODIFIED — ceiling test, plus review-round tests for `pollTimedOut`'s three states and the terminal-status-past-ceiling case)
- `apps/web/src/__tests__/app/lesson/error.test.tsx` (NEW — 3 tests for the new error boundary)
- `apps/web/src/__tests__/app/lesson/page.test.tsx` (NEW, review round — 1 test confirming `page.tsx` keys `PlayerLoader` by `lessonId`)
- `apps/web/src/__tests__/components/player/PlayerLoader.test.tsx` (MODIFIED — 1 new test for the poll-timeout UI; all pre-existing mocks updated for the new required `pollTimedOut` field)

## Senior Developer Review (AI)

**Date:** 2026-08-24
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers (8 layers, per CLAUDE.md's BMAD Code Review Gate):** Blind Hunter (diff-only, no project context), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec), Scale & Load Hunter (diff + repo access + `docs/SCALE-CONTRACT.md`), Story Quality, Test Coverage, AC Completeness, Process Integrity.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | High (corroborated — Scale & Load Hunter, independently verified) | Scale & Load Hunter | Closing the infinite-poll gap (AC-1) without any accompanying signal meant that once `MAX_POLL_DURATION_MS` elapsed, `LessonGeneratingState` would render the identical "still generating, hang tight" spinner forever with **zero way to tell "still working" apart from "gave up 3 hours ago"** — no error, no manual action, `revalidateOnFocus: false` blocking even a tab-refocus recovery. Directly analogous to `UploadFlow.tsx`'s own `giveUpSlow()` degradation, which this story's implementation had not adopted. | Fixed — `useLesson.ts` now exposes `pollTimedOut`, set when the ceiling is reached while still processing; `PlayerLoader.tsx`'s `LessonGeneratingState` shows an explicit message + a "Check again" button (calling `refetch()`) instead of the plain spinner once timed out. |
| 2 | High (corroborated 3× — Blind Hunter, Edge Case Hunter, Test Coverage, independently) | Multiple | `pollingStartedAtRef` (and the new `pollTimedOut`) lived in a `useRef`/`useState` scoped to the `useLesson` hook instance, but nothing in `PlayerLoader`/`page.tsx` guaranteed that instance unmounts on a `lessonId` change — confirmed via `PlayerLoader.test.tsx`'s own pre-existing `rerender()`-with-a-different-`lessonId` test, which proves the component is reused, not remounted. A still-generating lesson A's elapsed poll window (or timed-out state) would carry over to a freshly-navigated-to lesson B, potentially stopping B's polling almost immediately. | Fixed — `apps/web/src/app/lesson/[id]/page.tsx` now keys `<PlayerLoader key={lessonId}>`, matching the exact precedent already used one level down (`<Player key={lesson.lesson_id}>`). A fresh mount per lesson eliminates the whole staleness class structurally, and was chosen over an in-hook reset specifically because this repo's `react-hooks/refs` ESLint rule forbids reading/writing a ref's `.current` during render (the first attempted fix, an "adjust state during render on a prop change" pattern per React's own docs, failed CI for exactly this reason — this repo's lint config is stricter than what React's docs describe as acceptable). |
| 3 | Low-Medium | Edge Case Hunter | The new `error.tsx`'s root wrapper had no `relative`/`z-index`, while `page.tsx`'s own content wrapper explicitly sets `relative z-10` specifically to sit above `layout.tsx`'s `absolute z-0` noise-overlay div. Per CSS paint order, a positioned sibling paints after static in-flow content regardless of DOM order — the overlay could paint above the error card. | Fixed — added `relative z-10` to `error.tsx`'s root wrapper, matching `page.tsx`'s established convention. |
| 4 | Medium, acknowledged not fixed | Edge Case Hunter, Acceptance Auditor (both independently) | Adopting the shared `nextPollInterval`/`LESSON_STATUS_POLL_INTERVAL_MS` means the poll cadence while generating changed from `useLesson.ts`'s old (undocumented-as-unique) 5000ms to the shared 8000ms — a genuine ~37.5% slower cadence, with no WebSocket push wired into this hook to compensate. | Not actioned — this is the direct, disclosed consequence of AC-1's mandate to adopt the shared utility wholesale (the story's own Gap 1 narrative already flags the old 5000ms value as stale/undocumented, not a deliberately-tuned one), and AC-3 only protects the hook's six *exported values* from behavior change, not poll cadence. Both reviewers agreed this is disclosed, not silent. |
| 5 | Low, single-sourced (Blind Hunter), refuted | Blind Hunter | Claimed the diff (as pasted into the review prompt) had a duplicate `refreshInterval` object key that wouldn't compile. | Not a real defect — this was an artifact of the diff text being hand-constructed for the diff-only Blind Hunter prompt (which gets no repo access) rather than pasted verbatim from a real `git diff`; independently confirmed by reading the actual committed file, which has no such duplication. Lesson for future reviews: always paste real `git diff` output for diff-only reviewers, never hand-reconstruct it. |
| 6 | Low, single-sourced (Blind Hunter) | Blind Hunter | New `error.tsx` has no Sentry/observability wiring beyond `console.error`. | Not actioned — matches `(dashboard)/error.tsx`'s identical existing pattern (also `console.error`-only); explicitly listed in this story's own "What NOT to do." |
| 7 | Low, single-sourced (Blind Hunter) | Blind Hunter | `ArrowLeft` icon on the "Return to Dashboard" link implies browser-back, not a fixed-destination link. | Not actioned — copies `PlayerLoader.tsx`'s own pre-existing `LessonErrorState` icon/copy verbatim for consistency; not a new inconsistency introduced by this story. |
| 8 | Low, single-sourced (Test Coverage) | Test Coverage | No test constructs an `error` with a `digest` field for `error.tsx`. | Not actioned — `error.tsx` never branches on `digest`, so there is no digest-specific behavior to cover; confirmed by Edge Case Hunter as a non-issue at the runtime level too. |
| Operational | — | Story Quality, Acceptance Auditor (both independently) | Both reviewers observed live, evolving uncommitted changes to these exact files mid-review — a review subagent running in the same shared working directory (not an isolated worktree) had run `git stash` to isolate a clean comparison state, discarding an in-progress round of these same fixes. | Resolved outside the story itself — recovered from `git stash list` (4 `temp-audit-isolate-*` entries, all confirmed superseded and dropped after reapplying), fixes reapplied and committed cleanly, then the two lint-rule failures this surfaced (see finding #2) were fixed for real. See `feedback-review-agents-shared-workspace` memory for the process lesson. |

### Non-issues independently re-verified

- AC-1, AC-4 (copy/reset/link/contrast), AC-6 (suite/tsc/eslint) all independently reproduced as SATISFIED by the Acceptance Auditor by running the actual commands against the isolated committed tree, not trusting the story's own prose.
- Story-First Gate and Sprint Task Branch Rule confirmed followed by Story Quality and Process Integrity via `git log` and `git merge-base` — story-only commit (`e1a1dfd`) precedes the implementation commit (`d0a3d8a`), branch cut cleanly from `main`, name matches the required pattern.
- All three "What NOT to do" boundaries (no touching `PlayerLoader.tsx`'s pre-existing states *at implementation time*, no changing `lessonStatusPoll.ts`'s shared constants, no Sentry beyond `console.error`) confirmed respected in the original implementation by Process Integrity via direct file reads and `git log --stat` scoped to those paths — the review round's own fix to `PlayerLoader.tsx` (finding #1) is a deliberate, documented, review-driven exception to that boundary, not an oversight.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-24 | Story created after a read-only lesson-generation-flow error-state audit found 2 real gaps (unbounded `useLesson.ts` poll, missing `/lesson/[id]` error boundary). Branch `sprint4/s4-11-poll-ceiling-error-boundary` off `main`. | Dev 2 |
| 2026-08-24 | Implemented both tasks (TDD, RED then GREEN). 8-agent adversarial review found 2 real defects beyond the original scope (poll-timeout UX gap, lessonId-change staleness) plus a z-index gap — all 3 fixed; 4 further findings triaged not-actioned with reasons. One operational incident (a review subagent's `git stash` discarding uncommitted work mid-review) recovered cleanly with no data loss. Final: 82 files / 992 tests passing, `tsc --noEmit` and `eslint` clean. See Senior Developer Review above. | Dev 2 |
