---
baseline_commit: "3891a0edd75991375301ffc146d138579dda0d5e"
---

# Story 1-9: Library Real Data Integration

Status: ready-for-dev

## Story

As a student viewing my library,
I want to see my actual uploaded lessons (with real generation status) instead of mock data,
so that the library page reflects what I've actually uploaded and whether it's ready to study.

## Context

This is Sprint 1 task **S1-09** from `docs/dev2-sprint-tracker.md` — previously blocked on Dev 1's backend, picked back up now that `sprint1/s1-8-upload-real-api` (PR #73) is merged to `main`. Requested directly by the user ("wire the 2 pending APIs in the dashboard and the library") alongside its sibling, **S1-10** (Dashboard — separate story, branches from this one once merged to the feature master).

**This story's original tracker sketch is wrong in the same way S1-08's was** — written before Dev 1's backend existed, it assumed `GET /api/lessons` returning rich data. Verified the real, live backend directly (`apps/api/app/modules/content/router.py`) before writing this story, not assumed from docs:

### The real backend contract (confirmed by reading the code, not docs)

- **`GET /api/content/lessons?limit=&offset=`** (`content/router.py:276-299`) — the only list endpoint. Real, working, user-scoped (`.eq("user_id", user_id)` — filters to the JWT's own user, not global). `limit` defaults 20, max 200; `offset` defaults 0. Ordered `created_at` descending (newest first) — **hardcoded, no `sort` param**. **No `status` query filter** — if you need "only failed lessons," filter client-side after fetching.
- **Response shape** (`LessonStatusResponse`, already defined and exported from `apps/web/src/services/upload.service.ts` — reuse it, do not redefine): `{ lesson_id: string, status: 'queued'|'running'|'ready'|'failed', title: string | null, error: string | null, created_at: string | null, completed_at: string | null }`.
- **No thumbnail, no duration, no "chapter title," no student reading-progress percentage exist anywhere** — not in this response, not in any other endpoint, not even as a column in the `lessons` table (`supabase/migrations/20260611000000_initial_schema.sql:86-96`: only `lesson_id, user_id, title, status, content jsonb, source_file_path, created_at, updated_at` — no `thumbnail_url`, no `duration_minutes`). The mock `MockLesson` shape (`chapterTitle`, `durationSeconds`, `progressPercent`, `thumbnailUrl`, `slides`, `timeline`) has **no real counterpart at all**. This story replaces the whole `LibraryView`/`LibraryCard` visual design with one that only shows what's actually available: title, status, created-at.
- **The mock's 4 status buckets don't map to reality.** Mock statuses were `completed | in_progress | processing | failed` — a *student's reading progress* concept. The real `status` field is a *generation pipeline* concept: `queued | running | ready | failed`. There is no backend concept of "in progress reading" vs. "done reading" at all (that would need session data — see Dev Notes below). Map real statuses to tabs: **All / Generating (queued+running, combined) / Ready / Failed** — this actually matches the tracker's own AC wording ("Generating / Ready / Failed") better than the old mock's bucketing did.
- **No retry endpoint exists.** The tracker's AC says "Failed lessons show a Retry button" — there is no `POST /api/content/lessons/{id}/retry` or equivalent anywhere in `apps/api`. A failed lesson's original file isn't retained client-side either (it was only ever an in-memory `File` object during the original upload). **Descoped to a "Upload Again" button that routes to `/upload`** — a fresh upload, not an in-place retry. Documented here so this isn't mistaken for an oversight later.
- **Auth is real, not a TODO** — `get_current_user` (`apps/api/app/dependencies.py:48-112`) validates the Supabase JWT and every content route requires it. This is genuinely enforced (404-on-ownership-mismatch, not just decorative).

### A real gap this story must fix first: server-side requests never carry the JWT today

`apps/web/src/lib/api.ts`'s request interceptor only attaches `Authorization` `if (typeof window !== 'undefined')` (line 19). **`/library`'s page component is an `async` Server Component** (`apps/web/src/app/(dashboard)/library/page.tsx` — no `"use client"`, calls `libraryService.getLibrary()` directly during server render). Any real backend call made from there today would go out with **no Authorization header at all** and 401. This is a real, previously-undiscovered gap, not a hypothetical — Server Components run with `window === undefined`, so the interceptor's guard silently skips them.

**Fix:** a new server-only helper, `apps/web/src/lib/api.server.ts`, that reads the session via the existing `apps/web/src/lib/supabase/server.ts` (Next.js `cookies()`-based server client — already exists, already used by `middleware.ts`) and returns an axios instance with the Authorization header already set. Used only by the initial server-rendered fetch. Any *client-side* pagination ("Load more") reuses the existing, already-working `apps/web/src/lib/api.ts` client instance directly (it already attaches the token correctly in the browser — proven by `UploadFlow.tsx`'s polling, which already works this way) — **do not invent a second client-side API client.**

## Acceptance Criteria

1. **New `apps/web/src/lib/api.server.ts`**: exports an async `getServerApi()` that returns an axios instance (same `baseURL` as `lib/api.ts`) with `Authorization: Bearer <token>` set from the current server-side Supabase session (via `lib/supabase/server.ts`), or no Authorization header if there's no session. Server-only (imports `next/headers` transitively) — must never be imported from a `"use client"` file.
2. **New `apps/web/src/services/lessons.service.ts`**: exports `lessonsService.listLessons({ limit, offset }): Promise<LessonStatusResponse[]>` calling `GET content/lessons` via `getServerApi()`, reusing the existing `LessonStatus`/`LessonStatusResponse` types exported from `apps/web/src/services/upload.service.ts` (do not redefine them).
3. **`library.service.ts` rewritten** to fetch real data:
   - `LibraryData` becomes `{ lessons: LessonStatusResponse[] }` (replacing the old `{inProgress, completed, processing, failed}` mock-shape buckets).
   - `getLibrary()` fetches an initial page (limit **24**, offset **0**) via `lessonsService.listLessons`, wraps success/failure in the existing `ApiResponse<T>` envelope (`createSuccessResponse`/`createErrorResponse` from `apps/web/src/mocks/utils/response.ts` — reuse, this is a generic response envelope, not lesson mock data) exactly as today, so `LibraryDataFetcher`'s existing success/failure branching in `library/page.tsx` needs no changes.
4. **`LibraryView.tsx` + `LibraryCard` rewritten for the real, sparse data shape:**
   - Tabs: **All / Generating / Ready / Failed** — "Generating" = `status === 'queued' || status === 'running'`.
   - Each card shows: `title` (fallback **"Untitled Lesson"** when `null`, which happens while `status !== 'ready'`), a status badge (Generating/Ready/Failed — reuse the existing spinner/checkmark/alert visual language already in the current `LibraryCard`), and "Created {formatTimeAgo(created_at)}" (new helper, see AC #6). **No thumbnail image, no duration, no progress bar** — none of that data exists.
   - Ready cards are clickable → `/lesson/{lesson_id}`, same as today.
   - Generating cards are not clickable (same non-interactive treatment as today's "processing" cards).
   - Failed cards show the `error` message (fallback **"Generation failed — please try again."** when `error` is `null`) and an **"Upload Again"** button that routes to `/upload` (not a retry — see Context above).
   - Empty states: no lessons at all → "No lessons yet — upload your first PDF to get started," with a CTA linking to `/upload`; a tab with zero matching lessons (but the library isn't empty overall) → the existing "No lessons found in this category" copy is fine, keep it.
5. **Pagination ("Load more"):** `LibraryView` (already `"use client"`) holds the fetched lesson list in state, seeded from `initialData.lessons`. A "Load more" button appears when the most recently fetched page returned exactly `limit` (24) items (a length-based heuristic — the API has no total count to check against) and fetches the next page directly via the existing client-side `apps/web/src/lib/api.ts` instance (`api.get('content/lessons', { params: { limit: 24, offset: <current count> } })`) — **not** `getServerApi()`, which cannot run client-side. Newly fetched lessons are appended; the button hides once a page returns fewer than 24.
6. **New `formatLessonStatusLabel` helper** in `apps/web/src/lib/utils.ts` (matching the existing `formatCesLabel`/`formatTeachbackLabel` pattern): maps `'queued'|'running'` → `"Generating"`, `'ready'` → `"Ready"`, `'failed'` → `"Failed"`.
7. **Tests:**
   - `lessons.service.test.ts`: `listLessons` calls `content/lessons` with the right `limit`/`offset` params via the server API and returns the array.
   - `library.service.test.ts`: updated/rewritten for the new `LibraryData` shape and real fetch, success + failure paths.
   - `LibraryView.test.tsx` (new or rewritten): tab filtering (All/Generating/Ready/Failed) and counts, Ready card navigates on click, Generating card is not clickable, Failed card shows its error + "Upload Again" links to `/upload`, empty states (fully empty vs. empty-tab), "Load more" appears/fetches/hides correctly.
   - `apps/web/src/__tests__/app/library/page.test.tsx`: update the two existing tests' mocked `LibraryData` shape to `{ lessons: [...] }`; both should still pass with the same success/failure branching logic, unchanged in `page.tsx` itself.
8. **No regression:** full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean (0 new warnings). `apps/web/src/services/upload.service.ts` (and its exported types) are read from, never modified, by this story.

## Tasks / Subtasks

- [ ] Task 1: Server-side authenticated API client (AC: #1)
  - [ ] 1.1 Write failing test first (RED) for `getServerApi()` — attaches `Authorization` when a session exists, omits it when there's none
  - [ ] 1.2 Implement `apps/web/src/lib/api.server.ts` (GREEN)
- [ ] Task 2: `lessons.service.ts` (AC: #2)
  - [ ] 2.1 RED — `listLessons` calls `content/lessons` with correct params, returns the response array
  - [ ] 2.2 Implement (GREEN)
- [ ] Task 3: `library.service.ts` real wiring (AC: #3)
  - [ ] 3.1 RED — success/failure paths against the new `LibraryData` shape
  - [ ] 3.2 Implement (GREEN)
- [ ] Task 4: Rewrite `LibraryView`/`LibraryCard` for real, sparse data (AC: #4, #6)
  - [ ] 4.1 RED — tabs/counts/click-behavior/empty-states/formatLessonStatusLabel tests
  - [ ] 4.2 Implement (GREEN)
- [ ] Task 5: Pagination (AC: #5)
  - [ ] 5.1 RED — "Load more" appears/fetches-next-page/appends/hides-at-short-page tests
  - [ ] 5.2 Implement (GREEN)
- [ ] Task 6: Update existing `library/page.test.tsx` for the new data shape (AC: #7)
- [ ] Task 7: Full verification (AC: #8)
  - [ ] 7.1 Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean
- [ ] Task 8: Tracker update
  - [ ] 8.1 Mark S1-09 in `docs/dev2-sprint-tracker.md` as done

## Dev Notes

### Files this story touches

- `apps/web/src/lib/api.server.ts` (NEW)
- `apps/web/src/services/lessons.service.ts` (NEW)
- `apps/web/src/services/library.service.ts` (MODIFY — real fetch, new `LibraryData` shape)
- `apps/web/src/components/library/LibraryView.tsx` (MODIFY — full rewrite for real/sparse data, tabs, pagination)
- `apps/web/src/lib/utils.ts` (MODIFY — add `formatLessonStatusLabel`)
- `apps/web/src/__tests__/services/lessons.service.test.ts` (NEW)
- `apps/web/src/__tests__/services/library.service.test.ts` (MODIFY or NEW, depending on current file)
- `apps/web/src/__tests__/components/library/LibraryView.test.tsx` (NEW or rewritten)
- `apps/web/src/__tests__/app/library/page.test.tsx` (MODIFY — new `LibraryData` shape in mocks)
- `docs/dev2-sprint-tracker.md` (MODIFY — mark S1-09 done)

### Branch / merge convention

Branch `sprint1/s1-9-library-real-api`, branched from `main` (which now has `sprint1/s1-8-upload-real-api` merged, PR #73). Feeds into a new dedicated feature master, **`feature-real-data-integration`** (created off `main`), which also gets S1-10 (Dashboard). Task branches stay local; only `feature-real-data-integration` is pushed, same convention as `feature-learner-mode`.

### What NOT to do

- Do NOT invent a thumbnail, duration, or chapter-title field client-side (e.g. deriving a fake duration from something) — none of that data exists server-side; showing fabricated data would be worse than showing nothing.
- Do NOT build a real "Retry" (resubmit-the-same-upload) mechanism — no backend support exists; "Upload Again" → `/upload` is the honest scope.
- Do NOT modify `apps/web/src/services/upload.service.ts` — only read its exported `LessonStatus`/`LessonStatusResponse` types and reuse them.
- Do NOT use `getServerApi()` from any `"use client"` component — it depends on `next/headers`, server-only. Client-side pagination reuses the existing `lib/api.ts` client instance instead.
- Do NOT touch the Dashboard (`dashboard.service.ts`, dashboard components) — that's S1-10, a separate story that starts after this one merges to `feature-real-data-integration` (it will reuse `lessons.service.ts`).
- Do NOT touch Continue-Learning or Learning Pulse anywhere — out of scope for both S1-09 and S1-10 per explicit user decision (no backend data source exists for either; they stay mocked).

### Project Structure Notes

No conflicts with `packages/shared` frozen contracts. `library.service.ts`'s public shape (`getLibrary(): Promise<ApiResponse<LibraryData>>`) is preserved so `library/page.tsx` needs zero changes — only `LibraryData`'s internal shape changes, which `LibraryView` (already receiving `initialData` as a prop) absorbs.

### References

- [Source: docs/dev2-sprint-tracker.md#S1-09 — Library Real Data Integration] (original sketch — assumed a `GET /api/lessons` shape that doesn't exist; superseded by this story per the real contract above)
- [Source: apps/api/app/modules/content/router.py] (real, verified backend contract)
- [Source: supabase/migrations/20260611000000_initial_schema.sql] (real `lessons` table schema — confirms no thumbnail/duration columns)
- [Source: apps/web/src/services/upload.service.ts] (reuse `LessonStatus`/`LessonStatusResponse` — do not redefine)
- [Source: apps/web/src/lib/api.ts] (the client-side interceptor gap this story fixes with a server-only counterpart)
- [Source: apps/web/src/lib/supabase/server.ts] (existing server Supabase client `api.server.ts` builds on)
- [Source: docs/stories/1-8-upload-real-api.md] (precedent for correcting a stale sketch against the real backend, and for the "no percentage/stage — just Processing..." UI pattern this story's "Generating" status follows)

## Dev Agent Record

### Agent Model Used

_To be filled in during implementation._

### Debug Log References

_To be filled in during implementation._

### Completion Notes List

_To be filled in during implementation._

### File List

_To be filled in during implementation._

### Change Log

- 2026-07-14: Story created — Sprint 1 remainder task S1-09, branch `sprint1/s1-9-library-real-api` off `main`, feeding into new feature master `feature-real-data-integration`.
