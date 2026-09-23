---
title: "Story 5-9: Show book personalization form during processing + fix FK bug"
status: in-progress
story_key: "5-9-book-context-processing-ux"
baseline_commit: ""
---

# Story 5-9 — Book Context Form During Processing + Fix Migration FK Bug

**Branch:** `sprint5/s5-9-book-context-processing-ux`
**Based on:** `sprint5/s5-1-book-context-form` (includes all S5-1 work — 10-question form,
API endpoints, prompt injection)

## Story

As a student who has just uploaded a PDF, I want to see the 10-question personalisation form
**immediately** when I land on the book detail page — even while my book is still being
analysed — so I can fill it out while waiting for chapters to be detected (parallel UX, not
sequential blocking). I should not have to wait for chapter detection to finish before I can
answer these questions.

The industry-standard pattern: upload → redirected to book page → form visible immediately →
processing spinner below → when chapters are ready, chapter list appears below the form.

## Acceptance Criteria

- **AC1** — `supabase/migrations/20260921000000_book_context.sql` FK reference is
  `REFERENCES books(book_id)` (not `books(id)` — `books` PK is `book_id`). The migration
  applies to production Supabase without error.
- **AC2** — `BookContextForm` renders on `/books/{id}` when `book.status === "processing"`,
  i.e. immediately after upload redirect while chapter detection is still running.
- **AC3** — `BookContextForm` renders on `/books/{id}` when `book.status === "ready"` (existing
  behaviour preserved).
- **AC4** — `BookContextForm` does NOT render when `book.status === "failed"` (no chapters will
  ever appear; form context would be wasted).
- **AC5** — When `book.status === "processing"`, the form subtitle reads:
  "While your book is being analysed — tell us how you'll use it."
- **AC6** — When `book.status === "ready"`, the form subtitle remains:
  "Optional — helps personalise every lesson we generate from it."
- **AC7** — The "detecting chapters" spinner/banner still appears (below the form) when
  `book.status === "processing"`.
- **AC8** — The dismiss button (✕) on `BookContextForm` still works correctly — clicking it
  hides the form for the current browser session.
- **AC9** — All existing `BookDetail.test.tsx` tests continue to pass.
- **AC10** — New `BookDetail.test.tsx` tests cover AC2, AC3, AC4, and confirm `isProcessing`
  prop value passed to the form.
- **AC11** — All 5 CI checks pass (API lint/type/test, contract, web lint/type/build).

## Tasks / Subtasks

- [ ] **T1** — Fix FK in `supabase/migrations/20260921000000_book_context.sql`
  - [ ] T1a — Change `REFERENCES books(id)` → `REFERENCES books(book_id)` (1 line)
- [ ] **T2** — Update `BookDetail.tsx` mount condition
  - [ ] T2a — Replace `book?.status === "ready"` guard with `book != null && book.status !== "failed"`
  - [ ] T2b — Pass `isProcessing={book.status === "processing"}` prop to `BookContextForm`
- [ ] **T3** — Update `BookContextForm.tsx` to accept and use `isProcessing` prop
  - [ ] T3a — Add `isProcessing?: boolean` to `BookContextFormProps` interface
  - [ ] T3b — Add `isProcessing = false` to function destructuring
  - [ ] T3c — Render conditional subtitle based on `isProcessing`
- [ ] **T4** — Write/update frontend tests
  - [ ] T4a — Mock `BookContextForm` in `BookDetail.test.tsx` (vi.hoisted pattern)
  - [ ] T4b — Test: form renders when `status === "processing"` with `isProcessing=true`
  - [ ] T4c — Test: form does not render when `status === "failed"`
  - [ ] T4d — Test: form renders when `status === "ready"` with `isProcessing=false`
- [ ] **T5** — Run all CI checks locally
  - [ ] T5a — `cd apps/web && npx vitest run`
  - [ ] T5b — `cd apps/api && python -m pytest tests/test_s5_1_book_context.py -v`

## Dev Notes

### Why FK was wrong
`supabase/migrations/20260921000000_book_context.sql` line 23 references `books(id)` but the
`books` table PK is defined as `book_id` in `supabase/migrations/20260611000000_initial_schema.sql`.
Postgres would reject the migration with `ERROR: there is no unique constraint matching given keys
for referenced table "books"`. Fix: `REFERENCES books(book_id)`.

### Why show form during processing
The §4.2 questions (purpose, coverage scope, difficulty, deadline, structure preference,
motivation, end goal, feared section, prior attempt, outcome clarity) are all about the
student's intent with the book — none require chapter metadata. They can and should be
answered in parallel with chapter detection (~2–5 min), not after it. This is the
industry-standard "upload + form" UX (Figma, Notion, GitHub create-project patterns).

### Component ordering in BookDetail.tsx
New ordering preserves the existing visual hierarchy:
```
[Book title + page/chapter count]
[BookContextForm — shown during processing AND ready, never failed]
[Stale-poll error banner — unchanged]
[Processing spinner — shown only when processing, sits below the form]
[Chapter list — shown when ready]
[Empty-chapter state — shown when ready + no chapters]
[Chapters error — unchanged]
```

### isProcessing prop
`BookContextForm` receives `isProcessing?: boolean` (default `false`). When true: subtitle
changes to "While your book is being analysed…". The form's internal loading/save/dismiss
logic is unchanged. No new API calls are added.

### Guard tests
This story modifies `BookDetail.tsx` and `BookContextForm.tsx`. Check before pushing:
- `npx vitest run src/__tests__/components/dashboard/books/BookDetail.test.tsx`
- Any existing `BookContextForm` tests if present.

## Scale & Load

1. **One unit of work:** One form render per book page visit. Fixed 10 fields, one DB row per
   (book_id, user_id) via UNIQUE constraint. Range: always exactly 10 fields.
2. **Fixed budgets vs variable input:** `motivation/end_goal/feared_section` each capped at 500
   chars by `maxLength` on the frontend input. Backend schema already validates via `schemas.py`.
   Exceeding limit → 422 (explicit error), never silent truncation.
3. **Scope:** Per-user, per-book. UNIQUE (book_id, user_id) enforces one row. UI is one form
   per user session — no fan-out.
4. **Unbounded reads:** None. `GET /books/{id}/context` returns at most 1 row — bounded by UNIQUE.
5. **Inherited caps:** None. New table. FK now correctly references books(book_id).
6. **Concurrent check-then-act:** Upsert `ON CONFLICT (book_id, user_id) DO UPDATE SET …` is
   atomic in Postgres — no TOCTOU. Safe under concurrent submits from the same user/book.

## Dev Agent Record

### Debug Log
*(populated during implementation)*

### Completion Notes
*(populated when done)*

### File List
- `supabase/migrations/20260921000000_book_context.sql` — fix FK
- `apps/web/src/components/dashboard/books/BookDetail.tsx` — new mount condition + isProcessing prop
- `apps/web/src/components/dashboard/books/BookContextForm.tsx` — accept isProcessing, conditional subtitle
- `apps/web/src/__tests__/components/dashboard/books/BookDetail.test.tsx` — new tests

### Change Log
*(populated per commit)*
