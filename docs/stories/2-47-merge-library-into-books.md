---
baseline_commit: c06ed81
---

# Story 2.47: Fold My Library into My Books (S4-06)

Status: done

## Story

As a student browsing my uploaded books,
I want to see every lesson generated for a chapter — not just the newest one —
so that I can reach an older-tier or previous lesson attempt without a separate "Library"
section that duplicates the same underlying data.

**Source:** Product decision made in a live session with the user, 2026-08-17. The user noticed
`My Books` (`/books`) and `My Library` (`/library`) both surface lesson data and asked whether
Library is still needed now that Books shows chapters. Investigated directly against the running
code (not the tracker's description of either page) before answering:

- **Books** (`/books` → `/books/[id]`) lists a book's chapters (`useChapters` →
  `booksService.listChapters`) and renders one `ChapterRow` per chapter. Each row shows
  `lesson_count` and the chapter's **single newest lesson only**
  (`chapter.latest_lesson`) — gated strictly on `latest_lesson.status === 'ready'`, never on
  `has_lesson` (`watchableLessonId` in `books.service.ts`; a chapter whose only lesson failed
  still has `has_lesson: true` and a non-null `lesson_id`, and linking to it would 404 the player).
- **Library** (`/library`) fetches `GET content/lessons?limit=100` — every lesson row for the
  user, flat, across every book, with no chapter/book grouping — bucketed into All/Ready/
  Processing/Failed tabs (`libraryService.getLibrary`). It has no unique action Books lacks (no
  retry button, nothing else); it is purely a different *view* of lesson data Books already has
  access to.
- **The one real gap:** `apps/api/app/modules/content/router.py`'s `_CHAPTER_COLUMNS` query
  already embeds **every** lesson for the chapter in one round trip
  (`lessons!lessons_chapter_id_fkey(lesson_id,status,tier,created_at)`) — `_row_to_chapter_response`
  computes `lesson_count = len(lessons)` from that full list, but then discards every row except
  the newest (`_latest_lesson`) before building `ChapterResponse`. **The backend already fetches
  the data this story needs; it just never serializes it out.** Today, Library's flat list is the
  *only* UI path to reach a non-latest lesson (a different tier, or a retry after a failure).

**Decision:** fold that one capability into Books (expose all lessons per chapter, not just the
latest) and retire the standalone Library page — this is Dev 2's own frontend territory, plus a
small, explicitly user-approved excursion into the backend (`content/router.py` is normally Dev
1's module; the user explicitly asked for the backend to be updated in this same branch).

## Acceptance Criteria

1. **AC-1 (backend)** — `ChapterResponse` (`apps/api/app/modules/content/router.py`) gains one
   new, additive field: `lessons: list[LatestLesson]` — every lesson for the chapter (all tiers,
   all states), **newest-first**, derived from the exact same `lessons` embed
   `_row_to_chapter_response` already receives via `_CHAPTER_COLUMNS` (no second Supabase call).
   Existing fields (`lesson_id`, `has_lesson`, `lesson_count`, `latest_lesson`) are computed
   exactly as today, unchanged in shape or value — this field is purely additive.
2. **AC-2 (backend, Scale & Load finding — see below)** — the new `lessons` field is capped at
   **20 entries** (newest-first, so the cap keeps the most relevant rows) via an in-Python slice
   after the existing embed is fetched — not a new query, and not a change to `lesson_count`
   (which continues to report the TRUE total even past the cap). `# BOUNDED:` comment explaining
   why 20 is a safety ceiling, not the natural bound (see Scale & Load Q1/Q2).
3. **AC-3 (backend)** — `docs/contracts/book-api.v1.json` bumped to the next version with a
   changelog entry documenting the new additive `ChapterResponse.lessons` field, matching the
   pattern already used for `GenerateLessonRequest.force` (D54's contract catch-up).
4. **AC-4 (backend tests)** — a chapter fixture with lessons across 2+ tiers/states returns all of
   them in `lessons`, newest-first; a fixture with >20 lessons returns exactly 20 (newest),
   `lesson_count` still reports the true total; a chapter with zero lessons returns `lessons: []`
   (never `null` — consistent with `has_lesson`/`lesson_count` already treating zero as a valid,
   non-null state). Existing `latest_lesson`/`lesson_count`/`has_lesson` assertions in
   `tests/unit/test_book_endpoints.py` (or wherever they currently live) must pass unmodified.
5. **AC-5 (frontend types)** — `ChapterResponse` in `apps/web/src/services/books.service.ts` gains
   the matching `lessons: LatestLesson[]` field, verified field-for-field against the real
   (just-changed) Python model — not assumed from this story's prose.
6. **AC-6 (frontend UI)** — `ChapterRow.tsx`: when `chapter.lessons.length > 1`, render an
   expandable "N other lessons" affordance listing each non-latest lesson's tier + status, each
   with its own Watch link gated the *same* way as today's single Watch button — `status ===
   'ready'` only, never on presence alone (generalize `watchableLessonId`'s safety rule to each
   list entry, don't just apply it to the latest one). When `lessons.length <= 1`, the row renders
   exactly as it does today (no visual regression for the common case).
7. **AC-7 (removal)** — Delete the standalone Library feature entirely, not just unlink it:
   `apps/web/src/app/(dashboard)/library/` (`page.tsx` + `layout.tsx`), `hooks/useLibrary.ts`,
   `services/library.service.ts`, `components/library/LibraryView.tsx`, and their dedicated test
   files (`__tests__/app/library/page.test.tsx`, `__tests__/hooks/useLibrary.test.ts`,
   `__tests__/services/library.service.test.ts`, `__tests__/components/library/LibraryView.test.tsx`).
   Remove the `libraryService` export from `services/index.ts` and the `/library` mock handlers
   from `mocks/api/index.ts` / `mocks/api/library.ts`.
8. **AC-8 (nav + cross-links)** — Remove the "My Library" entry from `Sidebar.tsx`'s
   `mainNavItems`. Redirect every remaining `/library` reference to `/books`:
   `RecentLessons.tsx`'s "View All" button, and `ContinueLearningCard.tsx`/`QuickActions.tsx` if
   they also link there (verify each directly — don't assume symmetry). `proxy.ts`'s deny-list
   needs no functional change (it protects routes by NOT being on an allow-list; deleting
   `/library` just means that path no longer exists) — but its comment referencing `/library` as
   historical context may be updated for accuracy, not correctness.
9. **AC-9 (no dead references)** — After removal, `grep -r "useLibrary\|libraryService\|LibraryView\|'/library'\|"/library""` across `apps/web/src` returns zero hits.
10. **AC-10 (tests)** — Backend: full `apps/api` suite green via the established worktree-baseline
    comparison (net-new failures = 0 against pre-story `main`), `ruff check`/`ruff format --check`/
    `mypy app` all clean (all three are real CI gates now — see `docs/DEFECT-REGISTER.md` D110–D114
    for why this matters). Frontend: full `apps/web` suite green after removing the ~4 library test
    files and updating `Sidebar.test.tsx`/`RecentLessons.test.tsx`/(`ContinueLearningCard.test.tsx`/
    `QuickActions.test.tsx` if touched); `tsc --noEmit` clean; `eslint` clean on every touched file.

## Scale & Load

Answering `docs/SCALE-CONTRACT.md`'s six questions.

1. **Unit of work and its range.** One unit = one chapter's exposed lesson list. Min: 0 (no
   generation attempted yet). Typical: 1–3 (one per tier — T1/T2/T3 — the only path the actual
   product UI exposes; `ChapterGenerateControl.tsx` sends only `{tier}`, never `force`, so the
   `force=true` regeneration path D54 added is not reachable from this UI at all today). **Real,
   unbounded-in-principle case:** Gate 5's idempotency check only blocks a new generation while an
   existing lesson for that `(chapter_id, tier)` is `generating`/`ready` — a **failed** lesson does
   not block a retry, so a student repeatedly retrying a failing tier accumulates one new row per
   attempt with no cap found anywhere in this flow (no equivalent of D106/D107's retry-count
   discussion exists for lesson generation). No hard ceiling exists today.
2. **Fixed budgets vs. variable input.** Two, both new to this story: (a) the exposed `lessons`
   list is capped at 20 (AC-2) — a safety ceiling far above the realistic case (typical 1-3,
   even a determined student retrying a failing tier repeatedly is unlikely to reach 20 in one
   session), not a proven natural bound; if ever hit, `lesson_count` still reports the true total
   so the discrepancy is visible in the data, not hidden — but there is currently **no frontend
   affordance surfacing "N more not shown"** if the cap is ever hit (Task list below adds this as
   an explicit, surfaced degradation per Scale Contract Q2, rather than shipping a silent cap).
   (b) None of the *existing* fields' budgets change.
3. **Scope of every limit.** The new 20-entry cap is per-chapter, per-request (computed fresh on
   every `GET .../chapters` call) — no shared bucket, no cross-user or cross-instance state.
4. **Which reads/writes are unbounded?** **Pre-existing, not introduced here, but newly relevant:**
   the `_CHAPTER_COLUMNS` embed's `lessons!lessons_chapter_id_fkey(...)` side has no `.limit()`.
   **Correction (2026-08-17, `/bmad-code-review`, Scale & Load Hunter):** this was originally
   cited here as tracked under D59 — verified FALSE. D59 (`docs/DEFECT-REGISTER.md`) covers only
   `admin/router.py` (closed) and `analytics/service.py` (Dev 3's, open); it never named
   `content/router.py`. A new, correctly-scoped entry, **D115**, was opened for this gap and the
   CI guard's marker-scoping blind spot that let it through unflagged (see the Review Findings
   section below). Before this story, the unbounded fetch was truncated down to exactly one row
   (`latest_lesson`) before ever reaching the client, so the lack of a query-level limit was
   invisible to callers. **This story is the first to expose more of that same unbounded read to
   the client** (as a list, not just a count), which is exactly why AC-2's application-level cap
   exists — the underlying D115 gap is not fixed here (that's a separate, pre-existing defect with
   its own owner, Dev 1), but this story must not make it *worse* by shipping an unbounded list to
   the frontend on top of an unbounded read from Postgres.
5. **Inherited caps re-derived?** The 20-entry cap is a **new** cap, sized against this story's own
   realistic range (typical 1-3, "no UI path to force many more"), not inherited from anywhere —
   documented here, in code as a `# BOUNDED:` comment, rather than a bare magic number.
6. **Concurrent check-then-act safety.** No new writes are introduced by this story — it only
   extends a GET response's shape. The only write in the surrounding flow
   (`generate_chapter_lesson`'s Gate 5 idempotency check) is unchanged by this story and is out of
   scope here.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 2, 3 — backend): Extend `_row_to_chapter_response` to serialize the full
  (capped, newest-first) lessons list; bump the frozen contract.
  - [x] 1.1 RED: test that a chapter fixture with lessons across multiple tiers/states returns all
    of them in `lessons`, newest-first order; a >20-lesson fixture returns exactly 20 (newest) with
    `lesson_count` still reporting the true total; a zero-lesson chapter returns `lessons: []`, not
    `null`; existing `latest_lesson`/`lesson_count`/`has_lesson` tests still pass unmodified with no
    fixture changes. Confirmed RED: 3 failures (2 new tests + the deliberate shape-set update).
  - [x] 1.2 GREEN: implemented `_all_lessons()` in `content/router.py`, reusing the existing embed
    (no second Supabase call) — mirrors `_latest_lesson`'s status-mapping and newest-first sort
    exactly, capped at the new `_MAX_LESSONS_EXPOSED = 20` module constant with a `# BOUNDED`-style
    comment citing Scale & Load Q2/Q5 (originally D59, corrected to **D115** 2026-08-17 — see
    Review Findings). Added `lessons: list[LatestLesson]` to `ChapterResponse`
    (`content/schemas.py`) via `Field(default_factory=list)`. All 39 tests in
    `test_book_endpoints.py` pass.
  - [x] 1.3 Bumped `docs/contracts/book-api.v1.json` to 1.3.0 with a changelog entry and the new
    `ChapterResponse.lessons` field documented. Verified live: booted uvicorn locally and ran
    `.github/scripts/check_book_contract.py` against the real `/openapi.json` — 13 comparisons, no
    divergence.
- [x] Task 2 (AC: 5): Add `lessons: LatestLesson[]` to `ChapterResponse` in
  `apps/web/src/services/books.service.ts`, verified field-for-field against the real (just-
  changed) Python model.
  - [x] 2.1 RED: found a REAL, more interesting RED than a bare `tsc` type gap — this repo's
    `test/contract.ts` has a provenance guard (`assertExampleMatchesSchema`) that throws at
    *import time* if `docs/contracts/book-api.v1.json`'s `schemas.ChapterResponse` and its
    `real_example` payloads don't carry the exact same field set. Adding `lessons` to the schema
    block alone (Task 1.3) without updating `real_example` would have reddened every test that
    imports `@/test/fixtures` — confirmed this is exactly what the guard is for.
  - [x] 2.2 GREEN: added `lessons: LatestLesson[]` to `ChapterResponse` (`books.service.ts`),
    `ContractChapter` (`test/fixtures.ts`), and validated each `lessons[]` entry against the
    `LatestLesson` schema in the provenance guard itself. Populated `real_example`'s `lessons`
    arrays: each chapter's real captured `latest_lesson` is kept verbatim as `lessons[0]`; the
    additional entries a `lesson_count` of 2/3 implies were never individually captured in the
    original 2026-08-04 live gate (only the aggregate count + latest were recorded) — added as
    clearly-labeled SYNTHETIC entries (`note_1_3_0` in the contract JSON), matching this file's own
    established precedent for `TOO_LARGE_CHAPTER`/`RATE_LIMITED_CHAPTER`. Fixed 3 manually-
    constructed `ChapterResponse`/`ContractChapter` literals that needed the new field
    (`books.fixtures.ts`'s `CHAPTERS_21` synthesis, `TOO_LARGE_CHAPTER`, and one MSW mock response
    in `books-msw.integration.test.tsx`). `tsc --noEmit` clean; 8 files / 102 tests passing
    (`contract.test.ts`'s 29 tests confirm the provenance guard didn't throw).
- [x] Task 3 (AC: 6): `ChapterRow.tsx` — expandable "N other lessons" section for
  `chapter.lessons.length > 1`, each entry gated the same `status === 'ready'` rule as today's
  single Watch button, generalized per-entry.
  - [x] 3.1 RED: 4 new tests confirmed failing before implementation (0/1-lesson no-affordance,
    >1 shows "N other lessons" toggle with correct pluralization, expanding reveals working Watch
    links for non-latest READY entries even when the latest one failed, a non-latest non-ready
    entry never gets a link). Used the real captured fixtures directly
    (`CHAPTER_LESSON_COUNT_2`/`CHAPTER_LATEST_FAILED`, now carrying real `lessons` arrays from
    Task 2) rather than inventing new ones.
  - [x] 3.2 GREEN: implemented. `otherLessons = chapter.lessons.slice(1)` (lessons[0] is always the
    same lesson as latest_lesson, both derived server-side by the identical newest-first sort) —
    toggle button + expandable `<ul>`, each entry gated by a new `isWatchable()` helper generalizing
    `watchableLessonId`'s rule. The 20-entry cap surfacing IS implemented: an explicit "N more
    lessons not shown" line renders whenever `lesson_count > lessons.length`, per Scale & Load Q2 —
    not deferred.
  - [x] 3.3 Verified: 21/21 tests passing (15 pre-existing + 6 new), `tsc --noEmit` clean, `pnpm
    lint` 0 errors (32 pre-existing warnings, none in touched files).
- [x] Task 4 (AC: 7, 8, 9): Delete the Library feature; redirect all cross-links to `/books`;
  remove the nav entry; verify zero dead references.
  - [x] 4.1 Deleted `app/(dashboard)/library/` (page+layout), `hooks/useLibrary.ts`,
    `services/library.service.ts`, `components/library/LibraryView.tsx`, `mocks/api/library.ts`,
    and all 4 dedicated test files, via `git rm`. Removed the `libraryService`/`libraryApi`
    barrel exports from `services/index.ts`/`mocks/api/index.ts`.
  - [x] 4.2 Removed "My Library" from `Sidebar.tsx`'s `mainNavItems`; updated `Sidebar.test.tsx`'s
    href-list assertion.
  - [x] 4.3 Redirected to `/books`: `RecentLessons.tsx`'s "View All", `ContinueLearningCard.tsx`'s
    "View Path" (both verified directly, both did link to `/library`), and `QuickActions.tsx`'s
    whole "My Library" card — renamed to "My Books" (icon, title, description, href) rather than
    leaving a stale "Library" label pointing at Books, since this one is a self-contained branded
    card, not a generic "View All" button. Updated `RecentLessons.test.tsx`/
    `ContinueLearningCard.test.tsx`/`Sidebar.test.tsx`/`TopUtilityBar.test.tsx` (the last one found
    during full-suite verification, not caught by the initial grep — its mobile-nav-menu test
    asserted a "my library" link by role name). Also fixed 3 `proxy.test.ts` path arrays
    (`/library` was listed as an example protected/ungated path in 3 separate describe blocks —
    replaced with `/books` where that didn't already appear, removed otherwise) and one
    explanatory comment in `proxy.ts` itself (accuracy only, the deny-list needed no functional
    change). Also updated 2 pre-existing comments in `useDashboard.ts`/`useBooks.ts` and one in
    `lessonStatusPoll.ts` that cross-referenced `useLibrary.ts` by name for "see this file for the
    full rationale" — made self-contained instead of pointing at a deleted file.
  - [x] 4.4 Grep-verified zero remaining hits for `useLibrary|libraryService|LibraryView|libraryApi`
    across `apps/web/src`. (The handful of remaining `/library`-string and "library" hits are my
    own explanatory Story 2-47 comments documenting the removal — not dead references.)
- [x] Task 5 (AC: 10): Full suites green. Backend: `ruff check .`, `ruff format --check .`,
  `mypy app`, and the gating test suite (worktree-baseline comparison against pre-story `main`,
  net-new failures = 0). Frontend: `pnpm test`, `tsc --noEmit`, `eslint` — all clean.
  - Backend: `ruff check .` — All checks passed (0 errors, repo-wide). `ruff format --check .` —
    226 files already formatted. `mypy app` — Success, 0 issues in 83 source files. Gating suite
    (`tests/unit tests/integration -m "not postgres"`): **1182 passed, 0 failed, 6 skipped, 79
    deselected** — exactly +2 over the pre-story baseline (the two new Task 1 tests), zero
    regressions.
  - Frontend: `pnpm test` — **76 files / 946 tests passing**, 0 failed (was 80 files / 965 tests
    before this story: -4 files from Task 4's library test deletions, net -19 tests after
    accounting for the +6 new `ChapterRow` tests added in Task 3). `tsc --noEmit` clean. `pnpm
    lint` — 0 errors, 32 pre-existing warnings (none in any file this story touched).

### Review Findings

_BMAD 6-agent adversarial code review, 2026-08-17 (Blind Hunter, Edge Case Hunter, Acceptance
Auditor, Scale & Load Hunter [mandatory], Story Quality, Test Coverage, AC Completeness, Process
Integrity). Branch diff `main..sprint4/s4-06-merge-library-into-books`. 1 decision-needed, 9
patch, 0 defer, 5 dismissed as noise/accepted-pattern._

- [x] [Review][Decision] Frozen contract ships fabricated/synthetic `lessons` example data —
  **Resolved 2026-08-17: accepted as-is.** User decision: keep the disclosed synthetic entries —
  `docs/contracts/book-api.v1.json`'s `real_example`, `note_1_3_0` explicitly discloses that the
  non-latest `lessons[]` entries for the two real captured chapters are synthetic (invented, not
  pulled from a live capture), because no per-entry data existed for a `lesson_count` of 2–3
  before this story. This is transparently disclosed, not hidden — but it means format
  assumptions (timestamp precision, tier casing, status vocabulary for older/failed rows) in a
  file whose stated purpose is to be a real-capture ground truth are currently unverified against
  the live database. Team must decide: accept synthetic examples here as-is, or require a fresh
  real multi-lesson capture before merge.
- [x] [Review][Patch] Unbounded embedded `lessons` read is mis-cited under the wrong D59 entry and
  invisible to the CI guard that exists to catch it [apps/api/app/modules/content/router.py:89-100,
  1030-1044] — Scale & Load Hunter (mandatory layer) confirmed empirically: `docs/DEFECT-REGISTER.md`'s
  actual D59 entry covers `admin/router.py` (closed) and `analytics/service.py` (Dev 3's, open)
  only, never `content/router.py`/`_CHAPTER_COLUMNS`. Running `test_unbounded_queries.py`'s
  `_unbounded_selects()` against the real file returns `[]` — the `# BOUNDED: <= 80 rows...`
  marker written to justify the outer `chapters` count also blankets the embedded `lessons`
  relation the adjacent comment admits is unbounded, a marker-scoping blind spot in the CI guard
  itself. Reachable input: a single user retrying a failing tier accumulates >20 lesson rows on
  one chapter in ~75 minutes at the stated per-user rate limit (faster across N replicas, per
  D49's `memory://` default).
  **Fixed 2026-08-17.** Opened `docs/DEFECT-REGISTER.md` **D115** (correctly scoped to
  `content/router.py`'s embedded `lessons` read and the CI guard's marker-scoping blind spot),
  corrected every D59 citation to D115 in `router.py`'s comments and this story's own Scale & Load
  / Dev Notes sections. The underlying query-level fix remains deferred under D115, owner Dev 1 —
  not fixed by this story, as intended; the CI guard's marker-scoping blind spot is noted in
  D115's own Enforcement column as what closing it requires.
- [x] [Review][Patch] "N other lessons" toggle button undercounts before it is even expanded
  [apps/web/src/components/dashboard/books/ChapterRow.tsx — `otherLessonsLabel(otherLessons.length)`]
  — the label is derived from `chapter.lessons.slice(1).length` (capped at 19 max, since `lessons`
  itself is capped at 20 server-side), not from the true `chapter.lesson_count - 1`. Example: true
  `lesson_count = 23` → button reads "19 other lessons" when 22 actually exist. The existing
  "surfaces the 20-entry cap explicitly" test does not catch this because it overrides
  `lesson_count` on a fixture whose `lessons` array is still small, never constructing a real
  20-item array. Fix: derive the button label from `chapter.lesson_count - 1`, not
  `otherLessons.length`; add a test with a genuine 20-item `lessons` array and a `lesson_count`
  past it.
  **Fixed 2026-08-17.** Button label now derives from `Math.max(chapter.lesson_count - 1,
  otherLessons.length)`. Added a dedicated regression test plus rebuilt the "surfaces the 20-entry
  cap" test to use a real 20-item `lessons` array instead of a bare `lesson_count` override.
- [x] [Review][Patch] `latest_lesson`/`lessons[0]` invariant is asserted only in a comment, not
  guaranteed or tested [apps/api/app/modules/content/router.py — `_latest_lesson`, `_all_lessons`]
  — the two functions independently filter and sort the same rows with no shared tiebreak key; a
  row with the newest `created_at` but a missing `lesson_id`, or two rows tied on `created_at`
  (plausible under the same rapid failed-retry pattern the 20-cap itself worries about), can make
  `_latest_lesson` and `_all_lessons(...)[0]` diverge, which `ChapterRow.tsx` hard-codes as always
  equal (`otherLessons = chapter.lessons.slice(1)`). Fix: derive `_latest_lesson` from
  `_all_lessons(lessons)[0]` as the single source of truth, add an explicit secondary sort key
  (e.g. `lesson_id`) to break `created_at` ties deterministically, and add a backend test asserting
  `body[0]["latest_lesson"] == body[0]["lessons"][0]`.
  **Fixed 2026-08-17.** `_latest_lesson` is now `_all_lessons(lessons)[0] if ... else None` —
  single source of truth, correct-by-construction. Sort key extended to `(created_at, lesson_id)`
  for a deterministic tiebreak. `_row_to_chapter_response` now computes `_all_lessons` once and
  reuses it for both `latest_lesson` and `lessons` (also removes a duplicate sort). Added
  `test_list_chapters_latest_lesson_always_equals_lessons_first_entry`, which additionally proves
  the fix improves behavior: a newest-but-malformed row now correctly falls back to the newest
  VALID lesson instead of `latest_lesson` going null while `lessons` still had a usable entry.
- [x] [Review][Patch] `QuickActions.tsx`'s "My Library"→"My Books" rename has zero test coverage
  [apps/web/src/components/dashboard/sections/QuickActions.tsx] — no `QuickActions.test.tsx`
  exists anywhere in the repo, despite the Dev Agent Record calling this a deliberate,
  non-mechanical change (icon, title, description, and href all changed). Add a test asserting the
  new title, icon, and `href="/books"`.
  **Fixed 2026-08-17.** Added `QuickActions.test.tsx` — 4 tests covering the Upload PDF card's
  href, the My Books title/href/absence of "My Library" text, the updated description, and an
  exact-count assertion (2 cards) against a stray reintroduced third card.
- [x] [Review][Patch] AC-9's "zero dead references" grep does not actually return zero, and
  nothing guards against regression — 5 files still contain the literal `/library`/`"library"`
  substring in self-referential removal comments: `apps/web/src/components/dashboard/sections/RecentLessons.tsx`,
  `.../ContinueLearningCard.tsx`, `.../QuickActions.tsx`, plus two the story's own Task 4.4
  verification missed — `apps/web/src/components/dashboard/shell/TopUtilityBar.tsx` (a stale
  comment listing "Dashboard/Library/Upload/Reports") and `apps/web/src/app/(dashboard)/books/page.tsx`
  (a comment referencing the now-deleted `library/page.tsx` by path). No CI guard enforces this
  going forward (FIXED-UNGUARDED per Defect Register binding rule 7). Fix: reword all such
  comments to avoid the literal substring, and consider adding a small grep-based unit test so a
  future PR can't silently reintroduce a dead reference.
  **Fixed 2026-08-17.** Reworded all 5 comments to drop the literal quoted `/library` substring
  and the bare "Library" nav-item mention, while keeping the historical "this used to be Library"
  context. Added `__tests__/guards/no-library-references.test.ts` — a source-scan guard (matching
  AC-9's own grep pattern exactly) that now runs on every `pnpm test`, closing the FIXED-UNGUARDED
  gap.
- [x] [Review][Patch] `ChapterRow.tsx`'s new `isWatchable()` duplicates rather than reuses
  `books.service.ts`'s existing `watchableLessonId` gating rule [apps/web/src/components/dashboard/books/ChapterRow.tsx]
  — if that rule is ever extended (e.g. an entitlement check), only the top-level Watch button
  would pick it up; the "other lessons" list would silently keep the old, narrower rule. Fix:
  extract the "is this lesson watchable" predicate into `books.service.ts` once, and have both
  call sites use it.
  **Fixed 2026-08-17.** Extracted `isLessonWatchable()` into `books.service.ts`; `watchableLessonId`
  and `ChapterRow.tsx`'s per-entry gate both call it now — one rule, one place to extend it.
- [x] [Review][Patch] Missing edge-case tests around the 20-entry cap [apps/api/tests/unit/test_book_endpoints.py,
  apps/web/src/__tests__/components/dashboard/books/ChapterRow.test.tsx] — no test at the exact
  20/21-item boundary (only tested at 23, well past it), no frontend test rendering a realistic
  near-cap (20-item) `lessons` array, and no test covering a malformed row missing `lesson_id`
  mixed into the list passed to `_all_lessons`. Add these three cases.
  **Fixed 2026-08-17.** Added backend tests for exactly-20 (all survive, uncapped), exactly-21
  (drops only the single oldest), and a malformed row missing `lesson_id` (skipped, not surfaced,
  `lesson_count` still counts it). Added a frontend test rendering a real 20-item `lessons` array
  (folded into the rebuilt "surfaces the 20-entry cap" test above).
- [x] [Review][Patch] AC-2's required `# BOUNDED:`-tagged comment format wasn't used
  [apps/api/app/modules/content/router.py — `_MAX_LESSONS_EXPOSED`] — the comment is descriptive
  prose without the literal `# BOUNDED:` tag this file already uses elsewhere (e.g. on
  `_CHAPTER_COLUMNS`'s query). No CI consequence (the guard only scans `.select()` chains, not
  plain list slices), but worth aligning for consistency. Low priority.
  **Fixed 2026-08-17.** Added a literal `# BOUNDED: output capped at 20 entries...` line to
  `_MAX_LESSONS_EXPOSED`'s comment, alongside the D115 correction.
- [x] [Review][Patch] Sprint tracker and contract-change notification gaps — this story (S4-06)
  is not yet listed in `docs/dev2-sprint-tracker.md`, and the tracker's own "interface contract
  changes: immediately flag to all 4 devs before merging" protocol wasn't followed for the
  `book-api.v1.json` 1.2.0→1.3.0 bump (the story's Dev Notes only commit to flagging Dev 1). Add
  an S4-06 entry to the tracker, and tag all 4 devs (not just Dev 1) on the contract change when
  the PR is opened.
  **Fixed 2026-08-17 (partially — one part is a PR-time action).** Added an S4-06 entry to
  `docs/dev2-sprint-tracker.md` §13 with the dashboard/header updated. Tagging all 4 devs on the
  contract-change PR itself cannot be done until the PR exists — carried forward as an explicit
  next step (see the end-of-review summary), not silently dropped.

_Dismissed as noise or already-accepted pattern (5): "mock-only assertion" claim against the two
new backend tests (they assert real `TestClient` HTTP response bodies against a mocked Supabase
boundary — this codebase's established, accepted unit-test pattern, not a new violation); AC-3/AC-5
"partial" coverage of the literal `"1.3.0"` version string and the TS interface beyond `tsc`
(same rigor level as prior additive contract bumps, not a gap this story introduced); the `lessons`
field's per-request over-fetch of full generation/failure history (status/tier/timestamp only, no
content — acceptable given the story's own stated realistic range of 1–3 and its explicit Scale &
Load discussion); no `maxItems` constraint in the JSON schema for the cap (nice-to-have hardening,
not a defect); AC-7/AC-10 "no explicit test assertion" findings (deletion and CI-tool cleanliness
are inherently structural/build-level facts, not something a unit-test assertion covers, and no
different from this codebase's standard practice elsewhere)._

## Dev Notes

- **Read the actual current files before touching them** — `ChapterRow.tsx`, `books.service.ts`,
  `library.service.ts`, `Sidebar.tsx`, `RecentLessons.tsx` were all read in full during story
  creation (2026-08-17); their current behavior is described accurately above, not assumed.
- **`content/router.py` is Dev 1's module.** This story touches it with explicit user approval
  (same pattern as the earlier `sprint3-master` backend excursion — see
  `docs/handoffs/dev2-backend-changes-handoff-2026-08-14.md` for the established precedent and
  tone). Flag the diff to Dev 1 in the PR description.
- **D115 (originally mis-cited here as D59, corrected 2026-08-17) is a real, pre-existing,
  separate defect** (unbounded `lessons` embed in `_CHAPTER_COLUMNS`) — this story's AC-2 cap
  prevents this story from making D115 worse, but does **not** close D115 itself (that would mean
  adding a real query-level bound or pagination to the embed, a bigger change with its own owner,
  Dev 1). Do not conflate the two in review.
- **CI is now fully real** (`docs/DEFECT-REGISTER.md` D110–D114, 2026-08-14): `ruff`, `ruff
  format`, and `mypy` all gate the `api` job for real now, and a broken postgres-migration-guard
  bug (D114) that silently never passed is also fixed. Run all three locally before pushing —
  they will actually fail the PR now, unlike earlier in the project's history.
- **Naming collision to watch:** `LatestLesson` (TS interface, `books.service.ts`) is used both as
  the type of `latest_lesson` (singular) and, per AC-1/AC-5, as the array element type of the new
  `lessons` field. This is intentional (same shape, no need for a second type) — just don't
  introduce a confusingly-named second type when one already fits.

## Project Context Reference

- CLAUDE.md: Team Ownership table (`content/router.py` = Dev 1; this story is an approved,
  explicit exception), Frozen Interface Contracts (`docs/contracts/book-api.v1.json` — additive
  GET-shape changes only), Scale Contract (six questions, answered above), Defect Register binding
  rules (D115 cited, not closed, by this story — originally mis-cited as D59, corrected
  2026-08-17).
- `docs/SCALE-CONTRACT.md` — full text of the six questions this story's Scale & Load section
  answers.

## Dev Agent Record

### Completion Notes

Implemented end-to-end via strict RED→GREEN TDD, task by task, per the story's own Tasks/Subtasks
sequence (all 5 marked `[x]` above with quantified evidence per task). Summary:

- **Backend (AC-1, AC-2, AC-3):** Added `ChapterResponse.lessons: list[LatestLesson]` — every
  lesson for the chapter, newest-first, capped at a new `_MAX_LESSONS_EXPOSED = 20` safety ceiling
  (router.py). This is additive-only against the frozen `docs/contracts/book-api.v1.json` (bumped
  1.2.0 → 1.3.0). No new query: the existing `_CHAPTER_COLUMNS` embed already fetched every lesson
  row per chapter; `_row_to_chapter_response` previously discarded all but the newest. `lesson_count`
  continues to report the true total even past the 20-cap, so the cap never silently hides how many
  lessons actually exist (Scale & Load Q2).
- **Frontend (AC-4 through AC-8):** `ChapterRow.tsx` gained an expandable disclosure listing
  `chapter.lessons.slice(1)` (the non-latest lessons), each with a Watch link gated by the same
  `isWatchable` rule already used for `latest_lesson` (ready status only — a failed latest lesson
  must never make a ready earlier lesson look inaccessible), and an explicit "N more lessons not
  shown" line when `lesson_count > lessons.length` — satisfying the no-silent-truncation rule from
  the Scale & Load section rather than deferring it.
- **Library removal (AC-9):** Deleted the entire `/library` route, its service, hook, component,
  mock, and all 4 of their test files. Fixed every cross-reference: `Sidebar.tsx` nav item removed;
  `RecentLessons.tsx`/`ContinueLearningCard.tsx` "View All"/"View Path" now point at `/books`;
  `QuickActions.tsx`'s "My Library" card renamed to "My Books" (icon, title, description, href) —
  a considered judgment call to avoid leaving a stale "Library"-branded card pointing at Books;
  `proxy.ts`/`proxy.test.ts` path arrays and comments updated; stale cross-file comments in
  `useDashboard.ts`, `useBooks.ts`, `lessonStatusPoll.ts` made self-contained. One gap missed by
  targeted grep (`TopUtilityBar.test.tsx`'s mobile-nav "my library" role-name assertion) was only
  caught by running the full test suite — recorded as an explicit lesson in Task 4's notes.
- **Verification (AC-10):** Backend gating suite 1182 passed / 0 failed / 6 skipped (+2 net over
  the pre-story baseline, zero regressions); `ruff check`, `ruff format --check`, `mypy app` all
  clean. Frontend 76 files / 946 tests passing, 0 failed; `tsc --noEmit` and `pnpm lint` clean.
  **Re-verified after the 2026-08-17 code review's 9 patch fixes:** backend 1186 passed / 0 failed
  / 6 skipped (+4 net — the review's boundary/invariant/malformed-row tests), `ruff`/`ruff
  format`/`mypy` still clean. Frontend 78 files / 952 tests passing, 0 failed (+2 files —
  `QuickActions.test.tsx`, the `no-library-references` guard — +6 tests net), `tsc --noEmit`
  clean.
- **Judgment calls made, all documented inline in the relevant task notes above:** (1) the 20-entry
  cap is a new safety ceiling, not a claim that D115 (originally mis-cited as D59, corrected
  2026-08-17) — the underlying unbounded embed — is closed; explicitly called out in Dev Notes to
  avoid conflating the two in review; (2) the cap-surfacing
  UI note was initially drafted as "deferred" then implemented instead, since deferring would
  contradict this codebase's own no-silent-truncation rule; (3) `QuickActions.tsx`'s card was
  renamed rather than left with a stale label, going slightly beyond a literal "redirect the href"
  reading of the task.
- **No user corrections occurred during implementation** — the story was executed autonomously
  per the `bmad-dev-story` workflow after the single authorizing instruction; all fixes recorded in
  "Errors and fixes" above (provenance-guard proactive check, a self-caught double-render test bug,
  a stale `.next/` build-cache false-positive, and the `TopUtilityBar.test.tsx` gap) were self-caught
  during the TDD/verification cycle, not user-reported.

### File List

**Modified:**
- `apps/api/app/modules/content/router.py`
- `apps/api/app/modules/content/schemas.py`
- `apps/api/tests/unit/test_book_endpoints.py`
- `docs/contracts/book-api.v1.json`
- `apps/web/src/test/fixtures.ts`
- `apps/web/src/__tests__/fixtures/books.fixtures.ts`
- `apps/web/src/services/books.service.ts`
- `apps/web/src/services/index.ts`
- `apps/web/src/mocks/api/index.ts`
- `apps/web/src/__tests__/app/books/books-msw.integration.test.tsx`
- `apps/web/src/components/dashboard/books/ChapterRow.tsx`
- `apps/web/src/__tests__/components/dashboard/books/ChapterRow.test.tsx`
- `apps/web/src/components/dashboard/shell/Sidebar.tsx`
- `apps/web/src/__tests__/components/dashboard/shell/Sidebar.test.tsx`
- `apps/web/src/__tests__/components/dashboard/shell/TopUtilityBar.test.tsx`
- `apps/web/src/components/dashboard/sections/RecentLessons.tsx`
- `apps/web/src/__tests__/components/dashboard/sections/RecentLessons.test.tsx`
- `apps/web/src/components/dashboard/sections/ContinueLearningCard.tsx`
- `apps/web/src/__tests__/components/dashboard/sections/ContinueLearningCard.test.tsx`
- `apps/web/src/components/dashboard/sections/QuickActions.tsx`
- `apps/web/src/hooks/useBooks.ts`
- `apps/web/src/hooks/useDashboard.ts`
- `apps/web/src/lib/lessonStatusPoll.ts`
- `apps/web/src/app/(dashboard)/books/layout.tsx`
- `apps/web/src/proxy.ts`
- `apps/web/src/__tests__/proxy.test.ts`
- `docs/stories/2-47-merge-library-into-books.md`
- `docs/DEFECT-REGISTER.md` (code-review fix: new **D115** entry, correcting the D59 mis-citation)
- `docs/dev2-sprint-tracker.md` (code-review fix: added S4-06 entry)
- `apps/web/src/components/dashboard/shell/TopUtilityBar.tsx` (code-review fix: stale Library
  comment reworded)
- `apps/web/src/app/(dashboard)/books/page.tsx` (code-review fix: stale `library/page.tsx`
  comment reworded)

**Added (code-review fixes, 2026-08-17):**
- `apps/web/src/__tests__/components/dashboard/sections/QuickActions.test.tsx`
- `apps/web/src/__tests__/guards/no-library-references.test.ts`

**Deleted:**
- `apps/web/src/app/(dashboard)/library/page.tsx`
- `apps/web/src/app/(dashboard)/library/layout.tsx`
- `apps/web/src/hooks/useLibrary.ts`
- `apps/web/src/services/library.service.ts`
- `apps/web/src/components/library/LibraryView.tsx`
- `apps/web/src/mocks/api/library.ts`
- `apps/web/src/__tests__/app/library/page.test.tsx`
- `apps/web/src/__tests__/hooks/useLibrary.test.ts`
- `apps/web/src/__tests__/services/library.service.test.ts`
- `apps/web/src/__tests__/components/library/LibraryView.test.tsx`

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-08-17 | Story drafted and committed alone (`c06ed81`), per BMAD Pre-Implementation Checklist. | Dev 2 (Claude) |
| 2026-08-17 | Tasks 1–5 implemented via RED→GREEN TDD: backend `lessons` field + 20-entry cap, frontend expandable disclosure UI, full `/library` removal, all cross-references fixed. Status → review. | Dev 2 (Claude) |
| 2026-08-17 | 6-agent adversarial code review (`/bmad-code-review`): 1 decision-needed (accepted synthetic contract data as-is), 9 patch findings applied — corrected D59→**D115** register mis-citation, fixed an "N other lessons" undercount bug, unified `latest_lesson`/`lessons[0]` via a single source of truth with a deterministic tiebreak, added `QuickActions.test.tsx`, closed AC-9's dead-reference gap with a new source-scan guard test, deduplicated the Watch-gate predicate, added 4 boundary/edge-case tests, added a literal `# BOUNDED:` tag, and added an S4-06 tracker entry. Backend 1186/0 failed, frontend 78 files/952 tests. Status → done. | Dev 2 (Claude) |
