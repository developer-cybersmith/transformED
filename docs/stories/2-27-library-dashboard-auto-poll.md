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
5. **AC-5** — No regression to either hook's existing behavior: per-user SWR cache key scoping and `null` key when unauthenticated stay untouched. *(Amended during review — see Senior Developer Review finding #1: `shouldRetryOnError` was restored to SWR's default `true`, a deliberate, necessary change, not a regression — keeping it `false` alongside indefinite polling caused auto-refresh to silently freeze after any transient error.)*
6. **AC-6** — Tests: both hooks have tests asserting the `refreshInterval` option is a function that returns the poll interval when at least one lesson is non-terminal, and `0` otherwise (including the `undefined`/pre-fetch data case, which must also resolve to `0`, not poll before any data exists).
7. **AC-7** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 3, 4, 6): Add `refreshInterval` to `useLibrary()`, keyed on `LibraryData.processing.length > 0`.
  - [x] 1.1 RED: write failing tests for the polling-on/off cases and the `undefined`-data case.
  - [x] 1.2 GREEN: implement.
- [x] Task 2 (AC: 2, 3, 4, 6): Add `refreshInterval` to `useDashboard()`, keyed on `continueLearning`/`recentLessons` non-terminal status.
  - [x] 2.1 RED: write failing tests, same shape as Task 1.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 7): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

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
| 2026-07-27 | Implemented both tasks. Added shared `apps/web/src/lib/lessonStatusPoll.ts` (`LESSON_STATUS_POLL_INTERVAL_MS`, `isLessonProcessing()`) used by both hooks. Full suite 53 files / 502 tests passing, `tsc --noEmit` and `eslint` clean. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Used SWR's `refreshInterval` as a function of the latest data (SWR v2.3.3 supports this) rather than a fixed interval, so polling automatically stops once nothing is left in flight — avoids needless backend load once a lesson set has fully settled.
- `LibraryData` already had a pre-computed `processing` bucket (`library.service.ts`), so `useLibrary()`'s condition is a direct length check. `DashboardData` has no equivalent bucket, so a small shared `isLessonProcessing()` helper checks `.status` on `continueLearning`/`recentLessons` directly — put in a new `lib/lessonStatusPoll.ts` rather than duplicated inline in both hooks, since both the constant and the check needed to be identical between them (AC-3).
- Deliberately did not touch the service layer — `refreshInterval` is purely a data-fetching-cadence concern, which SWR already owns in this codebase's existing hook/service split.

### Completion Notes

- Both tasks complete, all ACs (1–7) satisfied.
- Full `apps/web` test suite: 53 files, 502 tests, all passing.
- `tsc --noEmit`: clean. `eslint` on all touched files: clean.
- SWR's `refreshInterval` already respects the Page Visibility API by default (pauses while the tab is hidden, catches up on refocus) — no extra work needed to avoid polling a backgrounded tab.

### File List

- `apps/web/src/lib/lessonStatusPoll.ts` (MODIFIED — added `MAX_POLL_DURATION_MS` + `nextPollInterval()` ref-based cap helper, review round)
- `apps/web/src/hooks/useLibrary.ts` (MODIFIED — added `refreshInterval`; review round: `shouldRetryOnError: true`, wired through `nextPollInterval`)
- `apps/web/src/hooks/useDashboard.ts` (MODIFIED — added `refreshInterval`; review round: `shouldRetryOnError: true`, wired through `nextPollInterval`)
- `apps/web/src/app/(dashboard)/library/page.tsx` (MODIFIED, review round — renders stale-but-good data alongside an error banner instead of hiding the whole library on any error)
- `apps/web/src/__tests__/hooks/useLibrary.test.ts` (MODIFIED — new polling-condition tests; review round: `shouldRetryOnError: true` assertion, poll-duration-cap tests)
- `apps/web/src/__tests__/hooks/useDashboard.test.ts` (MODIFIED — new polling-condition tests; review round: `shouldRetryOnError: true` assertion, poll-duration-cap test)
- `apps/web/src/__tests__/app/library/page.test.tsx` (MODIFIED, review round — stale-data-plus-error-banner test)

## Senior Developer Review (AI)

**Date:** 2026-07-27
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers:** Blind Hunter (diff-only), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec) — per CLAUDE.md's BMAD Code Review Gate.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | High (independently re-verified against installed `swr@2.4.2` source) | Edge Case Hunter | SWR's polling loop (`execute()` in `swr/dist/index/index.js`) skips calling `revalidate()` on any tick where the cache already holds an error — it just reschedules the next check without ever re-fetching. The *only* way the cached error clears is `revalidateOnFocus`/`revalidateOnReconnect` firing, or a manual `mutate()`. Combined with `shouldRetryOnError: false` (both hooks' pre-existing setting, unrelated to this story), a single transient poll failure would silently and *permanently* pause auto-refresh until the user blurs/refocuses the tab or the network drops and reconnects — defeating this story's entire purpose. Verified directly against the installed SWR source (not just asserted) given how load-bearing this claim was. | Fixed — restored `shouldRetryOnError` to SWR's own default (`true`) on both hooks. Confirmed via source (`config-context-*.mjs`) that SWR's built-in `onErrorRetry` uses capped exponential backoff (`~random(0.5-1.5) × 2^min(retryCount,8) × errorRetryInterval`), not an unbounded hammering loop — this is exactly the self-healing behavior long-lived polling needs. This required amending this story's own original AC-5 (which had locked `shouldRetryOnError: false` as untouched) — a deliberate, review-driven correction, not an oversight. |
| 2 | High (independently verified by reading the actual page code) | Edge Case Hunter | `library/page.tsx` withheld `<LibraryView>` entirely whenever `error != null`, even though SWR still holds the last-known-good `data` in that case. So the moment finding #1's freeze bug fired, the user didn't just stop seeing updates — they lost the whole library view and saw a blanket failure screen instead. `dashboard/page.tsx` already degraded gracefully (banner + still-rendered stale data); `library/page.tsx` did not, inconsistently. | Fixed — `library/page.tsx` now renders `<LibraryView>` whenever `data` exists regardless of `error`, with a small warning banner ("couldn't refresh... showing your last known results") layered on top when there's also an error, matching `dashboard/page.tsx`'s existing pattern. The "couldn't load your library right now" empty state is now reserved for the genuine no-data-at-all case. |
| 3 | Medium (corroborated 2/3 — Blind Hunter, Edge Case Hunter) | Blind Hunter, Edge Case Hunter | No cap on total polling duration — unlike `UploadFlow.tsx`'s own `MAX_POLL_ATTEMPTS` backstop for the identical underlying risk (a genuinely-stuck backend job, already separately flagged to Dev 1), this story's polling had no ceiling and would run every `LESSON_STATUS_POLL_INTERVAL_MS` indefinitely for as long as the tab stayed open. | Added `MAX_POLL_DURATION_MS` (20 minutes, matching `UploadFlow.tsx`'s own window) and a shared `nextPollInterval()` helper that tracks a per-hook-instance start timestamp via a `useRef`, stopping polling once the ceiling is reached; the window resets once nothing is processing, so a later, separate lesson gets its own fresh window rather than inheriting an already-expired one. |
| 4 | Low (Blind Hunter only, not corroborated, refuted) | Blind Hunter | Claimed the test helper's `useSWRMock.mock.calls[0][2]` reads the *first* recorded mock call rather than the latest, risking stale/wrong config from an earlier, unrelated test. | Refuted — Blind Hunter is diff-only and couldn't see the test file's `beforeEach` block (outside the diff hunk), which calls `useSWRMock.mockReset()` before every single test, clearing call history each time. Within each isolated test, `calls[0]` is correct since exactly one `renderHook()` call happens per test. Confirmed empirically too: all tests pass, including this exact assertion pattern. Not actioned. |
| 5 | Low (Blind Hunter only, not corroborated, refuted) | Blind Hunter | Questioned whether the installed SWR version supports function-form `refreshInterval`, warning of a "silent runaway-polling" failure mode if unsupported. | Refuted — Edge Case Hunter confirmed the installed version is `swr@2.4.2`, whose type definitions explicitly support `refreshInterval?: number \| ((latestData) => number)`, and traced the exact runtime call site (`next()` calls `refreshInterval(getCache().data)`) confirming it behaves exactly as both hooks assume, including receiving `undefined` before the first successful fetch. Not actioned. |
| 6 | Low (Blind Hunter only, not corroborated, refuted) | Blind Hunter | Suggested `useDashboard`'s independent re-derivation of "processing" status (vs. `useLibrary`'s pre-bucketed field) could diverge if the backend's status vocabulary ever changed. | Refuted — Edge Case Hunter verified both hooks' checks are against the exact same closed `LessonStatus` union (`'queued'\|'running'\|'ready'\|'failed'`) already shared via `upload.service.ts`, with no divergence in the current code; this coupling pre-dates this story (both services already imported `LessonStatusResponse` from `upload.service.ts`), not something newly introduced. Not actioned. |
| 7 | Low (Blind Hunter only, not corroborated) | Blind Hunter | `LESSON_STATUS_POLL_INTERVAL_MS` is a hardcoded constant with no per-environment configurability. | Not actioned — matches this codebase's existing convention (`UploadFlow.tsx`'s own `POLL_INTERVAL_MS`/`MAX_POLL_ATTEMPTS` are likewise hardcoded, not env-configurable). |

### Non-issues independently re-verified

- `refreshInterval`'s function-form contract (receives `undefined` pre-fetch, called with `getCache().data` each tick) confirmed correct against actual SWR source by Edge Case Hunter.
- No cache-key collision or interaction with `UploadFlow.tsx`'s own independent polling loop — confirmed it uses a raw service call inside its own component-local effect, never touching SWR's cache at all.
- No stale-closure risk that could freeze polling off permanently — both hooks pass a fresh inline arrow function as `refreshInterval` every render, and SWR's polling effect's dependency array includes `refreshInterval` itself, so it always re-evaluates against current state.
- `isLessonProcessing`'s field/type assumptions confirmed to match the real `LessonStatusResponse`/`LibraryData`/`DashboardData` shapes exactly, field-for-field, by Edge Case Hunter.
- All 7 ACs and all 3 Dev Notes constraints independently re-verified satisfied by the Acceptance Auditor, including an independent `vitest`/`tsc`/`eslint` pass and direct source verification of the Page Visibility API claim.

## Change Log (continued)

| Date | Change | Author |
|------|--------|--------|
| 2026-07-27 | 3-agent code review round. 2 High findings (both from Edge Case Hunter, independently verified against actual SWR source and page code) fixed: `shouldRetryOnError` restored to SWR's default `true` to prevent polling from silently freezing after any transient error (amends this story's original AC-5); `library/page.tsx` now shows stale data + a warning banner instead of hiding the whole page on any error. 1 Medium finding (corroborated 2/3) fixed: added a 20-minute polling-duration cap matching `UploadFlow.tsx`'s own precedent. 3 Low, single-sourced Blind Hunter findings refuted with concrete evidence (test isolation via `beforeEach.mockReset()`, confirmed SWR version/behavior, confirmed no real type divergence) — not actioned. Full suite now 53 files / 506 tests, `tsc`/`eslint` clean. | Dev 2 |
