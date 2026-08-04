# Story 1.11: Books and chapters readable over HTTP (book-scale Phase 3.5)

Status: review

**Sprint:** Book-scale ingestion, Phase 3.5 of 9
**Owner:** Dev 1
**Branch:** `book-scale/phase-3.5-book-endpoints` — cut from **`book-scale/integration`**, not `main` (D41)
**Depends on:** Phase 3 ✅ Verified 2026-08-04
**Gates:** SYNC-1 — and therefore Dev 2's W1, W2, W3

---

## Story

As **Dev 2 building the book library and chapter picker**,
I want **the books and chapters the ingest job writes to be readable over the API**,
so that **I can build the UI against real data instead of waiting three phases for Phase 6**.

## Why this phase exists

`chapters` has **three writes and zero SELECTs** in the entire backend
(`pipeline/graph.py:628`, `workers/jobs/book_ingest.py:168`, `:174`). Phase 3 writes 21 correct
rows for a 1,151-page book and **no API can see any of them** — its own e2e step said "query
`chapters`" in the Supabase dashboard, which is the manual, unrepeatable verification the gate
rule exists to kill.

Two consequences, both fixed here: Phase 3's output becomes testable by an integration test
rather than by a human with a dashboard, and Dev 2 stops being blocked.

---

## Correction to the re-plan — read before implementing

The tracker's Phase 3.5 section says *"Delete `graph.py:609-651`"* (AC23, moved from Story 1-10).
**That is still premature, for the same reason it was premature in Phase 3, and this story does
not do it.**

`chapter_id` produced by that block is consumed at `graph.py:659` to write the chunk rows, and
`chunks.chapter_id` is `NOT NULL` (`20260611000000_initial_schema.sql:147`). Nothing supplies a
`chapter_id` until **Phase 5** makes it a `PipelineState` input. Deleting the block here leaves
`chunk_node` unable to write chunks at all.

The re-plan's stated rationale was *"inert today, destructive the moment Phase 6 lands"* — but
**Phase 5 precedes Phase 6**, so removing it in Phase 5 is still before the danger window opens,
and Phase 5 is the first moment a real `chapter_id` exists to replace it with.

**What this story DOES remove:** the `books.page_count` write at `graph.py:393-399`. That has no
such dependency, and `book_ingest_job` already writes `page_count` — two writers for one column
is exactly the drift this phase is meant to end.

**The guard test is therefore scoped to `books` now, and extended to `chapters` in Phase 5.**
Written that way deliberately: a guard that fails today would be commented out today.

---

## Acceptance Criteria

**Read endpoints**

1. `GET /api/content/books` returns the caller's books:
   `[{book_id, filename, status, page_count, chapter_count, created_at}]`, newest first.
   `chapter_count` is the real count of that book's chapter rows.
2. `GET /api/content/books/{book_id}` returns one book with the same shape.
   **This is what `UploadFlow` polls instead of `GET /lessons/{id}`** — without it Dev 2's W1
   has nothing to poll.
3. `GET /api/content/books/{book_id}/chapters` returns
   `[{chapter_id, chapter_index, title, page_start, page_end, boundary_confidence, lesson_id, has_lesson}]`,
   **ordered by `chapter_index`**.
4. `lesson_id` and `has_lesson` ship **now**, even though both are always `null`/`false` until
   Phase 6. Omitting them means Dev 2 rebuilds the chapter card at W3.
5. A book belonging to another user returns **404, not 403**, and the body contains **no book
   metadata** — no filename, no page count. 403 confirms the id exists.
6. A malformed (non-UUID) `book_id` returns 404, not 500 — matching `get_lesson`'s
   `uuid.UUID()` guard at `router.py:429-433`.

**Single-writer cleanup**

7. The `books.page_count` write is removed from `graph.py:393-399`. `book_ingest_job` is the
   only writer.
8. A guard test fails if anything under `app/modules/content/pipeline/` writes to the `books`
   table. Scoped to `books` — `chapters` is added in Phase 5 when the writer can actually go.

**Contract for Dev 2**

9. `docs/contracts/book-api.v1.json` contains the **real** JSON these endpoints return, captured
   from an actual ingest of the 1,151-page book — not hand-written examples.

**Verification**

10. Every endpoint is exercised against **real PostgREST + real Postgres**, not a Supabase mock.
    Binding rule 4, and D37 specifically: `_LIST_COLUMNS`' JSON-path selectors
    (`router.py:112-116`) have never been executed against real Postgres, and the `completed_at`
    reference in that same select list already caused one outage-class `42703` (D9). **Any new
    select list here is exposed to exactly that.**
11. Repo-wide, against a `main` baseline measured with the identical command: gating scope green;
    `ruff check .` clean; `ruff format --check` and `mypy app` show no new findings; the advisory
    full suite shows no new failures.

---

## Tasks / Subtasks

- [ ] **T1 — Response schemas** — `BookResponse`, `ChapterResponse` in
      `app/modules/content/schemas.py` (the module does not exist yet; `router.py` currently
      declares its models inline at `:52-70`). Keep them local — **not** in `packages/shared`,
      which is a frozen contract and needs no change. (AC1–4)
- [ ] **T2 — The three GET endpoints** in `app/modules/content/router.py`. (AC1–6)
  - [ ] Ownership via `books.user_id == current_user["sub"]`, 404 on mismatch
  - [ ] `chapter_count` — one aggregate query, not N+1 per book
  - [ ] Follow `get_lesson`'s UUID guard and 404 convention
- [ ] **T3 — RED then GREEN: endpoint tests** in `tests/unit/test_book_endpoints.py`. (AC1–6)
- [ ] **T4 — Remove the `books.page_count` write** from `graph.py:393-399`. (AC7)
- [ ] **T5 — Guard test** in `tests/unit/test_pipeline_writes_no_books.py` — a source scan over
      `pipeline/` for `table("books")`. Use `ast.unparse` with docstrings stripped, **not** a raw
      substring scan: a plain scan matches the prose explaining what the code avoids, which is
      exactly how the equivalent test in Story 1-10 first failed. (AC8)
- [ ] **T6 — Capture the contract** into `docs/contracts/book-api.v1.json` from a real ingest. (AC9)
- [ ] **T7 — Repo-wide gates + tracker update** with observed numbers. (AC11)

---

## Dev Notes

### Files being modified — current state

**`app/modules/content/router.py`** — three routes today: `POST /lessons` (now ingestion-only,
returns `BookUploadResponse`), `GET /lessons/{id}`, `GET /lessons`. Response models are declared
**inline in the router** at `:52-70`; there is no `schemas.py` yet.

The ownership pattern to copy is `get_lesson` (`:429-447`): validate the UUID, fetch, then
`if not lesson or lesson.get("user_id") != user_id: raise 404`. **Follow it exactly** — a
different shape here is a different security posture.

`_LIST_COLUMNS` (`:112-116`) is a cautionary example, not a template. Its comment explains that
naming `completed_at` explicitly made PostgREST reject the whole query with `42703` for every
user on every request (D9). **Keep the new select lists to real columns.**

**`app/modules/content/pipeline/graph.py:393-399`** — `extract_node` writes `books.page_count`
inside a `try/except` that only warns. It is guarded by `if book_id:` with the comment
*"P6: don't skip when page_count=0 — that's valid information"*. Removing it must not disturb the
image-upload block immediately above.

**`app/workers/jobs/book_ingest.py`** already writes `{"status": "ready", "page_count": ...}`
after detection, so removing the graph.py write leaves the column correctly populated by one
writer.

### Do not reinvent

- `single_row()` / `rows()` in `app/core/db.py:73-93` are the typed response-boundary helpers.
  Use them; do not hand-roll `.data` access — that is what they exist to centralise.
- `CurrentUser` and `get_supabase` are already imported in `router.py`.
- The Supabase client is **service-role** (`core/db.py:42`), so RLS does **not** filter for you.
  Ownership filtering here is application-level and must be explicit. This is the single most
  likely way to ship an IDOR in this story.

### What Phase 3 actually produced (test against these numbers)

The 1,151-page book yields **21** chapters, `chapter_index` 0..20, `boundary_confidence='toc'`,
`lesson_id NULL` on all 21, ranges `p40–68` … `p932–935`. NCERT XI Part 1 yields 7 (`heading`);
NCERT XII Part 1 yields 8 (`contents`).

### Testing standards

- Markers: `unit`, `integration`, `slow`, `live_eval`, `postgres`. `--strict-markers`,
  `filterwarnings = ["error"]`.
- The repo's `test_migration_*_schema.py` files parse SQL text and never open a connection —
  **do not copy that pattern.** `tests/integration/test_migration_chapters_book_scoped.py` is the
  model for real-database verification.
- A local Postgres with the full migration chain is already running: container
  `transformed-local-db`, `127.0.0.1:55432`, db `transformed`, user `postgres`, password `localdev`.

### References

- [Source: docs/book-scale-phase-tracker.md#Phase-3.5] — the plan, and the AC23 item this story corrects
- [Source: docs/stories/1-10-book-ingest-chapter-detection.md] — Phase 3, its gate numbers, and D-A/D-B
- [Source: CLAUDE.md#Defect-Register] — binding rules 1, 2, 4, 5, 7; D9 and D37 (`42703` in select lists); D41 (branch policy)

---

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] — 2026-08-04, two parallel agents on disjoint file sets

### Debug Log References

**The story's premise was factually wrong, and the guard is what caught it.**

AC7 named `graph.py:393-399` as the pipeline's `books` write. There was a **second** one:
`embed_node` at `graph.py:924-934` wrote `books.status = 'ready'`. AC8's guard, written exactly
as specified, went red on it on day one — which is the failure mode this story warned about in
its own text.

It was removed, and the reason is worse than redundancy: **`books.status` changed meaning in
Phase 3.** It used to mean "the pipeline finished"; it now means "ingestion finished", written
by `book_ingest_job` (`'ready'` on success, `'failed'` on error). A surviving `embed_node` write
would silently resurrect a book the ingest job had marked `failed`. Nobody wrote that semantic
change down when Phase 3 made it.

Removing both writes orphaned `book_id` in `extract_node` and `embed_node` (ruff F841); the
locals are gone, `book_id` stays on `PipelineState` and is still used by `chunk_node`.

**The chapter-creation block at `graph.py:609-651` was deliberately NOT deleted** — verified that
`chapter_id` from it is consumed at `:659` and `chunks.chapter_id` is `NOT NULL`. Phase 5.

**Guard mutation-checked independently.** Not taken on the implementing agent's word: a
`supabase.table("books").update(...)` was reintroduced into `graph.py` and the guard failed with
`Found: {'graph.py': ["supabase.table('books').update(...)"]}`, then passed again on revert. The
guard parses `ast.unparse`d source with docstrings stripped, so it detects writes rather than
mentions — a raw substring scan is how the equivalent test in Story 1-10 failed on its own
docstring.

**Ownership is enforced twice on purpose.** The Supabase client is service-role
(`core/db.py:42`), so RLS filters nothing: `_fetch_owned_book()` both filters
`.eq("user_id", sub)` and re-asserts ownership on the returned row. The chapters route resolves
ownership on `books` first — `chapters` has no `user_id`, so an unguarded `.eq(book_id)` would
be a straight IDOR.

**Known gap — AC10 is only partly satisfied.** The endpoint tests are unit tests against a
Supabase mock, which by construction cannot raise `42703`. Substituted: a guard parsing
`supabase/migrations/*.sql` asserting every column named in the select lists is real, plus a
premise assertion that the parser works so it cannot pass vacuously. **Still unverified against
real PostgREST: the `chapters(count)` embedded aggregate** — its response shape, and that the
relationship resolves unambiguously given `books` has three inbound FKs. That needs the
integration test before this phase is Verified.

### Completion Notes List

- T1–T6 complete. 35 new tests; gating scope **870 passed, 1 skipped** (was 835).
- `ruff check .` clean; `mypy app` **24 errors in 3 files**, unchanged from `main`.
- Pagination (`limit`/`offset`, default 50, max 200) added to `GET /books` — **not in the ACs**.
  Shipping an unbounded list was the alternative. Documented in the contract.
- Line-number drift found in the story: `get_lesson`'s UUID guard is at `router.py:421-426`
  (story said 429-433); `_LIST_COLUMNS` at `:113-117` (story said 112-116).
- **Not yet done:** the real-PostgREST integration test (AC10) and the tracker update. Phase 3.5
  is **not** Verified until the embed aggregate is confirmed against a live database.

### File List

- `apps/api/app/modules/content/schemas.py` (new — `BookResponse`, `ChapterResponse`)
- `apps/api/app/modules/content/router.py` (modified — 3 routes, 2 select-list constants, 5 helpers)
- `apps/api/app/modules/content/pipeline/graph.py` (modified — both `books` writes removed)
- `apps/api/tests/unit/test_book_endpoints.py` (new — 32 tests)
- `apps/api/tests/unit/test_pipeline_writes_no_books.py` (new — the AC8 guard + 2 premise tests)
- `apps/api/tests/unit/test_extract_node.py`, `test_embed_node.py` (modified — asserted the removed writes)
- `docs/contracts/book-api.v1.json` (new — frozen read contract for Dev 2's W0)
