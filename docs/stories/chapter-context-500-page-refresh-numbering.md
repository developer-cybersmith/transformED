# Story: Chapter-context 500, chapter list not auto-updating, raw 0-based page numbers, and missing dashboard/reports navigation

**Discovered:** 2026-09-24, live verification of chapter/lesson generation on `hieiq.ai`
(triggering "Generate" on a chapter surfaced the first three issues in one session; a
follow-up pass over `/reports` surfaced the next two). Registered as **D183** in
`docs/DEFECT-REGISTER.md`.

## Problems

### 1. `PUT`/`GET .../chapters/{chapter_id}/context` return a real 500

Console/network evidence: `PUT .../chapters/{id}/context` returns `500`, backend log:

```
File "slowapi/extension.py", line 383, in _inject_headers
    raise Exception(
Exception: parameter `response` must be an instance of starlette.responses.Response
```

`slowapi`'s `async_wrapper` only calls `response.headers.append(...)` on the endpoint's own
return value when that value IS itself a `starlette.responses.Response`. Both
`put_chapter_context` and `get_chapter_context` return Pydantic models
(`ChapterContextResponse`) on their success path, so slowapi falls back to
`kwargs.get("response")` to find something to attach headers to — and since neither
function declares a parameter named `response`, that's `None`, which trips the exact
exception above. Every OTHER `@limiter.limit(...)` endpoint in this file
(`upload_lesson`, `generate_chapter_lesson`) already carries both `request: Request` and
`response: Response` — these two were the only ones missing it.

### 2. The chapter list doesn't update on its own after clicking "Generate"

`useChapters`'s SWR `refreshInterval` was keyed ONLY on `bookStatus === 'processing'`
(the book's own ingestion status). Once a book finishes ingestion (`status: 'ready'`),
polling stops dead — permanently — even while an individual chapter's own lesson
generation (triggered separately, per-chapter, via "Generate") is still `queued`/`running`.
The card freezes on "Generating…" until a manual page reload, because nothing is left
polling to notice the transition to `ready`/`failed`. `BookDetail.tsx`'s own copy
("This page updates on its own") states the intended behavior that this bug breaks.

### 3. Page ranges shown as raw 0-based PDF indices

`ChapterRow.tsx` rendered `PDF pages {page_start}–{page_end} (0-based index) · N pages`
using the backend's raw 0-based page index directly — e.g. "PDF pages 11–17 (0-based
index)" for a chapter that starts on the PDF's 12th page. No PDF reader numbers pages
starting from 0; showing the bare 0-based index, with that parenthetical jargon inline,
reads as a bug to a student, not a deliberate design choice.

### 4. `/reports` and `/reports/[sessionId]` render with no Sidebar at all

Both pages lived at `app/reports/page.tsx` / `app/reports/[sessionId]/page.tsx`, physically
OUTSIDE the `(dashboard)` route group every other authenticated page lives under
(`books/`, `upload/`, `dashboard/`, `settings/` each have their own `layout.tsx` rendering
`<Sidebar />` + `<TopUtilityBar />` — there is no shared `(dashboard)/layout.tsx`, so a page
outside the group inherits neither). `ReportsIndex.tsx`'s own top-of-file comment documented
this as a deliberate "standalone page, no dashboard shell" choice — it was a real, if
undocumented-as-a-defect, navigational dead end: no sidebar, and no mobile nav fallback
either (`TopUtilityBar`'s hamburger menu lives in the SAME missing layout).

### 5. The lesson report page (`/reports/[sessionId]`) offers no way back to the dashboard

Independent of #4: even with the sidebar now present, `SessionReport.tsx`'s only in-content
navigation was a single "Back to Reports" link — no path back to `/dashboard` from the page
itself. `ErrorState` (shown when the report fails to load) already has its own "Back to
Dashboard" link, so the gap was specific to the successful-render path.

## Fixes

1. Added `response: Response` to both `put_chapter_context` and `get_chapter_context`.
   Added a source-level AST-scan guard test
   (`test_limiter_response_param.py::test_every_rate_limited_endpoint_declares_a_response_parameter`)
   that flags ANY `@limiter.limit(...)`-decorated endpoint missing a `response` parameter,
   repo-wide — not just the two sites found by hand (Defect Register binding rule 6).
2. `useChapters`'s `refreshInterval` now also continues polling while any currently-loaded
   chapter has `latest_lesson.status` in `queued`/`running` (reusing the existing
   `isLessonProcessing` helper other pages already poll lessons with), in addition to the
   existing `bookStatus === 'processing'` condition.
3. `ChapterRow.tsx` now displays `page_start + 1`–`page_end + 1` ("Pages 70–121"), matching
   how every PDF reader numbers pages by file position. The honest caveat that this may not
   match the book's own PRINTED page numbers (front matter, roman numerals, etc.) moves from
   cluttered inline text into the existing tooltip (`title` attribute).
4. Moved `app/reports/page.tsx` and `app/reports/[sessionId]/page.tsx` into
   `app/(dashboard)/reports/` and added `reports/layout.tsx`, matching the exact
   Sidebar + TopUtilityBar shell every sibling route (`books/`, `upload/`, `settings/`,
   `dashboard/`) already duplicates for itself (no shared `(dashboard)/layout.tsx` exists —
   `books/layout.tsx`'s own comment documents why). `[sessionId]` inherits the new layout the
   same way `books/[id]` already inherits `books/layout.tsx`. `ReportsIndex.tsx`'s stale
   "standalone page, no dashboard shell" comment updated to match.
5. `SessionReport.tsx`'s single "Back to Reports" link is now a breadcrumb
   (`← Dashboard / Reports`), kept in-content and always visible regardless of viewport —
   the Sidebar itself is `hidden lg:flex`, so an inline path back is not redundant with it on
   narrower screens (`TopUtilityBar`'s own mobile menu covers those, but the explicit
   in-content link matches `ErrorState`'s existing "Back to Dashboard" precedent and is what
   was directly asked for).

## Feature added in the same PR: sidebar collapse/expand toggle

Requested directly, not a defect fix. `Sidebar.tsx` gained a collapse toggle (arrow icon,
`ChevronLeft`/`ChevronRight` from `lucide-react` — the convention already used elsewhere for
directional disclosure, e.g. `ChapterRow.tsx`'s expand/collapse chevrons):

- Defaults to expanded (full labels visible).
- Collapsing shrinks the sidebar to an icon rail (`w-20`); each nav item and the Account
  button keep their FULL accessible name via `aria-label` even when collapsed (a Radix
  `Tooltip` alone is visual-only and does not label the underlying control for assistive
  tech — caught by `Sidebar.test.tsx`'s own new coverage before it shipped).
- Hovering an icon in the collapsed state shows its label in a tooltip (reuses the existing
  `components/ui/tooltip.tsx` Radix wrapper, same local-`TooltipProvider`-per-usage pattern
  `JargonHover.tsx` already established — no new dependency).
- The choice persists to `localStorage` (`hie:sidebar-collapsed`), because the sidebar is
  duplicated per top-level route (see #4's fix note) — every navigation between
  Dashboard/Books/Upload/Reports/Settings mounts a FRESH `<Sidebar />`, so plain `useState`
  would silently re-expand on every click-through. Read/write follows
  `useAttentionConsent.ts`'s guarded try/catch pattern (storage unavailable → fails to the
  safe, fully-visible default, never stuck hidden).

## Incidental fixes (found while adding test coverage for #1, in the same file)

- `tests/test_s5_3_endpoints.py` had NO reset between test cases for `limiter`'s module-level
  `memory://` storage, so rate-limit state leaked across test methods within the same pytest
  process — the "3/minute" PUT budget was already exhausted by the 4th PUT call in file order,
  regardless of what that specific test was checking. **Confirmed pre-existing** (reproduces
  identically on `main` before this story's fix, via `git stash` + rerun). Added an autouse
  `_reset_rate_limiter` fixture.
- `test_put_fk_violation_returns_404` used `MagicMock(spec=APIError)` as a mock `side_effect`
  — a `Mock` (even `spec`'d) is not an actual exception instance, so `raise`-ing it fails with
  `TypeError: exceptions must derive from BaseException`. This was masked by the rate-limiter
  leak above (the test never got far enough to hit it). Replaced with a real
  `APIError({"code": "23503", ...})` instance.

Both were surfaced ONLY once the primary bug (#1) was fixed and the test's real assertions
could finally run — not scope creep, but the direct, unavoidable consequence of no longer
masking them (Defect Register: "9 of 11 pre-existing defects never worked for one minute" —
the same pattern recurring here in miniature).

## Acceptance Criteria

1. **AC1**: `PUT`/`GET .../chapters/{chapter_id}/context` return their documented status
   codes (200/204/404) on every success path a real user can reach — never a 500 from the
   rate-limiter's own header-injection machinery.
2. **AC2**: `test_limiter_response_param.py` fails CI if any current or future
   `@limiter.limit(...)`-decorated endpoint in `app/` lacks a `response: Response` parameter.
3. **AC3**: `useChapters`'s poll continues while any loaded chapter has a lesson `queued` or
   `running`, and stops once the book is `ready` AND no chapter has a lesson actively
   generating — covered by both directions in `useChapters.test.ts`.
4. **AC4**: `ChapterRow` displays 1-based page numbers; the 0-based-vs-printed-page caveat
   lives in the tooltip, not inline text.
5. **AC5**: `tests/test_s5_3_endpoints.py` passes deterministically, run alone or combined
   with other test files, with no rate-limit-state leakage between test cases.
6. **AC6**: `/reports` and `/reports/[sessionId]` render the same Sidebar + TopUtilityBar
   shell as every other authenticated route — verified by a real `next build`'s route list
   (both routes present, no collision, `[sessionId]` still dynamic) plus the existing
   route-level tests (updated import paths, still passing).
7. **AC7**: `SessionReport.tsx` offers an in-content link to `/dashboard`, not only
   `/reports` — covered in `SessionReport.test.tsx`.
8. **AC8**: The sidebar collapse toggle: (a) defaults expanded, (b) hides labels and shows a
   tooltip on hover when collapsed, (c) every collapsed nav control keeps a real accessible
   name via `aria-label` (not tooltip-only), (d) persists across a full unmount/remount
   (simulating the real per-route Sidebar remount) via `localStorage` — all four covered in
   `Sidebar.test.tsx`.

## Scale & Load

1. **Unit of work & range**: one PUT/GET call per chapter-context save/load (unchanged rate
   limits: 3/min;20/hr and 30/min;200/hr respectively); one extra `Array.some()` scan over the
   currently-loaded chapter list per SWR poll tick (bounded by the same per-book chapter count
   every other chapter-list render already iterates).
2. **Fixed budgets vs. variable input**: no new budgets introduced. The existing
   `MAX_POLL_DURATION_MS` (~20 min) ceiling in `lessonStatusPoll.ts` already bounds how long
   `useChapters` polls once triggered — unchanged by this fix, now correctly ALSO triggered
   by chapter-level lesson generation, not just book-level ingestion.
3. **Scope of limits**: per-user, per-book — unchanged. The `response: Response` fix changes
   nothing about the rate-limit ceiling itself, only whether the endpoint can return
   successfully at all.
4. **Unbounded reads/writes**: none introduced. `useChapters`'s new `.some()` check runs over
   already-fetched, already-bounded client-side data (the same list already rendered).
5. **Inherited caps re-derived?**: N/A.
6. **Concurrent-request safety**: N/A — no new server-side state or check-then-act sequence;
   the rate-limiter reset fixture only affects test isolation, not production behavior.

## Out of scope

- Redis-backed rate-limit storage tests (`test_rate_limit_redis_storage.py`) were found
  failing (`fakeredis`'s `evalsha` command unimplemented) while running the broader suite —
  confirmed pre-existing via `git stash` + rerun, unrelated to this story's files, not fixed
  here.
