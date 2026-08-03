# Book-Scale Ingestion — Phase Tracker

**Owner:** Dev 1
**Last updated:** 2026-08-03
**Overall status:** 1 of 7 phases verified — Phase 1 ✅ Verified; Phase 2 🔨 In Progress, blocked on DB access; Phase 3 re-planned
(`docs/bmad/phase-3-chapter-detection-plan.md`)
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
| 1 | Prove chapter detection (spike) | ✅ Verified | 2026-08-03 |
| 2 | Make chapters storable (migration) | 🔨 In Progress | — |
| 3 | Detect and store real chapters at upload | ⬜ Not Started | — |
| 4 | Extract one chapter's pages | ⬜ Not Started | — |
| 5 | Chapter-scoped generation | ⬜ Not Started | — |
| 6 | Endpoints | ⬜ Not Started | — |
| 7 | Prove it end to end | ⬜ Not Started | — |

**Totals:** Not Started 5 · In Progress 1 · Implemented 0 · Verified 1 · Blocked 0

**Status values:** `⬜ Not Started` · `🔨 In Progress` · `🧪 Implemented (awaiting verification)` · `✅ Verified` · `🚧 Blocked`

### End goal

> Upload a 1,000-page PDF. Sprint 1 and Sprint 2 run to completion without failing.

Sprint 3 does not begin until Phase 7 is `✅ Verified`.

---

## Phase 1 — Prove chapter detection

**Status:** ✅ Verified — 2026-08-03
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

Run 2026-08-03 in `apps/api/.venv` (`pypdfium2` 4.30.0, Python 3.13.4) against **8 real
textbooks**. Full evidence: **`docs/reports/PHASE-1-TOC-SPIKE.md`**.

**Bookmark tree present — 5 of 8 books, 164 chapters:**

| Book | Pages | TOC entries | `get_toc()` | Level | Chapters | Start page strict | ±1 | Median chapter |
|---|---:|---:|---:|:--:|---:|:--:|:--:|---:|
| Dive into Deep Learning (baseline) | 1,151 | 1,335 | 1.76 s | 0 | 27 | 27/27 | 27/27 | 40 p |
| OpenStax College Physics 2e | 1,671 | 525 | 0.03 s | 0 | 42 | 42/42 | 42/42 | 44 p |
| OpenStax Biology 2e | 1,475 | 591 | 0.05 s | 0 | 53 | 53/53 | 53/53 | 28 p |
| Mathematics for Machine Learning | 417 | 104 | 0.06 s | 1 | 20 | 19/20 | 20/20 | 22 p |
| Think Python 2e | 244 | 240 | 0.04 s | 0 | 22 | 22/22 | 22/22 | 10 p |
| **Total** | | | | | **164** | **163/164 = 99.4 %** | **164/164 = 100 %** | |

- Level-selection heuristic correct on **5 of 5**, no manual override. Chose level 0 on
  four books, level 1 on MML (whose level 0 is 3 "Part" entries, median span 163 p).
- All chosen levels monotonic — page ranges ascending and non-overlapping, which
  Phases 3 and 4 depend on.
- Baseline reproduced exactly: D2L → 27 chapters, 27/27 start pages. Measured 1.76 s
  here vs 4 s recorded in the brief.
- The one strict miss is MML entry `[8] "Exercises"` — bookmark one page early, found at
  +1, and a non-content entry regardless.

**No bookmark tree — 3 of 8 books, all NCERT Indian school physics (the target segment):**

| Book | Pages | TOC | Text layer | Printed contents page | In-body `CHAPTER N` openers |
|---|---:|---:|---:|:--:|---:|
| NCERT Class XI Physics Part 1 (2025-26) | 184 | 0 | 2,738 chars/p | yes | 7 true (+1 false) |
| NCERT Class XI Physics Part 2 (2006) | 189 | 0 | 2,816 chars/p | yes | 7 true, ch 9–15 (+4 false) |
| NCERT Class XII Physics Part 1 | 291 | 0 | 2,296 chars/p | yes, well structured | 0 |

- **None is a scan.** All three are born-digital with a full text layer — so rungs 2/3
  need **no OCR and no vision model**. The brief §8 scanned-book risk did not materialise
  in this sample.
- The two fallback signals are **complementary**: the in-body heading sweep is clean on the
  two books where it fires; on the third (XII Part 1, 0 hits) the printed contents page is
  near machine-readable (`CHAPTER TWO / ELECTROSTATIC POTENTIAL AND CAPACITANCE / 2.1
  Introduction 51`). Every no-bookmark book yielded at least one usable signal.

**Two new design items this surfaced (not in the current Phase 3/6 work lists):**

1. Contents-page numbers are **printed** page numbers, not PDF indices — the front-matter
   offset must be derived, not assumed.
2. Back matter produces **false chapter starts** (`p 175 Chapter 1`, `p 186 CHAPTER 9`) —
   pages *referencing* a chapter, not opening one. Starts must be monotonic and
   de-duplicated by chapter number.
3. Outlines list front/back matter as peers of real chapters — Contents, Preface, Index,
   Appendix, Answer Key, and 6× "Exercises" in MML. Unfiltered, the chapter picker offers
   "Index" as a lesson. Needs a title blocklist + minimum page-span floor.

**Brief's core premise confirmed:** median detected chapter is **10–44 pages** against a
pipeline built at 41 pages. Outliers exist in both directions (D2L Appendix A = 138 p;
several chapters 2–4 p), so Phase 5 must not assume ~40 pages.

### Decision this phase produces
- ≥ 3 of 4 books yield a usable list → proceed to Phase 2 as planned
- < 3 of 4 → add fallback rungs 2–5 and **re-plan before writing any code**

**Decision taken:** the result splits by segment rather than falling on either side.
Rung 1 needs **no change** — 99.4 % strict accuracy, worst case 1.76 s. But it covers
**0 %** of the Indian school-textbook sample, which is the product's actual market.

→ **Proceed to Phase 2 unchanged** (the migration is rung-agnostic; the
`boundary_confidence` enum `toc | font | fallback` already accommodates a
contents-page-derived value).
→ **Rungs 2 and 3 move from contingency into required Phase 3 scope**, and Phase 3 must be
re-planned to include them plus the three design items above, before Phase 3 begins.
→ **Rungs 4 and 5 stay deferred** — nothing in this sample required them.

**Not covered:** no genuinely image-only scan was tested; publisher textbooks (Pearson,
McGraw-Hill) could not be tested legally. Also confirmed — NCERT ships most of its
catalogue as **one PDF per chapter** (`ncert-keph1` → `keph101.pdf` … `keph108.pdf`), so
single-chapter upload stays a first-class case for this segment, not a degenerate one.

---

## Phase 2 — Make chapters storable

**Status:** 🔨 In Progress — 🚧 **blocked on database access**
**Story:** `docs/stories/1-9-chapters-storable-migration.md`
**Branch:** `book-scale/phase-2-chapters-storable`
**Depends on:** Phase 1 verified
**⚠️ FROZEN CONTRACT — 4-developer review required (`CLAUDE.md` §16)**
**Scope amended 2026-08-03:** RLS re-rooting added (AC14–17) — the 4 `chapters` and 4 `chunks`
policies root through `lessons.user_id` and can never match a chapter with `lesson_id = NULL`.

### Work
New migration in `supabase/migrations/`:
- `chapters.lesson_id` → **nullable** (today `NOT NULL REFERENCES lessons ON DELETE CASCADE`,
  `20260611000000_initial_schema.sql:132`)
- Add `lessons.chapter_id` (nullable, FK to `chapters`)
- Add `UNIQUE (book_id, chapter_index)`
- Add `chapters.boundary_confidence` — **`toc` | `contents` | `heading` | `font` | `fallback`**

> ⚠️ **Amended 2026-08-03 by the Phase 3 re-plan** (`docs/bmad/phase-3-chapter-detection-plan.md` §6).
> The enum was `toc | font | fallback`. The measured detection ladder has **five** distinct
> provenances; collapsing them destroys the only signal that says which detector is failing in
> production. Phase 2 has not started, so this costs no rework — but it must be folded in
> **before** the 4-developer review, not after. Nothing else in the migration changes.

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

**2026-08-03 — blocked before RED. No migration written. Not verified, not implemented.**

Harness built and committed (`be7a46a`): replays every file in `supabase/migrations/` in
filename order against a real server and asserts on real SQLSTATEs.
**25 tests collected, 25 skipped**, each with the visible reason *"Docker daemon not reachable
— cannot start a Postgres container"*. Repo-wide `ruff check .` → All checks passed.
`mypy` on the new test → Success, no issues.

Blockers, in the order hit:

1. **Docker daemon down.** CLI 29.1.3 present; `docker info` fails on the named pipe. Docker
   Desktop was launched and after 5+ minutes `tasklist` showed zero docker processes.
2. **Local PostgreSQL 18 IS running on `localhost:5432`** (PID 10552) and would satisfy
   binding rule 4 without Docker — but the superuser password is unknown.
3. **The chain cannot replay on stock Postgres regardless of server**, which changes the
   harness design: it needs `auth.users` (FK `20260611000000:69`, trigger `:75-77`),
   `auth.uid()` (**66** references), and `storage.buckets` (`20260710000000:18`).
   A shim is committed at `apps/api/tests/integration/supabase_shim.sql`.
   **`supabase db reset` — step 4 of the test list below — is not runnable: the Supabase CLI
   is not installed.** Replaying the migration files directly is the substitute.

**Unblock by either** starting Docker Desktop, **or** supplying the local Postgres 18
superuser password (harness needs ~3 lines changed to use a throwaway database instead of a
container).

### Files
`supabase/migrations/` (new file — **not yet written**),
`apps/api/tests/integration/test_migration_chapters_book_scoped.py`,
`apps/api/tests/integration/supabase_shim.sql`, `apps/api/pyproject.toml`

---

## Phase 3 — Detect and store real chapters at upload

**Status:** ⬜ Not Started — **re-planned 2026-08-03**
**Depends on:** Phase 2 verified
**Full plan:** **`docs/bmad/phase-3-chapter-detection-plan.md`** — supersedes the Phase 3
work list in the brief §5

> **Why re-planned:** Phase 1 proved `get_toc()` covers 0 % of the NCERT sample. The original
> single fallback to `detect_headings()` is the wrong shape: the failing books are
> born-digital (no OCR needed), and the two text signals are **complementary, not
> alternatives** — an either/or ladder solves 2 of 3 NCERT books, merging them solves 3 of 3.

### Work
- New ARQ job `book_ingest_job(book_id)` — does **not** use the LangGraph, no LLM, no OCR,
  no page rendering, no table scan
- A **five-rung detection ladder** with a shared single text-only page sweep:

  | Rung | Method | `boundary_confidence` | Status |
  |---|---|---|---|
  | **R1 outline** | `get_toc()` + level heuristic | `toc` | proven Phase 1, unchanged |
  | **R2 contents-page** | parse the printed contents page | `contents` | **new scope** |
  | **R3 heading-sweep** | in-body `CHAPTER n` openers | `heading` | **new scope** |
  | **R4 font-signals** | existing `detect_headings()` (`structure_detection.py:29`) | `font` | wired, not tuned |
  | **R5 whole-document** | one chapter — today's behaviour, made explicit and labelled | `fallback` | **new scope**, terminal |

  R2 and R3 are **merged**, not tried in sequence. R3 is authoritative; R2 fills the gaps by
  **title-anchored search**, not printed-page arithmetic.
- A shared **acceptance gate** per rung (7 rules) — see the plan §4. Rule 4 ("no start on a
  contents-like page") is load-bearing: the prototype's title check *passed* on two pages that
  were not chapters, because a contents page contains every title in the book.
- **Non-content filter** — drop `Index`, `Preface`, `Answer Key`, `Appendix *`, `Exercises`
  etc. Unfiltered, the chapter picker offers "Index" as a lesson.
- Write **N** chapter rows: real `page_start`/`page_end`, sequential `chapter_index` from 0
  over kept chapters, `boundary_confidence`
- Set `books.status='ready'` on success and `'failed'` on error — `'failed'` is currently
  never written anywhere
- `POST /lessons` (`content/router.py:242`) becomes ingestion-only: creates the `books` row,
  stores the PDF, enqueues this job. Stops creating a `lessons` row (`:338`) and stops
  enqueuing the pipeline (`:378`)
- Replaces the hardcoded chapter row at `graph.py:609-638`, including `"chapter_index": 1`
  (`:624`)
- Text sweep runs in the **isolated subprocess** (`CLAUDE.md` §18), never in the FastAPI process

**Prototyped in the Phase 1 spike:** the merged R2+R3 detector resolved **22 of 22 chapters
across all three NCERT books, 22/22 title-on-start-page.**

### Exit criterion
Uploading the 1,151-page book produces 27 chapter rows in seconds — **and** a bookmark-less
NCERT book produces its real chapter list rather than one whole-book chapter.

### End-to-end test
1. Upload the real book through the running API
2. Query `chapters` — expect **27 rows**, `chapter_index` 0..26, no gaps, no duplicates
3. Page ranges ascending, non-overlapping, within `[0, n-1]` — **gaps permitted only where a
   non-content entry was dropped**
   *(amended 2026-08-03: previously "covering the book", which the non-content filter makes
   impossible — see plan §5)*
4. `books.status = 'ready'`
5. **No `lessons` row created by upload**
6. Wall-clock from upload to `ready` — record it. Budget **≤ 15 s** for a 1,000-page book
   (measured: `get_toc()` 0.03–1.76 s; text sweep 2.8–7.9 ms/page → 5.53 s @ 1,671 p)
7. Upload NCERT XI Physics Part 1 (no outline) → **7 chapters**, `boundary_confidence='heading'`
   *(amended 2026-08-03: previously expected `'font'`)*
8. Upload NCERT XII Physics Part 1 (no outline, no in-body openers) → **8 chapters**,
   `boundary_confidence='contents'`
9. Assert **no chapter starts on a contents-like page** — directly, not via the title check
10. Upload a single-chapter PDF → exactly **1** chapter row, not an error (NCERT ships most of
    its catalogue as one PDF per chapter)
11. Upload a PDF with no usable signal → 1 chapter, `'fallback'`, `books.status='ready'`
12. Upload a corrupt PDF → `books.status = 'failed'`
13. Assert **no LLM call, no OCR, no page render, no table scan** occurred on this path

### Observed result
_Not yet run._

### Files
`apps/api/app/workers/jobs/` (new), `apps/api/app/modules/content/chapter_detection/` (new —
pure functions over `(page_count, toc, page_texts)`, no DB, so rungs are testable without a
Supabase mock per binding rule 2), `apps/api/app/modules/content/router.py`,
`apps/api/app/modules/content/pipeline/graph.py`,
`apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`,
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
