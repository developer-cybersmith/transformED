# Story: Chapter-context 500, chapter list not auto-updating, and raw 0-based page numbers in the UI

**Discovered:** 2026-09-24, live verification of chapter/lesson generation on `hieiq.ai`
(triggering "Generate" on a chapter surfaced all three issues in one session). Registered
as **D183** in `docs/DEFECT-REGISTER.md`.

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
