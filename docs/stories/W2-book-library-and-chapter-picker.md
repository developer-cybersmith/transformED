# Story W2: Book library and chapter picker

Status: ready-for-dev

**Track:** W · **Branch:** `book-scale/track-w`
**Depends on:** W1 (the upload flow pushes to `/books/{id}`). **Gates:** W3.

## Story

As a **student with uploaded textbooks**,
I want **to see my books and browse one book's chapters**,
so that **I can choose what to study** — the screen the whole book-scale effort exists to make
possible, and which does not exist at all today.

Recon confirmed: **no `books.service.ts`, no `useBooks`/`useChapters`, no `/books` route, no
`BookResponse`/`ChapterResponse` type anywhere in `apps/web`.** Grep for `content/books` returns
zero hits. Build from scratch — but from the templates named below, not from nothing.

## Acceptance Criteria

**AC1 — `books.service.ts`.** `listBooks()`, `getBook(id)`, `listChapters(bookId)` against
`content/books`, `content/books/{id}`, `content/books/{id}/chapters` (relative paths, no leading
slash — `lib/api.ts:4`'s `baseURL` already ends in `/api`). Types hand-written from
`docs/contracts/book-api.v1.json` v1.1.0, matching the repo's existing convention of declaring
response types in the service file. `services/library.service.ts` is the near-exact template.

**AC2 — `ChapterResponse` is modelled in full**, including the Phase 6 fields:
`lesson_count: number` and `latest_lesson: {lesson_id, status, tier, created_at} | null`.
`lesson_id` means the **most recent** lesson and `has_lesson` means "at least one lesson in any
state" — both are derived from an embedded relation, not stored.

**AC3 — The Watch button is gated on `latest_lesson.status`, never on `has_lesson`.**
This is the single most important line in this story. A chapter whose only lesson is `failed`
has `has_lesson: true`; rendering "Watch" for it produces a button that 404s the player.
`latest_lesson.status` is the **client** vocabulary — `queued | running | ready | failed` — mapped
server-side from the DB's `generating|ready|failed`. Only `ready` earns a Watch button.
`lesson_count > 1` must be visible: one chapter legitimately carries lessons at several tiers.

**AC4 — Routes.** `app/(dashboard)/books/page.tsx` and `books/[id]/page.tsx`, each with a
`layout.tsx`. There is **no shared `(dashboard)/layout.tsx`** — every child duplicates the
Sidebar + TopUtilityBar shell, so copy `(dashboard)/library/layout.tsx`. `books/[id]` inherits
`books/layout.tsx`.

**AC5 — Next 16, not Next 14.** The repo is Next **16.2.9** / React **19.2.4** (D36; CLAUDE.md is
wrong). In Next 15+ dynamic-route `params` is a **Promise**. **Read `app/lesson/[id]/page.tsx`
first and copy its actual signature** — recon flagged this as unverified, so verify rather than
assume.

**AC6 — Everything that fetches is a client component.** The axios auth interceptor is
browser-only (`lib/api.ts:18-27`). An RSC calling `api` gets no `Authorization` header and 401s.
Follow `library/page.tsx:7-9` + `useLibrary.ts:15-16`, which document exactly this.

**AC7 — SWR hooks keyed by user.** `useBooks`/`useChapters` modelled on `useLibrary.ts` —
**keyed by `user.id`** (`:20-22`) so a cache entry cannot leak across accounts. A book still
`processing` polls; use `nextPollInterval(book.status === 'processing', ref)` from
`lib/lessonStatusPoll.ts:26-36`. Do **not** use `isLessonProcessing` (`:15-17`) — wrong vocabulary.

**AC8 — Route gating, in this story.** Append `"/books"` to `ONBOARDING_GATED_PREFIXES` at
`proxy.ts:19`. `pathRequiresOnboarding` (`:23-25`) does exact-segment matching, so one entry
covers `/books` and `/books/{id}`. Auth gating is automatic — `PUBLIC_PATHS` (`:14`) is a
deny-list. No `config.matcher` change. Extend `__tests__/proxy.test.ts`.

**AC9 — Navigation.** Add the entry to `mainNavItems` (`components/dashboard/shell/Sidebar.tsx:12-17`),
which is exported and asserted by `__tests__/components/dashboard/shell/Sidebar.test.tsx`.

**AC10 — No dead-end CTAs.** Every button either navigates somewhere real or is disabled with a
reason. A chapter with no lesson shows "Generate" — **wired in W3**, disabled with an explanatory
tooltip here. Do not ship an enabled button that does nothing.

**AC11 — Empty, loading, error, stale.** Copy the banner pattern at `library/page.tsx:18-41`.
Zero books is a first-run state with a route to `/upload`, not an error.

**AC12 — Tests against MSW**, using W0's fixtures: list renders real captured books; a book with
21 chapters renders 21 rows with real page ranges; the `lesson_count: 2` chapter shows both;
a `failed` latest lesson shows no Watch button; 404 renders not-found, not a crash.

**AC13 — Gates.** `pnpm lint`, `pnpm type-check`, `pnpm test` clean.

## Dev Notes

- Real captured shapes are in `docs/contracts/book-api.v1.json` → `real_example`, taken
  2026-08-04 from the live 1,151-page run: 21 chapters, page ranges like `[69..120]`,
  `boundary_confidence: "toc"`, and one chapter carrying two lessons at different tiers.
- `boundary_confidence` (`toc|contents|heading|font|fallback`) is how the chapter was detected. It
  is **not** a quality score and must not be rendered as one. At most, surface `fallback`
  quietly — it means detection found no structure.
- Page ranges are 0-based PDF indices, not printed page numbers. Do not present them as "page 69"
  to a student without saying what they are.
