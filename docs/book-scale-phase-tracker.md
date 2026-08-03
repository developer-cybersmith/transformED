# Book-Scale Ingestion — Phase Tracker

**Owner:** Dev 1
**Last updated:** 2026-08-03
**Overall status:** 0 of 7 phases verified — not started
**Brief:** `docs/bmad/book-scale-implementation-brief.md`

> ## 🔒 GATE RULE — NO EXCEPTIONS
>
> **A phase is not complete when the code is written. A phase is complete when it has been
> tested end to end and observed working.**
>
> 1. Work on Phase N+1 **does not begin** until Phase N is marked `✅ Verified`.
> 2. **`Implemented` is not `Verified`.** Passing unit tests is not verification.
> 3. Only an **end-to-end run against a real PDF** moves a phase to `✅ Verified`.
> 4. The **observed result must be written into this file** — the actual numbers seen, not
>    "works". A phase with no recorded evidence is not verified.
> 5. If verification fails, the phase returns to `🔨 In Progress`. It is never partially
>    passed forward.
>
> **Why this rule exists:** the evaluation harness crashed on all five test PDFs and wrote a
> success-shaped result file anyway (`apps/api/tests/evals/runner.py:277-316`). Every defect
> in this effort survived because something reported success without being checked. This rule
> is the countermeasure.

---

## Status Dashboard

| Phase | Title | Status | Verified on |
|:-----:|-------|--------|-------------|
| 1 | Prove chapter detection (spike) | ⬜ Not Started | — |
| 2 | Make chapters storable (migration) | ⬜ Not Started | — |
| 3 | Detect and store real chapters at upload | ⬜ Not Started | — |
| 4 | Extract one chapter's pages | ⬜ Not Started | — |
| 5 | Chapter-scoped generation | ⬜ Not Started | — |
| 6 | Endpoints | ⬜ Not Started | — |
| 7 | Prove it end to end | ⬜ Not Started | — |

**Totals:** Not Started 7 · In Progress 0 · Implemented 0 · Verified 0 · Blocked 0

**Status values:** `⬜ Not Started` · `🔨 In Progress` · `🧪 Implemented (awaiting verification)` · `✅ Verified` · `🚧 Blocked`

### End goal

> Upload a 1,000-page PDF. Sprint 1 and Sprint 2 run to completion without failing.

Sprint 3 does not begin until Phase 7 is `✅ Verified`.

---

## Phase 1 — Prove chapter detection

**Status:** ⬜ Not Started
**Type:** Spike. No production code. No story file required.
**Depends on:** nothing
**Gates:** the shape of Phase 3

### Goal
Determine whether reading a book's built-in chapter list is sufficient on real target
textbooks, or whether fallback rungs 2–5 are needed.

### Work
- Run `PdfDocument.get_toc()` against 3–4 real target textbooks
- Apply the prototyped level-selection heuristic: coarsest level with 4–80 entries and a
  median span ≥ 3 pages
- For each book record: bookmark tree present, chapters detected, start-page accuracy

### Exit criterion
We know the usable-chapter-list rate across real books, and whether rungs 2–5 are required.

### End-to-end test
For each test book, print chapter count and page ranges, then open each chapter's start page
and confirm the title appears in the first 400 characters.

**Baseline already measured** — *Dive into Deep Learning*, 1,151 pages:
27 chapters, **27/27** start pages correct, 4 s.

### Observed result
_Not yet run._

### Decision this phase produces
- ≥ 3 of 4 books yield a usable list → proceed to Phase 2 as planned
- < 3 of 4 → add fallback rungs 2–5 and **re-plan before writing any code**

---

## Phase 2 — Make chapters storable

**Status:** ⬜ Not Started
**Depends on:** Phase 1 verified
**⚠️ FROZEN CONTRACT — 4-developer review required (`CLAUDE.md` §16)**

### Work
New migration in `supabase/migrations/`:
- `chapters.lesson_id` → **nullable** (today `NOT NULL REFERENCES lessons ON DELETE CASCADE`,
  `20260611000000_initial_schema.sql:132`)
- Add `lessons.chapter_id` (nullable, FK to `chapters`)
- Add `UNIQUE (book_id, chapter_index)`
- Add `chapters.boundary_confidence` (`toc` | `font` | `fallback`)

Direction is **permissive** — no existing row can be invalidated. Never modify an applied
migration.

### Exit criterion
A chapter row can exist without a lesson.

### End-to-end test
Against **real Postgres**, not a mock (binding rule 4 — a Supabase mock has no catalog and
cannot 42703):
1. Insert a chapter row with `lesson_id = NULL` → succeeds
2. Insert a duplicate `(book_id, chapter_index)` → rejected
3. Existing 23 chapter rows still readable and valid
4. `supabase db reset` replays the full migration chain cleanly

### Observed result
_Not yet run._

### Files
`supabase/migrations/` (new file)

---

## Phase 3 — Detect and store real chapters at upload

**Status:** ⬜ Not Started
**Depends on:** Phase 2 verified

### Work
- New ARQ job `book_ingest_job(book_id)` — does **not** use the LangGraph
- Read the chapter list via `get_toc()`; fall back to `detect_headings()`
  (`nodes/structure_detection.py:29`) over text-only extraction when absent
- Write **N** chapter rows: real `page_start`/`page_end`, sequential `chapter_index`,
  `boundary_confidence`
- Set `books.status='ready'` on success and `'failed'` on error — `'failed'` is currently
  never written anywhere
- `POST /lessons` (`content/router.py:242`) becomes ingestion-only: creates the `books` row,
  stores the PDF, enqueues this job. Stops creating a `lessons` row (`:338`) and stops
  enqueuing the pipeline (`:378`)
- Replaces the hardcoded chapter row at `graph.py:609-638`, including `"chapter_index": 1`
  (`:624`)

### Exit criterion
Uploading the 1,151-page book produces 27 chapter rows in seconds.

### End-to-end test
1. Upload the real book through the running API
2. Query `chapters` — expect **27 rows**, `chapter_index` 0..26, no gaps, no duplicates
3. Page ranges ascending, non-overlapping, covering the book
4. `books.status = 'ready'`
5. **No `lessons` row created by upload**
6. Wall-clock from upload to `ready` — record it
7. Upload a bookmark-less PDF → fallback path fires, `boundary_confidence = 'font'`
8. Upload a corrupt PDF → `books.status = 'failed'`

### Observed result
_Not yet run._

### Files
`apps/api/app/workers/jobs/` (new), `apps/api/app/modules/content/router.py`,
`apps/api/app/modules/content/pipeline/graph.py`,
`apps/api/app/modules/content/pipeline/nodes/structure_detection.py`

---

## Phase 4 — Extract one chapter's pages

**Status:** ⬜ Not Started
**Depends on:** Phase 3 verified

### Work
- Add `page_start`/`page_end` to the subprocess argv contract and to `extract_page_data(...)`
  — signature today is `(pdf_path, img_dir, ocr_threshold)` (`extract_subprocess.py:436-445`)
- Change `for page_idx in range(page_count)` (`:460`) to the bounded range
- Reuse `_build_sub_pdf` (`:144-153`)
- Skip the per-page table scan `_page_table_count` (`:469`) during chapter detection — it is
  the 579 ms/page cost

### Exit criterion
Extracting pages 272–306 returns only that chapter and never reads page 0.

### End-to-end test
1. Extract pages 272–306 of the real book → text matches that chapter only
2. Assert page 0 content is **absent** from the output
3. Wall-clock ≤ 60 s for a ~40-page chapter (baseline: ~26 s)
4. Out-of-range bounds → clean error, no crash
5. Omitting bounds → whole document, unchanged behaviour (backwards compatible)

### Observed result
_Not yet run._

### Files
`apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`,
`apps/api/app/modules/content/pipeline/graph.py`

---

## Phase 5 — Chapter-scoped generation

**Status:** ⬜ Not Started
**Depends on:** Phase 4 verified

### Work
- `chapter_id` becomes a required input on `PipelineState`
- `extract_node` (`graph.py:280-330`) resolves the chapter's page range and passes bounds
- **All other nodes untouched**
- Drop checkpoint-based `chapter_id` recovery at `graph.py:738` and `:3742` (closes D33)
- Idempotency guard so regenerating a chapter does not re-embed

### Exit criterion
A chapter of the big book produces a valid `LessonPackage`.

### End-to-end test
1. Generate a lesson for chapter 10 of the real book
2. Package validates against `packages/shared/lesson_package.schema.json`
3. **No truncation warning in the logs** — this is the core proof; today a big book emits
   them constantly
4. Slide and quiz counts land in the tier band
5. `chunks` for this lesson all carry the correct `chapter_id`
6. Regenerate the same chapter → **no new embedding API calls**
7. Total cost recorded and under the $3.00 ceiling

### Observed result
_Not yet run._

### Files
`apps/api/app/modules/content/pipeline/graph.py`

---

## Phase 6 — Endpoints

**Status:** ⬜ Not Started
**Depends on:** Phase 5 verified

### Work
- `GET /books`
- `GET /books/{book_id}/chapters` — makes `chapters` readable; today it has one INSERT and
  **zero SELECTs** in the entire backend
- `POST /books/{book_id}/chapters/{chapter_id}/lessons`
- **`tier` moves here** off the upload form (`router.py:255-261`)
- Page-count gate beside the existing 50 MB cap (`router.py:48`)

### Exit criterion
The whole flow is drivable over the API.

### End-to-end test
1. Upload → `GET /books` shows it
2. `GET /books/{id}/chapters` returns 27 chapters
3. `POST .../chapters/{id}/lessons` with `tier=T1` → lesson generates
4. Same book, different chapter, `tier=T3` → generates at T3 slide count
5. Another user's book → 404, not 403 (no existence leak)
6. Invalid tier → 422
7. Over the page-count gate → clean rejection

### Observed result
_Not yet run._

### Files
`apps/api/app/modules/content/router.py`, `apps/api/app/modules/content/schemas.py`

---

## Phase 7 — Prove it end to end

**Status:** ⬜ Not Started
**Depends on:** Phase 6 verified

### Work
- Commit a real book-scale fixture **with** a bookmark tree and one **without**
- Integration test: chapter count, page ranges, valid package, no truncation warning
- A guard that fails if `chapter_index` reverts to a constant or a cap silently moves
- One green eval run as the calibration baseline

### Exit criterion
CI fails if any of this regresses.

### End-to-end test — full acceptance
1. Upload a real 1,000+ page textbook via the API
2. N chapter rows appear with correct page ranges, in seconds
3. List chapters over the API
4. Generate **two different chapters at two different tiers**
5. Both produce schema-valid packages with **no truncation warnings**
6. Play both in the player; take both quizzes
7. Full suite + `ruff` + `mypy`, **repo-wide** (binding rule 1 — never scoped to touched files)
8. Mutation check: change `chapter_index` back to a constant → a test **must** fail

### Observed result
_Not yet run._

### Files
`apps/api/tests/integration/`, `apps/api/tests/fixtures/`, `apps/api/tests/evals/`

---

## Update protocol

When a phase changes state, in the **same** response:

1. Update the phase's **Status** line
2. Fill in **Observed result** with the actual numbers seen — never "works"
3. Update the **Status Dashboard** row and the **Totals** line
4. Update **Last updated** and **Overall status** in the header

Never mark a phase `✅ Verified` without recording evidence. Never update the dashboard
without updating the header date.
