# Story 2.47: Fold My Library into My Books (S4-06)

Status: ready-for-dev

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
   the `_CHAPTER_COLUMNS` embed's `lessons!lessons_chapter_id_fkey(...)` side has no `.limit()` —
   already flagged in the codebase's own comment as D59. Before this story, the unbounded fetch was
   truncated down to exactly one row (`latest_lesson`) before ever reaching the client, so the lack
   of a query-level limit was invisible to callers. **This story is the first to expose more of
   that same unbounded read to the client** (as a list, not just a count), which is exactly why
   AC-2's application-level cap exists — the underlying D59 gap is not fixed here (that's a
   separate, pre-existing defect with its own owner), but this story must not make it *worse* by
   shipping an unbounded list to the frontend on top of an unbounded read from Postgres.
5. **Inherited caps re-derived?** The 20-entry cap is a **new** cap, sized against this story's own
   realistic range (typical 1-3, "no UI path to force many more"), not inherited from anywhere —
   documented here, in code as a `# BOUNDED:` comment, rather than a bare magic number.
6. **Concurrent check-then-act safety.** No new writes are introduced by this story — it only
   extends a GET response's shape. The only write in the surrounding flow
   (`generate_chapter_lesson`'s Gate 5 idempotency check) is unchanged by this story and is out of
   scope here.

## Tasks / Subtasks

- [ ] Task 1 (AC: 1, 2, 3 — backend): Extend `_row_to_chapter_response` to serialize the full
  (capped, newest-first) lessons list; bump the frozen contract.
  - [ ] 1.1 RED: test that a chapter fixture with lessons across multiple tiers/states returns all
    of them in `lessons`, newest-first order; a >20-lesson fixture returns exactly 20 (newest) with
    `lesson_count` still reporting the true total; a zero-lesson chapter returns `lessons: []`, not
    `null`; existing `latest_lesson`/`lesson_count`/`has_lesson` tests still pass unmodified with no
    fixture changes.
  - [ ] 1.2 GREEN: implement in `content/router.py`. Reuse the existing embed — do not add a second
    Supabase call. Add the `# BOUNDED:` comment per Scale & Load Q2/Q5.
  - [ ] 1.3 Bump `docs/contracts/book-api.v1.json` version + changelog entry for the new field.
- [ ] Task 2 (AC: 5): Add `lessons: LatestLesson[]` to `ChapterResponse` in
  `apps/web/src/services/books.service.ts`, verified field-for-field against the real (just-
  changed) Python model.
  - [ ] 2.1 RED: `tsc --noEmit` / a runtime pass-through test confirming the field is required and
    typed correctly (a pure type addition may not fail at runtime under esbuild's type-stripping —
    verify with `tsc` first, matching Story 2-46's own precedent for this exact situation).
  - [ ] 2.2 GREEN: implement.
- [ ] Task 3 (AC: 6): `ChapterRow.tsx` — expandable "N other lessons" section for
  `chapter.lessons.length > 1`, each entry gated the same `status === 'ready'` rule as today's
  single Watch button, generalized per-entry.
  - [ ] 3.1 RED: tests — `lessons.length <= 1` renders identically to today (no regression); `> 1`
    shows the expandable affordance; each non-latest, `ready` entry gets its own working Watch
    link; a non-latest `failed`/`generating` entry never renders a Watch link (mirrors
    `watchableLessonId`'s existing safety test, generalized).
  - [ ] 3.2 GREEN: implement. If the 20-entry cap (AC-2) is ever hit, surface it explicitly (e.g. a
    "showing the most recent 20" note) rather than silently truncating with no indication — Scale
    & Load Q2.
- [ ] Task 4 (AC: 7, 8, 9): Delete the Library feature; redirect all cross-links to `/books`;
  remove the nav entry; verify zero dead references.
  - [ ] 4.1 Delete `app/(dashboard)/library/`, `hooks/useLibrary.ts`, `services/library.service.ts`,
    `components/library/LibraryView.tsx`, and their test files. Remove `libraryService` from
    `services/index.ts` and `/library` mocks from `mocks/api/`.
  - [ ] 4.2 Remove "My Library" from `Sidebar.tsx`'s `mainNavItems`; update its test.
  - [ ] 4.3 Redirect `RecentLessons.tsx`'s "View All" to `/books` (verify `ContinueLearningCard.tsx`
    and `QuickActions.tsx` directly — update only if they actually link to `/library`); update
    their tests.
  - [ ] 4.4 Grep-verify zero remaining hits for `useLibrary|libraryService|LibraryView|/library`
    across `apps/web/src`.
- [ ] Task 5 (AC: 10): Full suites green. Backend: `ruff check .`, `ruff format --check .`,
  `mypy app`, and the gating test suite (worktree-baseline comparison against pre-story `main`,
  net-new failures = 0). Frontend: `pnpm test`, `tsc --noEmit`, `eslint` — all clean.

## Dev Notes

- **Read the actual current files before touching them** — `ChapterRow.tsx`, `books.service.ts`,
  `library.service.ts`, `Sidebar.tsx`, `RecentLessons.tsx` were all read in full during story
  creation (2026-08-17); their current behavior is described accurately above, not assumed.
- **`content/router.py` is Dev 1's module.** This story touches it with explicit user approval
  (same pattern as the earlier `sprint3-master` backend excursion — see
  `docs/handoffs/dev2-backend-changes-handoff-2026-08-14.md` for the established precedent and
  tone). Flag the diff to Dev 1 in the PR description.
- **D59 is a real, pre-existing, separate defect** (unbounded `lessons` embed in
  `_CHAPTER_COLUMNS`) — this story's AC-2 cap prevents this story from making D59 worse, but does
  **not** close D59 itself (that would mean adding a real query-level bound or pagination to the
  embed, a bigger change with its own owner). Do not conflate the two in review.
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
  rules (D59 cited, not closed, by this story).
- `docs/SCALE-CONTRACT.md` — full text of the six questions this story's Scale & Load section
  answers.
