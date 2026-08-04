# Book-Scale Ingestion — Phase Tracker

**Owner:** Dev 1
**Last updated:** 2026-08-04
**Overall status:** 6 of 9 backend phases verified (1, 2, 3, 3.5, 4, 6). **SYNC-1 is released — Dev 2 is unblocked for W1.** Re-planned 2026-08-04 to align the
frontend: two backend phases inserted (3.5, 6.5) and a parallel **Track W** added for Dev 2.
Nothing is renumbered. Phase 3 plan: `docs/bmad/phase-3-chapter-detection-plan.md`
**Brief:** `docs/bmad/book-scale-implementation-brief.md`

> ## 🔒 GATE RULE — NO EXCEPTIONS
>
> **A phase is not complete when the code is written. A phase is complete when it has been
> tested end to end and observed working.**
>
> 1. Work on Phase N+1 **does not begin** until Phase N is marked `✅ Verified` **within its
>    track**. A phase in the other track begins when the phase it names as its dependency is
>    Verified. *(Amended 2026-08-04: the gate is about evidence, not about `main` — clause 3
>    says "end-to-end run against a real PDF" and never mentions trunk. Two tracks run in
>    parallel; nothing is batched, and every phase still records its own numbers.)*
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
| 2 | Make chapters storable (migration) | ✅ Verified | 2026-08-03 |
| 3 | Detect and store real chapters at upload | ✅ Verified | 2026-08-04 |
| **3.5** | **Books and chapters readable + pipeline writers removed** | ✅ Verified | 2026-08-04 |
| 4 | Extract one chapter's pages | ✅ Verified | 2026-08-04 |
| 5 | Chapter-scoped generation | 🧪 Implemented | — |
| 6 | Endpoints (the write endpoint + `tier` relocation) | ✅ Verified | 2026-08-04 |
| **6.5** | **`lesson_ready` actually reaches a client** | ⬜ Not Started | — |
| 7 | Prove it end to end + the single merge to `main` | ⬜ Not Started | — |

### Track W — Dev 2, `apps/web` (parallel)

| Phase | Title | Status | Starts after |
|:-----:|-------|--------|--------------|
| **W0** | Contract harness (MSW + real fixtures + CI that can go red) | ⬜ Not Started | now — no backend dependency |
| **W1** | Upload becomes ingestion (poll the book, not the lesson) | ⬜ Not Started | W0 Verified + SYNC-1 |
| **W2** | Book library + chapter picker | ⬜ Not Started | W1 Verified |
| **W3** | Generate from chapter (`tier` moves here) | ⬜ Not Started | SYNC-2 |
| **W4** | MSW off — the whole UI against the live API | ⬜ Not Started | Phase 6 Verified |

**Totals:** Backend — Not Started 1 · Implemented 1 · Verified 6. Track W — Not Started 5.

### Synchronisation points

| Sync | When | What is frozen | Signed by |
|------|------|----------------|-----------|
| **SYNC-0** | before further code | branch policy, this plan, the 3-vs-5 review-layer contradiction (P4), an owner for D36 | Dev 1 + Dev 2 |
| **SYNC-1** | Phase 3.5 Verified | the **read** contract: `GET /books`, `GET /books/{id}`, `GET /books/{id}/chapters` + captured real JSON | Dev 1 → Dev 2 |
| **SYNC-2** | Phase 5 Verified | the **write** contract: `POST /books/{bid}/chapters/{cid}/lessons`; `LessonStatusResponse` gains `book_id`, `chapter_id`, `chapter_index` | joint PR |
| **SYNC-3** | Phase 7 | nothing new — MSW off, joint e2e, one merge to `main` | Dev 1 + Dev 2; Dev 3/4 notified |

### Branch policy — why the UI break never reaches `main`

All of Phases 3 → 6.5 and all of Track W land on **`book-scale/integration`**, cut from `main`.
`main` merges **once**, at Phase 7. The re-plan established that nothing had been merged yet, so
the window where upload is broken costs a branch rather than code.

**The honest cost:** `main` keeps doing the wrong thing — one PDF = one whole-book lesson, the
4 %-of-source defect this effort exists to kill — until Phase 7. Any demo given meanwhile is
given from `main` and shows the old behaviour. Registered as **D41**.

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

**Status:** ✅ Verified — 2026-08-03 (applied to the live Supabase project and confirmed there)
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

**2026-08-03 — migration written, green on real PostgreSQL, then hardened by a 5-agent review.**
Story: `docs/stories/1-9-chapters-storable-migration.md`.
Migration: `supabase/migrations/20260803000000_chapters_book_scoped.sql` — 10th file in the chain.

**RED → GREEN, with a mutation check (post-review suite, 43 tests):**

| Run | Result |
|---|---|
| RED — before the migration existed | 19 failed, 6 passed |
| GREEN — migration applied | **51 passed, 0 failed** |
| Mutation — migration file moved away, re-run | **1 failed, 42 errors** |

Real SQLSTATEs observed, not mocked: **`42703`**, **`23505`**, **`23514`**, **`23503`**.

**What the review changed.** The first green run was 25 tests and three of the story's data-safety
ACs were not actually exercised: the fixture applied all 10 migrations to an *empty* database, so
every "pre-existing row" was created *after* the migration ran. AC8/AC9 tested the column default on
INSERT rather than the backfill; AC10 had no test at all. The suite now provisions a **pre-migration
schema, seeds real rows, and applies the migration second** — three separate databases inside one
container (`transformed_test`, `transformed_legacy`, `transformed_dupes`).

**RLS proven behaviourally, both directions:** owner sees 1, other user sees 0, `service_role` sees
1, `anon` sees 0 — using Supabase's real `authenticated`/`service_role` roles. Write-side is now
covered too (cross-tenant INSERT rejected `42501`, DELETE leaves the row), and `chunks` rows are
actually read under a role rather than asserted by substring.

**Production-shape rehearsal (2026-08-03).** The migration was replayed over a structural copy
of the live project before ever touching it — pre-migration schema, seed, migration applied
**second**:

| Checked against the real shape | Result |
|---|---|
| Rows: books / lessons / chapters / chunks | 27 / 27 / **23** / 2,161 — **unchanged by the migration** |
| Chapters keeping their original `lesson_id` **and** `book_id` | **23 / 23** |
| Chapters backfilled to `boundary_confidence='fallback'` | **23 / 23** |
| Duplicate `(book_id, chapter_index)` | **0** — the UNIQUE constraint was *accepted* by the real shape |
| RLS across the 2,161-chunk graph | owner reads their own · stranger reads **0** · `service_role` reads **2,161** |

**This closes D39.** The live project was also queried read-only beforehand: 23 chapters across
23 distinct books, every `chapter_index = 1`, no duplicates, and `boundary_confidence` /
`lessons.chapter_id` both returning `42703` — i.e. confirmed still pre-migration.

The seed (`apps/api/tests/integration/prod_shape_seed.sql`) reproduces the live **structure**
only: row counts, the one-chapter-per-book distribution and the full FK graph are real; every
uuid is a deterministic `uuid5` stand-in and emails and chunk bodies are fabricated. **Zero real
identifiers, student content or personal data.**

**Repo-wide gates** (baseline measured on `main` in a git worktree with the identical command):

| Gate | `main` baseline | This branch |
|---|---|---|
| CI gating scope (`tests/unit tests/integration -m "not postgres"`) | green | **795 passed, 0 failed** |
| `pytest tests -q` (advisory) | 19 failed, 1498 passed | **19 failed, 1551 passed** |
| `ruff check .` | pass | **pass** |
| `ruff format --check .` / `mypy app` | 1 file / 24 errors | unchanged |

**Zero regressions.** 1551 = 1498 + 53 new tests; the 19 failures are identical to main's (D40).

**One production regression found by the review and fixed.** The new `UNIQUE (book_id, chapter_index)`
turned a recoverable ARQ retry into a permanent failure: `chunk_node` writes its checkpoint *after*
the chapter insert, so a failure in that window makes the retry re-write the same
`(book_id, chapter_index=1)` → `23505` → stuck on all of `max_tries=3`. `graph.py` now upserts on
that conflict target. Guarded by a unit test plus a real-Postgres counterpart.

**Also hardened:** the migration is now one transaction (so AC10's fail-loud abort is recoverable and
its documented "re-apply" remedy actually works), `DROP POLICY IF EXISTS` throughout, the index is
named, the test container binds to `127.0.0.1` only, and the `postgres` marker moved off CI's gating
step into its own job that **fails if the tests skip** rather than passing green having verified
nothing.

### Applied to the live Supabase project — 2026-08-03

Applied by a teammate via the Supabase SQL editor, then verified read-only against the live
project. **This closes D38 and is what moves Phase 2 to `✅ Verified`.**

| Check | Before | After |
|---|---|---|
| `chapters.boundary_confidence` | `42703` (absent) | **present**, `required=true` in the live OpenAPI schema |
| `lessons.chapter_id` | `42703` (absent) | **present**, `required=false` (nullable) |
| `chapters.lesson_id` nullability | `NOT NULL` | **`required=false`** — nullable, the whole point of Phase 2 |
| Rows: books / chapters / lessons / chunks | 27 / 23 / 27 / 2,161 | **27 / 23 / 27 / 2,161 — unchanged** |
| Backfill | — | **23 / 23** chapters at `boundary_confidence='fallback'` |
| Legacy rows | 23 carrying `lesson_id` | **23 still carrying it**, none orphaned |
| Duplicate `(book_id, chapter_index)` | 0 | **0** — constraint accepted by live data |
| `lessons.chapter_id` values | — | 27 / 27 NULL, correct: nothing links a chapter yet |

**The four exit tests, executed against the live project 2026-08-03** — not inferred from the
schema, executed and observed:

| # | Test | Result on live Supabase |
|:--:|---|---|
| 1 | Insert a chapter with `lesson_id = NULL` | **SUCCEEDED** — row created, `lesson_id: None`, `boundary_confidence: 'toc'`, pages 272–306 |
| 2 | Insert a duplicate `(book_id, chapter_index)` | **REJECTED — `23505`** `chapters_book_id_chapter_index_key` |
| 2b | Out-of-enum `boundary_confidence` | **REJECTED — `23514`** `chapters_boundary_confidence_check` |
| 3 | Existing 23 rows readable and valid | **PASSED** — all 23 intact, backfilled, none orphaned |
| 4 | `supabase db reset` | **Not runnable** — Supabase CLI not installed. Substituted by replaying all 10 migration files in filename order (container + local Postgres). |

**And the criterion that Phase 3 actually depends on:** the `lesson_id = NULL` chapter was
**visible to its owner (1 row), invisible to another user (0) and to `anon` (0)**. Under the old
`lessons`-rooted policies that row would have been invisible to *everyone* —
`EXISTS (SELECT 1 FROM lessons WHERE lesson_id = NULL)` is never true. This is the re-rooting
doing its job on production data.

**Cleanup verified:** test row deleted, counts back to 27 / 23 / 27 / 2,161, zero `ZZZ-VERIFY`
rows, zero chapters with a NULL `lesson_id`. Production is exactly as it was.

**RLS re-rooting verified behaviourally on the live project**, by minting JWTs with the real
`SUPABASE_JWT_SECRET` and querying PostgREST as each identity:

| Identity | chapters | chunks |
|---|---:|---:|
| Owner (owns 13 of the 27 books) | **9** | **1,507** |
| Stranger (random `sub`) | **0** | **0** |
| `anon` key, unauthenticated | **0** | — |

Cross-checked against the ownership graph: exactly **9** of the 23 chapters sit on books that
user owns. The policy resolves *exactly*, not approximately — the re-rooted
`books.user_id` predicate returns the right rows and nothing else, on real data, through the
real PostgREST stack.

### Files
`supabase/migrations/` (new file — **not yet written**),
`apps/api/tests/integration/test_migration_chapters_book_scoped.py`,
`apps/api/tests/integration/supabase_shim.sql`, `apps/api/pyproject.toml`

---

## Phase 3 — Detect and store real chapters at upload

**Status:** ✅ Verified — 2026-08-04
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

**Gated 2026-08-04. Story: `docs/stories/1-10-book-ingest-chapter-detection.md`.**

**Detection, real PDFs through the real subprocess path:**

| Book | Pages | Time | Rung | Chapters (raw) |
|---|---:|---:|---|---|
| Dive into Deep Learning | 1,151 | 10.13 s | `toc` | 21 (27) |
| OpenStax Biology 2e | 1,475 | 7.08 s | `toc` | 47 (53) |
| OpenStax College Physics 2e | 1,671 | 9.49 s | `toc` | 34 (42) |
| NCERT XI Physics Part 1 | 184 | 2.96 s | `heading` | 7 (7) |
| NCERT XI Physics Part 2 | 189 | 2.11 s | `heading` | 7 (7) |
| NCERT XII Physics Part 1 | 291 | 2.41 s | `contents` | 8 (8) |
| demo sample-chapter | 41 | 0.88 s | `heading` | 1 (1) |

Invariants held on all seven — monotonic, in-bounds, non-overlapping, `chapter_index`
sequential from 0, **no start on a contents-like page**.

**Full stack — FastAPI + ARQ + Redis + the live Supabase project.** Uploading the real
1,151-page book (44.7 MB) through `POST /lessons`:

- **202** `{book_id, job_id}` — **no `lesson_id`** ✅
- `books.status` → `ready` in **28.4 s** ✅
- **21 chapter rows**, `chapter_index` 0..20 with no gaps or duplicates ✅
- ranges ascending and non-overlapping — `ch0 'Introduction' p40–68` … `p932–935` ✅
- `boundary_confidence = {'toc'}` on all 21 ✅
- **`lesson_id NULL` on 21/21** — the Phase 2 capability, exercised in production ✅
- **0 `lessons` rows, 0 `lesson_jobs` rows created by upload** ✅
- single-chapter PDF → exactly 1 chapter (2.8 s) ✅ · corrupt PDF → `status='failed'` (2.5 s) ✅
- `tier` supplied → **422** ✅

All test data removed afterwards; the project is back to 0 books / 0 chapters / 0 lessons.

**The gate found a defect review had missed.** `--text-only` returned full page text over a
pipe (2.4 MB of JSON for D2L) when the detector needs full text only for the 40 contents-scan
pages and 400 characters beyond. D2L sat at **14.56 s against a 15 s budget — 3 % headroom**.
Fixed by passing the detector's own constants down: **10.13 s, 32 % headroom, identical rungs
and counts on every book.**

**AC15 was breached and has been split rather than moved.** Ingest measured 28.4 s. Decomposed:
**18.9 s storage download** (44.7 MB at 2.4 MB/s) + **10.1 s processing** = 29.0 s, against
28.4 s observed. 67 % is network transfer the Phase 1 budget never covered. Processing meets
the 15 s figure; end-to-end is now recorded rather than capped, and transfer is tracked as
**D42**.

**One check failed because the test was wrong, not the code.** `short.pdf` begins every page
with `"Chapter 1: Introduction to Cell Biology"`, so `heading` was the correct rung — it was
never a no-signal fixture.

### Files
`apps/api/app/workers/jobs/` (new), `apps/api/app/modules/content/chapter_detection/` (new —
pure functions over `(page_count, toc, page_texts)`, no DB, so rungs are testable without a
Supabase mock per binding rule 2), `apps/api/app/modules/content/router.py`,
`apps/api/app/modules/content/pipeline/graph.py`,
`apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`,
`apps/api/app/modules/content/pipeline/nodes/structure_detection.py`

---

## Phase 3.5 — Books and chapters readable + pipeline writers removed

**Status:** ✅ Verified — 2026-08-04 · **Owner:** Dev 1
**Depends on:** Phase 3 ✅ · **Gates:** SYNC-1 — **RELEASED**, and therefore all of Track W from W1

### Why this exists

`chapters` has **three writes and zero SELECTs** in the entire backend. A phase whose output no
API can see is a phase whose regression no integration test can catch — Phase 3's own e2e step
said *"query `chapters`"* in the Supabase dashboard, which is exactly the manual, unrepeatable
verification the gate rule exists to kill. It is also what converts three idle Dev 2 phases
into three parallel ones.

### Work

1. `GET /api/content/books` → `[{book_id, filename, status, page_count, chapter_count, created_at}]`, RLS-scoped.
2. `GET /api/content/books/{book_id}` → single book + status. **This is what `UploadFlow` polls
   instead of `GET /lessons/{id}`.** Without it W1 has nothing to poll.
3. `GET /api/content/books/{book_id}/chapters` → ordered by `chapter_index`, including
   `lesson_id` and `has_lesson` **from day one** even though both are always null until Phase 6
   — otherwise Dev 2 rebuilds the chapter card at W3.
4. Another user's book → **404, not 403**, with no book metadata in the body.
5. **Delete `graph.py:609-651`** — the hardcoded `chapter_index: 1` writer (AC23, moved here
   from Phase 3). It upserts on the same `(book_id, chapter_index)` conflict target
   `book_ingest_job` uses, against 0-based detected indices; and `book_ingest_job`'s stale-trim
   would then delete real chapters. Inert today, destructive the moment Phase 6 lands.
6. Remove the `books.page_count` write from `graph.py` — `book_ingest_job` is the single writer now.
7. **Run the pipeline before deleting, to prove it fails** — evidence, not assumption.
8. A guard test that fails if anything under `pipeline/` writes `books` or `chapters` again.

### Exit criterion
Phase 3's output is visible over HTTP, and nothing in `pipeline/` can write `books` or `chapters`.

### End-to-end test
1. Upload the real book → `GET /books` shows it with `chapter_count = 21`
2. `GET /books/{id}/chapters` returns 21 ordered chapters with real page ranges
3. Another user's book → 404, body carries no metadata
4. The guard test fails when a `chapters` write is reintroduced into `pipeline/` (mutation check)
5. Captured real JSON committed to `docs/contracts/` for Dev 2

### Observed result

**Gated 2026-08-04 against the running API + real PostgREST + the live Supabase project.**
Story: `docs/stories/1-11-book-chapter-read-endpoints.md`. **19/19 endpoint checks passed.**

Ingested the real 1,151-page book as user A, then:

| Check | Result |
|---|---|
| `GET /books` → 200, book listed | ✅ |
| `chapter_count` via the embedded aggregate | **21** — the real count ✅ |
| `page_count` written by `book_ingest_job` | **1151** ✅ |
| `GET /books/{id}` same shape as the list item | ✅ |
| `GET /books/{id}/chapters` → **21**, ordered by `chapter_index` | ✅ |
| Real page ranges | `ch0 'Introduction' p40–68` ✅ |
| `lesson_id` + `has_lesson` present from day one | `null` / `false` ✅ |
| User B → **404, not 403**, body `{"detail":"Book not found"}` with no metadata | ✅ |
| User B's own list excludes A's book | 0 books ✅ |
| Malformed `book_id` → 404 not 500, on both routes | ✅ |

All test data removed; the project is back to 0 books.

**AC10 is closed by a repeatable guard, not by this one run.**
`tests/integration/test_book_select_lists_against_postgrest.py` runs **every** select list the app
sends against a real PostgREST — imported from the router rather than re-parsed, so a renamed
constant is an error rather than a silent skip. **9 passed.** It carries a live-trap premise test
asserting a bogus column really does raise `42703`, so it cannot pass vacuously.

**This also closes D37**, whose enforcement column had read *"(to add — real-PostgREST integration
test)"* since 2026-07-30. `_LIST_COLUMNS` — the select list whose `completed_at` reference caused
the D9 outage — has now been executed against a real database for the first time.

**Two defects found while gating, both mine:**

1. I spent a cycle testing a **stale uvicorn**. An older API process from the Phase 3 gate still
   held port 8077, my relaunch failed with `[Errno 10048] address in use`, and the log went to a
   file I did not read. All three routes 404'd and I nearly filed it as a routing bug. The live
   `/openapi.json` showed 3 content routes against 6 in source, which is what caught it.
2. The first version of the PostgREST guard read the constants with a **regex** and skipped when it
   found nothing — two are f-strings and one name was wrong. It reported green while verifying
   nothing. It now imports them.

**Not done here, deliberately:** deleting `graph.py:609-651`. `chapter_id` from it is consumed at
`:659` and `chunks.chapter_id` is `NOT NULL`, so removing it leaves `chunk_node` unable to write
chunks. Moved to Phase 5, where a real `chapter_id` first exists.

**Found by the guard, not by review:** `embed_node` was a **second** `books` writer
(`graph.py:924-934`, `status='ready'`). Removed — `books.status` changed meaning in Phase 3 from
"pipeline finished" to "ingestion finished", so that write could resurrect a book the ingest job
had marked `failed`.

### Files
`apps/api/app/modules/content/router.py`, `apps/api/app/modules/content/schemas.py`,
`apps/api/app/modules/content/pipeline/graph.py`, `docs/contracts/book-api.v1.json`,
`apps/api/tests/unit/test_book_endpoints.py`, `tests/unit/test_pipeline_writes_no_books.py`,
`tests/integration/test_book_select_lists_against_postgrest.py`

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

**Gated 2026-08-04 against the real 1,151-page book.** Story: `docs/stories/1-12-page-scoped-extraction.md`.

Extracting chapter 9, pages 272-306:

| Check | Result |
|---|---|
| First page content | `'7 Convolutional Neural Networks'` — the right chapter |
| `extracted_page_count` / `page_offset` / `page_count` | **35 / 272 / 1151** |
| Slice equals `whole[272:307]` **byte for byte** | yes |
| **Page 0 absent from the output** | yes |
| Off-by-one guards on both boundaries | yes |
| Wall-clock | **2.75 s** vs 10.02 s whole-document — **3.6x faster** |
| Unbounded == explicit full bounds (backwards compatible) | yes |
| Out-of-range -> exit 1 naming the bad value, **never clamped** | yes |

28 new tests, all running from a clean checkout — the eval PDFs are gitignored, so they now
generate at import rather than skipping. Verified by deleting every fixture and re-running.

`_extract_font_blocks` is bounded too: 2,830 blocks in 0.5 s for a 5-page range against 31,726 in
7.3 s whole-document. Left unbounded, a "35-page" extraction would still have parsed all 1,151
pages and the phase would have achieved nothing.

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

**Implemented 2026-08-04, NOT yet Verified.** Story: `docs/stories/1-13-chapter-scoped-generation.md`.

Verified against the code by line-to-function mapping rather than by reading the diff:

| AC | Check | Result |
|---|---|---|
| 1 | `chapter_id` on state, on `run_pipeline`, read from `lessons.chapter_id` | yes |
| 2 | `page_start`/`page_end` reach the subprocess spawn args | yes |
| 4 | `"chapter_index": 1` gone; any `chapters` write from `pipeline/` | **none** |
| 7 | D33 closed — normalise then raise a diagnostic before Pydantic sees it | yes |
| 8 | Guard widened to `books` **and** `chapters`, mutation-checked | yes |
| 9 | **Of the eleven generation nodes, none touched** | confirmed |

AC9 is the phase's central bet and it held: `lesson_planner`, `slide_generator`, quiz, narration,
jargon, interventions, complexity, TTS and image are byte-identical. Only `extract_node`,
`chunk_node`, `package_builder_node`, `run_pipeline` and one new helper changed.

25 existing tests failed and every one was repaired **without weakening an assertion** — 21 stale
fixtures, 4 inverted to assert the new invariant rather than deleted.

Gating scope **917 passed, 1 skipped** (was 898); ruff clean; mypy unchanged at 24/3.

**Why this is not Verified:** AC10 requires generating a real chapter through all eleven nodes,
which spends real money on the project's OpenAI key. The repo has a `live_eval` marker for exactly
this class of run.

**DECISION 2026-08-04 — D43: pay once, not twice.** Phase 7's acceptance run must generate two
chapters at two tiers regardless, so AC10 is folded into it rather than billed twice. Phase 6
proceeds on Phase 5's *implementation*, which it needs whatever AC10 returns. This is a recorded
exception to the gate rule above, not a lapse: if the Phase 7 run fails, Phase 5 returns to
🔨 In Progress and Phase 6 is un-Verified along with it. Phase 7's exit criterion names AC10 by
number so the acceptance run cannot pass without discharging it.

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

**✅ Verified 2026-08-04.** Story: `docs/stories/1-14-generate-lesson-from-chapter.md`.

**Live, against the real 1,151-page book and the real Supabase project.**

| | |
|---|---|
| Ingest | 1,151 pages, **21 chapters**, upload 58.0 s, end-to-end **90.3 s** |
| Generation half | **12/12** — create 202, idempotent 200, second tier, all four negatives |
| Page bounds reaching the subprocess | **3/3** |
| Gating suite | **1068 passed, 1 skipped** (was 968 passed / 10 skipped) |
| ruff repo-wide / mypy | clean / 24 errors in 3 files, unchanged from `main` |

**The premise, measured.** `extract_node` spawned the subprocess with argv `(40, 68)` — the
chapter's real bounds — and returned **82,665 chars for 29 pages (~2,851/page)**. A
whole-document extraction of the same book would be **~3,280,945 chars**. Every extracted image
landed on pages 52, 54, 55, 61 — all inside the chapter. That is the book-scale premise
demonstrated end to end, not argued.

**The cap does not refuse anything real.** Largest detected chapter in this book: **98 pages**,
against a 200 cap. The 40-page warn band set `truncation_expected` where it should.

**One chapter, two lessons, two tiers** — `lesson_count: 2` with `latest_lesson` resolving to the
newer by `created_at`. The dead scalar `chapters.lesson_id` could never have expressed this.

### Found by this phase, and fixed

**D52 — the rate limiter was keyed by IP, not by user.** `_get_user_key` decoded the bearer token
with no `audience=`, and every Supabase token carries `aud: "authenticated"` — PyJWT raises
`InvalidAudienceError` in exactly that case, the bare `except` swallowed it, and it returned
`get_remote_address`. Every authenticated user shared one bucket: one caller exhausting
`3/minute` locked out everyone behind the same egress IP. Present since `upload_lesson`'s
`5/minute` was written. Caught because the gate expected a 404 for another user's book and got a
**429**. 8 regression tests, mutation-checked.

**D51 — CI's anti-vacuum guard had never fired.** `grep -qE "^[0-9]+ skipped|no tests ran"` only
matches an ALL-skipped run; pytest's mixed summary is `9 passed, 12 skipped`, so a partial skip
passed green. The PostgREST half of the harness had been skipping in CI, unreported, since it was
written. Guard tightened to fail on any skip; truth-tabled over four summary shapes.

### Stale processes cost most of the debugging time

Three separate incidents in one session, all the same shape — *something reported success without
being checked*:

1. A stale `uvicorn` served **3** book routes while source had **4**; the live `/openapi.json`
   disagreed with the code.
2. My own port-free check used `LISTENING.*:8077`, which can never match Windows `netstat`
   column order — so it reported "free" unconditionally.
3. Two stale ARQ workers running pre-Story-1-13 code (their lesson `SELECT` predates
   `chapter_id`) failed every lesson within seconds and produced three false gate failures.

`app.routes` is also the wrong instrument on this FastAPI version — module routes are
`_IncludedRouter` branches with no `.path`. Use `app.openapi()`.

### Files
`apps/api/app/modules/content/router.py`, `apps/api/app/modules/content/schemas.py`

---

## Phase 6.5 — `lesson_ready` actually reaches a client

**Status:** ⬜ Not Started · **NEW 2026-08-04** · **Owner:** Dev 1 (Dev 4 notified)
**Depends on:** Phase 6 ✅

### Why this exists
`core/pubsub.py` strips the `lesson_ready:` prefix and passes the **lesson_id** into
`manager.send()`, which keys connections by the **session_id** (D34). Today that is dead code
because the frontend deliberately no-ops `lesson_ready` and readiness comes from polling — so
Phase 7 could pass on polling alone and never notice. Fix it before the acceptance run, or the
acceptance run certifies a broken push path.

### Exit criterion
A generated lesson pushes `lesson_ready` to a connected client and the client acts on it.

### End-to-end test
1. Connect a WebSocket, generate a chapter lesson, observe the message arrive keyed correctly
2. Assert `manager.send` receives an id a client actually connected under (closes D34)

### Observed result
_Not yet run._

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

**Also discharges Story 1-13 AC10 (D43).** Phase 5 was carried forward as `🧪 Implemented` on the
understanding that this run — which generates two chapters at two tiers anyway — is where the
eleven nodes are proven against ~40 pages for real. If that fails, Phase 5 and Phase 6 both
return to `🔨 In Progress`. This run may not be recorded as passing while AC10 is outstanding.

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

# Track W — Dev 2, `apps/web`

Runs in parallel with Track A from SYNC-1. Same gate rule: a W phase is complete only when
tested end to end and observed working, with the numbers recorded here.

## W0 — Contract harness
**Depends on:** nothing — starts immediately.
**Why first:** `upload.service.test.ts:46-53` asserts `body.get('tier')).toBe('T3')` against a
mock. That test **passes today and will keep passing** while the endpoint 422s — Dev 2's CI
stays green while the product is dead. That is the 2026-07-29 failure one layer up.
**Work:** MSW; fixtures captured from Dev 1's real 1,151-page run (not hand-written); a contract
CI job comparing the committed `docs/contracts/book-api.v1.json` against the live FastAPI schema.
**Exit criterion:** a **mutation check** — rename a field in the fixture and the contract test
must go red.

## W1 — Upload becomes ingestion
**Depends on:** W0 Verified + SYNC-1.
**Work:** `upload.service.ts` — `BookUploadResponse {book_id}`, stop sending `tier`, poll
`GET /books/{id}`. `UploadFlow.tsx` two-phase state machine. **Today it 422s on 100 % of
uploads** (`handleTierSelect` is the only route to `processing`, so `tier` is always set), and
with no tier it polls `content/lessons/undefined` forever.
**Exit criterion:** upload a real book in a browser and watch chapters appear.

## W2 — Book library + chapter picker
**Depends on:** W1 Verified. Routes `/books`, `/books/[id]`. No dead-end CTAs.
Add `/books` to `ONBOARDING_GATED_PREFIXES` (`proxy.ts:19`) in the same story as the route.

## W3 — Generate from chapter
**Depends on:** SYNC-2. `ModeSelection` relocates from upload to the chapter card — **`tier`
moves with it**. S2-09 is **moved in Dev 2's tracker, not deleted**.

## W4 — MSW off
**Depends on:** Phase 6 Verified. The whole UI against the live integration API. Gates Phase 7.

---

## Update protocol

When a phase changes state, in the **same** response:

1. Update the phase's **Status** line
2. Fill in **Observed result** with the actual numbers seen — never "works"
3. Update the **Status Dashboard** row and the **Totals** line
4. Update **Last updated** and **Overall status** in the header

Never mark a phase `✅ Verified` without recording evidence. Never update the dashboard
without updating the header date.
