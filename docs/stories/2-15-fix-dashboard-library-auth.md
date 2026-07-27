---
baseline_commit: 4831d35a18b72eda9e21b563066a6f36f244dcc8
---

# Story 2.15: Fix Dashboard/Library 401 — Move Real Data Fetching Client-Side

Status: ready-for-dev

## Story

As a student,
I want the dashboard and library pages to actually load my real lessons,
so that Story 2-14's real-backend wiring works when I actually use it, not just in tests.

**Source:** live end-to-end testing immediately after merging Story 2-14 hit a hard failure — first a 404 (traced to an unrelated Django/Daphne process occupying port 8000, not a code issue; resolved by the user stopping that process), then a **401 Unauthorized** once the real FastAPI backend was actually running. The 401 is a genuine bug in Story 2-14's implementation.

**Root cause:** `dashboard/page.tsx` and `library/page.tsx` were written as Next.js **Server Components** (`export default async function ...`), calling `dashboardService.getDashboard()`/`libraryService.getLibrary()` directly during server-side rendering. But `apps/web/src/lib/api.ts`'s request interceptor only attaches a Bearer token when `typeof window !== 'undefined'`:

```ts
api.interceptors.request.use(async (config) => {
    if (typeof window !== 'undefined') {
        const supabase = createClient();
        const { data } = await supabase.auth.getSession();
        if (data.session?.access_token) {
            config.headers.Authorization = `Bearer ${data.session.access_token}`;
        }
    }
    return config;
});
```

A Server Component runs in Node.js — `window` is never defined there — so every real API call made from `dashboard/page.tsx`/`library/page.tsx` went out with no Authorization header at all, and the backend's `CurrentUser` dependency correctly rejected it with 401.

**Confirmed this is a real, pre-existing architectural constraint, not something new to invent a workaround for:** every other real, authenticated API integration in this codebase is already a **Client Component** for exactly this reason — `apps/web/src/hooks/useLesson.ts` (`'use client'`, used by `PlayerLoader.tsx`) and `apps/web/src/hooks/useSessionReport.ts` (`'use client'`, SWR-based) both fetch real data entirely in the browser. Story 2-14 broke this established pattern by putting the fetch in a Server Component.

## Acceptance Criteria

1. **AC-1** — `dashboard/page.tsx` and `library/page.tsx` fetch their real data client-side, matching `useSessionReport.ts`'s established SWR pattern, not server-side.
2. **AC-2** — Two new hooks, `useDashboard()` and `useLibrary()`, wrap `dashboardService.getDashboard()`/`libraryService.getLibrary()` via SWR with `shouldRetryOnError: false` (matching `useSessionReport`'s rationale: a permanently-failing endpoint must not hammer the backend on a growing retry loop).
3. **AC-3** — Both pages preserve their existing UX: `dashboard/page.tsx` shows an inline error banner on a real fetch failure (from Story 2-14's review round) instead of a silent, indistinguishable-from-empty state; `library/page.tsx` shows its existing "Loading intelligence..." loading state and "We couldn't load your library right now." failure state — now driven by the hook's `isLoading`/`error` instead of a server-side `Suspense`/try-catch.
4. **AC-4** — No regression to Story 2-14's other fixes (dedup, wider lookup window, mock-pulse isolation, `all`-field robustness) — those live in the services, untouched by this story.
5. **AC-5** — Tests: both new hooks have dedicated tests (mocking `swr`'s default export directly, per `useSessionReport.test.ts`'s established pattern); `library/page.test.tsx` is rewritten to mock the `useLibrary` hook directly (its old approach tested a `LibraryDataFetcher` server function that no longer exists after this story).
6. **AC-6** — No regressions: full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file.

## Tasks / Subtasks

- [x] Task 1 (AC: 2, 5): Create `useDashboard()` hook + tests.
  - [x] 1.1 RED: hook doesn't exist, import fails.
  - [x] 1.2 GREEN.
- [x] Task 2 (AC: 2, 5): Create `useLibrary()` hook + tests.
  - [x] 2.1 RED, 2.2 GREEN — same pattern as Task 1.
- [x] Task 3 (AC: 1, 3): Convert `dashboard/page.tsx` to a Client Component using `useDashboard()`.
- [x] Task 4 (AC: 1, 3, 5): Convert `library/page.tsx` to a Client Component using `useLibrary()`; rewrite `library/page.test.tsx` to mock the hook instead of the now-removed `LibraryDataFetcher`.
- [x] Task 5 (AC: 6): Full `apps/web` suite green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### Current state of every file this story touches (read directly, not assumed)

- **`apps/web/src/lib/api.ts`** — confirmed the exact root cause: `if (typeof window !== 'undefined')` gates the entire auth-header attachment.
- **`apps/web/src/hooks/useSessionReport.ts`** — the reference pattern this story copies exactly: `'use client'`, `useSWR(key, fetcher, { shouldRetryOnError: false })`, returns `{data ?? null, isLoading, error}`.
- **`apps/web/src/hooks/useLesson.ts`**, **`apps/web/src/components/player/PlayerLoader.tsx`** — confirmed both `'use client'`, the other precedent for "real API calls are always client-side here."
- **`apps/web/src/app/(dashboard)/dashboard/page.tsx`** (pre-this-story) — a Server Component directly `await`ing `dashboardService.getDashboard()` in a try/catch, added in Story 2-14's review round to show an inline error banner. That banner UX is preserved, just now driven by SWR's `error`.
- **`apps/web/src/app/(dashboard)/library/page.tsx`** (pre-this-story) — a Server Component with a separate exported `LibraryDataFetcher` async function, wrapped in `<Suspense>` for streaming. This story removes the `Suspense`/streaming structure entirely (it only ever made sense for a genuinely server-rendered fetch) in favor of a single client component managing `isLoading`/`error`/`data` states directly — the same three states `Suspense` + try/catch were approximating, just correctly authenticated now.
- **`apps/web/src/__tests__/app/library/page.test.tsx`** — previously tested `LibraryDataFetcher` (a named export that no longer exists after this story); rewritten to render the default-exported `LibraryPage` and mock `@/hooks/useLibrary` directly.

### What NOT to do

- Do NOT attempt to make the Server Component path work by reading the Supabase session server-side (e.g. via `@/lib/supabase/server.ts` + `next/headers`'s `cookies()`) — that would be a *new* pattern not used anywhere else in this codebase for real, authenticated data; the client-side hook approach is the established, working precedent (`useLesson`, `useSessionReport`) and keeps this fix minimal and consistent.
- Do NOT touch `dashboard.service.ts`/`library.service.ts` — Story 2-14's fixes there (dedup, wider window, mock-pulse isolation, `all` field) are correct and untouched; this story only changes *where* they're called from.
- Do NOT re-introduce server-side `Suspense` streaming for `library/page.tsx` — it's incompatible with the client-side auth requirement.

### Testing standards

Vitest. For the two new hooks, mock `swr`'s default export directly (`vi.mock('swr', () => ({ default: useSWRMock }))`) exactly as `useSessionReport.test.ts` does — do not attempt to exercise real SWR async/caching behavior, since these are thin passthrough hooks and the interesting logic (dedup, window sizing, mock isolation) is already tested at the service level in Story 2-14.

### References

- [Source: this session's live end-to-end test, immediately after merging Story 2-14] — the 401 this story fixes
- [Source: apps/web/src/lib/api.ts] — the exact root-cause line (`typeof window !== 'undefined'`)
- [Source: apps/web/src/hooks/useSessionReport.ts, apps/web/src/hooks/useLesson.ts] — the established client-side-fetch precedent this story now also follows
- [Source: docs/stories/2-14-real-dashboard-library.md] — the story this fixes a regression in

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-27 | Story created immediately after Story 2-14 was found broken in live testing (401 on both pages). Root-caused to Server Components being unable to use `api.ts`'s browser-only auth interceptor. Branch `sprint2/s2-15-fix-dashboard-library-auth` off `sprint2-master`. Implemented same-session given the user was actively blocked: both pages converted to Client Components using two new SWR-based hooks (`useDashboard`, `useLibrary`), matching the established `useSessionReport`/`useLesson` pattern. Full suite 52 files / 462 tests passing, `tsc --noEmit` and `eslint` clean. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Root-caused via direct reproduction: confirmed `/health` (a zero-dependency route) also 404'd before the user restarted their backend, then got a clean 401 once the real FastAPI process was actually running — proving the auth header was genuinely missing, not a routing issue.
- Chose the client-side-hook fix over a server-side-Supabase-session alternative specifically because it's the *already-established* pattern in this codebase (`useLesson`, `useSessionReport`), not a new mechanism — minimizes risk and keeps the auth model consistent across the whole app.
- `library/page.tsx`'s `Suspense`+`LibraryDataFetcher` streaming structure was removed entirely — it only made sense for a genuine server-side fetch, which is no longer possible here. Replaced with a single client component managing the same three states (`isLoading`/`error`/`data`) directly.

### Completion Notes

- All 5 tasks complete, all ACs (1–6) satisfied.
- Full `apps/web` test suite: 52 files, 462 tests, all passing.
- `tsc --noEmit`: clean. `eslint` on all touched files: clean.
- No changes to `dashboard.service.ts`/`library.service.ts` — Story 2-14's fixes there are untouched.

### File List

- `apps/web/src/hooks/useDashboard.ts` (NEW)
- `apps/web/src/hooks/useLibrary.ts` (NEW)
- `apps/web/src/app/(dashboard)/dashboard/page.tsx` (MODIFIED — Server → Client Component)
- `apps/web/src/app/(dashboard)/library/page.tsx` (MODIFIED — Server → Client Component, removed `Suspense`/`LibraryDataFetcher`)
- `apps/web/src/__tests__/hooks/useDashboard.test.ts` (NEW)
- `apps/web/src/__tests__/hooks/useLibrary.test.ts` (NEW)
- `apps/web/src/__tests__/app/library/page.test.tsx` (MODIFIED — rewritten against the new hook-based page)
