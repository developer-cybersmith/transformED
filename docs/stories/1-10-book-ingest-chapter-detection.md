# Story 1.10: Detect and store real chapters at upload (book-scale Phase 3)

Status: ready-for-dev

**Sprint:** Book-scale ingestion, Phase 3 of 7
**Owner:** Dev 1
**Branch:** `book-scale/phase-3-chapter-detection`
**Plan of record:** `docs/bmad/phase-3-chapter-detection-plan.md` — supersedes the brief §5
**Depends on:** Phase 1 ✅ Verified · Phase 2 ✅ Verified (applied to live Supabase 2026-08-03)
**Blocks:** Phases 4–7

---

## Story

As **Dev 1 building book-scale ingestion**,
I want **uploading a book to detect its real chapters and store one row per chapter**,
so that **a student can later pick any chapter to learn, instead of the pipeline inventing a single fake chapter spanning the whole book**.

## Context

`POST /lessons` today creates a `books` row, a `lessons` row, a `lesson_jobs` row and enqueues the
full 11-node generation pipeline — for the whole PDF, as one lesson. The pipeline then writes
exactly one chapter row, hardcoded at `graph.py:609-638` with `"chapter_index": 1` and a title/page
range read off `sections[0]`/`sections[-1]`. On a 1,151-page book that names the chapter after its
copyright page and claims it spans pages 1–1151.

Phase 1 proved detection works. Phase 2 made the rows storable. **This story is the job that
actually detects and writes them.**

### What Phase 1 measured (this is the evidence the design rests on)

| | |
|---|---|
| Books with a usable outline (`get_toc`) | **5 of 8** — 164 chapters, **163/164 (99.4 %)** strict start-page accuracy |
| Books without one | **3 of 8 — all NCERT Indian school physics, the target segment** |
| Those three | born-digital, 2,296–2,816 chars/page — **no OCR needed** |
| Merged R2+R3 prototype on those three | **22/22 chapters, 22/22 title-on-start-page** |
| Text-only sweep cost | 2.8–7.9 ms/page → **5.53 s on a 1,671-page book** |

Full evidence: `docs/reports/PHASE-1-TOC-SPIKE.md`.

---

## Decisions — TAKEN 2026-08-03 (Dev 1)

**D-A — This story breaks lesson generation until Phase 6, and breaks Dev 2's upload page now.**

The plan says `POST /lessons` becomes ingestion-only: stops creating a `lessons` row (`router.py:338`)
and stops enqueuing the pipeline (`:378`). But the endpoint that *replaces* it —
`POST /books/{book_id}/chapters/{chapter_id}/lessons` — is **Phase 6**. Phases 4 and 5 sit between.
So on merge:

- `LessonUploadResponse` currently returns `lesson_id`; ingestion-only has no lesson to return.
  Any client reading `lesson_id` breaks. `apps/web` Story 1-8 polls `GET /lessons/{lesson_id}`
  straight off that response.
- There is **no way to generate a lesson at all** between this story and Phase 6.

The brief's §3 rationale is "zero users today", which makes this survivable — but it is not
currently written down as a consequence anywhere, and Dev 2 owns the upload page.
**DECIDED: (a) — accept the gap.** Zero users today, so the cost is internal only. Consequences to
carry, not discover:
- Lesson generation is **unavailable from this merge until Phase 6 lands**. That is three phases.
- Dev 2's upload page (`apps/web`, Story 1-8) reads `lesson_id` off the upload response and polls
  `GET /lessons/{id}`. It **will break**. Dev 2 must be told before this merges, not after.
- Registered as a `D-nn` entry with the trigger *"Phase 6 lands"*, per binding rule 5.
Rejected: (b) keeping the old path behind a flag doubles the surface this story must keep working;
(c) pulling a Phase 6 endpoint forward makes this story two stories.

**D-B — `tier` has nowhere to go.** `POST /lessons` takes `tier` as a form field
(`router.py:255-261`) and writes it to `lessons.tier`. With no `lessons` row created, the parameter
is accepted and silently dropped. The plan moves `tier` to the Phase 6 endpoint, which is correct —
but this story must either reject the field or document that it is ignored. **DECIDED: reject with 422.** If `tier` is supplied to `POST /lessons`, return **422** naming the
Phase 6 endpoint that will accept it. Failing loudly beats accepting a parameter we no longer
honour — a silent drop is how a caller keeps sending T3 and keeps getting T2.

---

## Acceptance Criteria

**Detection — the ladder** (`docs/bmad/phase-3-chapter-detection-plan.md` §3)

1. **R1 outline** — `get_toc()` + the level heuristic (coarsest level with 4–80 entries and median
   span ≥ 3 pages). On the D2L fixture: **27 chapters, 27/27 start pages**. `boundary_confidence='toc'`.
2. **R3 heading-sweep** — pages whose first 4 non-blank lines open `CHAPTER <n>` (digits, ASCII
   number words, roman). Keeps the **first** page per chapter number; consecutive starts ≥ 3 pages
   apart; strictly increasing. `boundary_confidence='heading'`.
3. **R2 contents-page** — a page is contents-like if it has a bare `Contents`/`Table of Contents`
   header in its first 8 lines **or** ≥ 5 lines matching `N.M  Title  <page>`. The first section row
   under each `CHAPTER <n>` header gives that chapter's printed start page.
   `boundary_confidence='contents'`.
4. **R2 and R3 are MERGED, not sequential.** R3 is authoritative; chapters only R2 found are placed
   by **title-anchored search** — nearest non-contents page within a window whose first 400 chars
   carry the title. **No printed-page-to-PDF-index offset arithmetic** (Phase 1 measured a folio
   estimator at 28 % consensus and 2 pages wrong; title-anchored search resolved 8/8 with no offset).
5. **R4 font-signals** — existing `detect_headings()` (`nodes/structure_detection.py:29`),
   `boundary_confidence='font'`. Wired as a rung; **not tuned in this story**.
6. **R5 whole-document** — one chapter, `page_start=0`, `page_end=n-1`,
   `boundary_confidence='fallback'`. Always accepts. This is today's implicit behaviour made
   explicit and, critically, **labelled**.

**The acceptance gate** (applied to every rung; a failing rung falls through, R5 cannot fail)

7. All 7 rules enforced: ≥1 chapter · starts strictly increasing · consecutive starts ≥ 3 pages
   apart unless N=1 · **no start on a contents-like page** · no chapter > 40 % of the book unless
   N=1 · ≥ 80 % of starts carry their title in the first 400 chars · ranges within `[0, n-1]` and
   non-overlapping.
8. **Rule 4 is asserted independently of rule 6.** In the Phase 1 prototype the title check *passed*
   on two contents pages — a contents page contains every title in the book. A test must prove a
   contents page is rejected as a chapter start even though its text satisfies rule 6.

**Non-content filter**

9. Entries whose normalised title matches `contents`, `preface`, `foreword`, `acknowledgements`,
   `index`, `glossary`, `bibliography`, `references`, `notation`, `installation`, `answer key`,
   `exercises`, `about the authors`, `appendix *` are dropped. Unfiltered, OpenStax Biology offers
   "Index" as a lesson (6 of its 53 entries are front/back matter).
10. `chapter_index` is sequential from 0 and gap-free **over kept chapters**. Page ranges may have
    gaps where a non-content entry was dropped — ascending, non-overlapping, within `[0, n-1]`.

**The job**

11. `book_ingest_job(ctx, book_id)` registered in `WorkerSettings.functions`
    (`app/workers/main.py:100`). **No LangGraph, no LLM, no image render, no table scan** — asserted,
    not assumed.
12. Writes N chapter rows with real `page_start`/`page_end`, sequential `chapter_index`, and the
    `boundary_confidence` of the rung that produced them.
13. `books.status='ready'` on success, **`'failed'` on error** — `'failed'` is currently written
    nowhere in the codebase.
14. Text sweep runs in the **isolated subprocess** (`CLAUDE.md` §18), never in the FastAPI process.
15. A 1,000+ page book with an outline completes in **≤ 15 s** (measured budget: `get_toc()`
    0.03–1.76 s, sweep 5.53 s @ 1,671 p).

**Behaviour at the edges**

16. A **single-chapter PDF** → exactly 1 chapter row, not an error. NCERT ships most of its
    catalogue as one PDF per chapter (`ncert-keph1` → `keph101.pdf` … `keph108.pdf`), so this is the
    common shape for the target segment, not a degenerate case.
17. A PDF with **no usable signal** → 1 chapter, `'fallback'`, `books.status='ready'`.
18. A **corrupt PDF** → `books.status='failed'`, job does not hang.
19. Re-running `book_ingest_job` for the same book **does not duplicate rows** — Phase 2's
    `UNIQUE (book_id, chapter_index)` makes a naive re-run raise `23505`. Same class of defect the
    review caught in `chunk_node`.

**Router**

20. `POST /lessons` creates the `books` row, stores the PDF, enqueues `book_ingest_job`. Stops
    creating `lessons`/`lesson_jobs` rows and stops enqueuing `content_pipeline_job`.
21. Supplying `tier` to `POST /lessons` returns **422**, with a message naming the Phase 6 endpoint
    that will accept it. Never silently discarded.
22. The hardcoded chapter row at `graph.py:609-638` is **deleted**, including `"chapter_index": 1`.

**Verification**

23. Every rung is tested against the **real Phase 1 fixtures**, with the recorded numbers
    (D2L 27 chapters; NCERT XI Part 1 → 7 `heading`; NCERT XII Part 1 → 8 `contents`).
24. Detection is **pure functions over `(page_count, toc, page_texts)`** — no DB, no I/O — so every
    rung is testable without a Supabase mock (binding rule 2).
25. Repo-wide: CI gating scope green; `ruff check .` passes; `ruff format --check` and `mypy app`
    show no new findings; advisory full suite shows no new failures — all against a `main` baseline
    measured with the identical command (binding rule 1).

---

## Tasks / Subtasks

- [x] **T1 — D-A and D-B decided 2026-08-03:** accept the Phase 6 gap; reject `tier` with 422.
- [ ] **T2 — Detection module**, `app/modules/content/chapter_detection/` (AC1–10, AC24)
  - [ ] `types.py` — `DetectedChapter(title, page_start, page_end, chapter_index, boundary_confidence)`
  - [ ] `rungs.py` — R1/R2/R3/R4/R5 as pure functions over `(page_count, toc, page_texts)`
  - [ ] `gate.py` — the 7 acceptance rules; `filter.py` — the non-content blocklist
  - [ ] `ladder.py` — R1 → (R2 ⊕ R3 merged) → R4 → R5, one shared text sweep
- [ ] **T3 — RED: rung tests against the real fixtures** (AC23)
  - [ ] Commit small real-PDF fixtures, or a captured `(toc, page_texts)` JSON per book if the PDFs
        are too large — the numbers must be the Phase 1 numbers, not invented ones
  - [ ] A test that a contents page is rejected as a chapter start **while passing the title check** (AC8)
- [ ] **T4 — Text-only subprocess mode** (AC14)
  - [ ] Add a mode to `extract_subprocess.py` returning **per-page** texts, skipping render, OCR and
        `_page_table_count` (the 579 ms/page cost)
  - [ ] Preserve the existing argv contract — the current call is
        `sys.executable -m …extract_subprocess <pdf> <img_dir> <ocr_threshold>` (`graph.py:280-290`)
- [ ] **T5 — `book_ingest_job`** in `app/workers/jobs/book_ingest.py` (AC11–13, AC15–19)
  - [ ] Register in `WorkerSettings.functions`; idempotent re-run (AC19)
  - [ ] `books.status` transitions, including `'failed'`
- [ ] **T6 — Router + graph cleanup** (AC20–22)
- [ ] **T7 — Repo-wide gates + tracker update** (AC25)
  - [ ] Tracker Phase 3 with **observed numbers**, per the update protocol
  - [ ] `D-nn` entries: image-only scans, non-English chapter tokens, merged multi-part books

---

## Dev Notes

### Files being modified — current state

**`app/modules/content/router.py` — `POST /lessons` (`:242`)**
Order today: `books` → `lessons` → `lesson_jobs` → storage upload → `enqueue_job("content_pipeline_job", lesson_id, _job_id=f"pipeline:{lesson_id}")` (`:378`).
Note the `_job_id` dedup: if ARQ dedupes it returns `None` and the handler **deletes all created rows
and returns 409** (`:380-392`). Whatever `book_ingest_job` uses for `_job_id`, that cleanup path must
stay coherent. Rate limit `5/minute` per user, 50 MB cap (`:48`) — both stay.

**`app/workers/main.py`** — `WorkerSettings.functions` at `:100` has a literal
`# Add future jobs here:` comment. `max_tries=3`, `retry_jobs=True`, `job_timeout` from
`ARQ_JOB_TIMEOUT_S` (default 1800), `queue_name = PIPELINE_QUEUE`, `max_jobs=5`.
**Because `retry_jobs=True` and `max_tries=3`, AC19 (idempotent re-run) is not optional** — a retry
after a partial write will otherwise hit `23505` and strand the book, exactly as `chunk_node` did.

**`app/modules/content/pipeline/nodes/extract_subprocess.py`** — `extract_page_data(pdf_path, img_dir, ocr_threshold)`
already builds `page_texts: list[str]` per page and then **flattens it into `raw_text`**. The
per-page data this story needs is already computed and thrown away. Returns
`{raw_text, page_count, image_files, font_blocks, tables_detected, docling_pages}`.
CLI usage string at `:517`.

**`app/modules/content/pipeline/nodes/structure_detection.py:29`** —
`detect_headings(raw_text: str, font_blocks: list[dict]) -> list[dict]`, each
`{"text", "level": chapter|section|topic, "char_offset"}`. **Known defect D28: the font strategy
outranks the explicit `Chapter N:` regex**, so a chapter can rank below its own subsections. D28 is
*pinned, not fixed* — do not "fix" it here; R4 must tolerate it.

**`app/modules/content/pipeline/graph.py:609-638`** — the hardcoded chapter row, now an **upsert**
with `on_conflict="book_id,chapter_index"` (added during the Phase 2 review to survive ARQ retries).
Deleting this block removes that concern with it.

### Do not reinvent

- `_build_sub_pdf` (`extract_subprocess.py:144-153`) is already a page-range primitive — **Phase 4**
  will use it. Do not build a second one here.
- `chapters` already has `book_id`, `page_start`, `page_end`, `chapter_index` — no new columns.
  Phase 2 added `boundary_confidence` and the `UNIQUE` constraint. Nothing further is needed.
- The Phase 1 spike scripts are **not** in the repo (scratchpad only). The algorithms are specified
  in `phase-3-chapter-detection-plan.md` §3; re-implement from the spec, and match the numbers.

### Pitfalls Phase 1 already paid for

1. **A contents page contains every chapter title**, so "the title appears on the start page" passes
   there. The v1 prototype accepted PDF pages 1 and 2 of NCERT XII Part 1 as chapters 1 and 3 — and
   the title check *confirmed* them. Monotonicity did not help; contents pages are early and in
   order. This is why AC8 exists as a separate criterion.
2. **Folio-based offset derivation does not work** — 28 % consensus, 2 pages wrong. Title-anchored
   search resolved 8/8 with no offset at all. Do not reintroduce the arithmetic.
3. **Back matter yields false starts** — `p 175 Chapter 1`, `p 186 CHAPTER 9` are pages *referencing*
   a chapter. Keep the first page per chapter number and enforce monotonicity.
4. **Chapter sizes vary far more than expected** — D2L's Appendix A is 138 pages, several chapters
   are 2–4. Do not assume ~40.

### Testing standards

- Markers are `--strict-markers`: `unit`, `integration`, `slow`, `live_eval`, `postgres`.
- `filterwarnings = ["error"]` — a warning fails the suite.
- **The repo's `test_migration_*_schema.py` files parse SQL text and never open a connection. Do not
  copy that pattern.** The Phase 2 harness
  (`tests/integration/test_migration_chapters_book_scoped.py`) is the model: real Postgres, real
  SQLSTATEs, provisions its own databases in a container.
- Phase 2 left a reusable local Postgres: container `transformed-local-db` on `127.0.0.1:55432`,
  db `transformed`, user `postgres`, password `localdev` — full chain + migration applied.

### Project structure

New: `app/modules/content/chapter_detection/` (pure), `app/workers/jobs/book_ingest.py`.
Modified: `app/workers/main.py`, `app/modules/content/router.py`,
`app/modules/content/pipeline/nodes/extract_subprocess.py`, `…/pipeline/graph.py`.
Tests: `tests/unit/test_chapter_detection_*.py` (pure, no DB), `tests/integration/` for the job.

### References

- [Source: docs/bmad/phase-3-chapter-detection-plan.md] — the ladder, gate, budget, known gaps
- [Source: docs/reports/PHASE-1-TOC-SPIKE.md] — every number quoted above
- [Source: docs/book-scale-phase-tracker.md#Phase-3] — exit criterion and the 13-step e2e test
- [Source: docs/stories/1-9-chapters-storable-migration.md] — Phase 2, and the review findings that
  shaped AC8/AC19
- [Source: CLAUDE.md#Defect-Register] — binding rules 1, 2, 4, 5, 7; D28 (pinned `detect_headings`
  precedence), D24 (CI advisory step), D40 (pre-existing `tests/integration` state leak)

---

## Dev Agent Record

### Agent Model Used

_not yet run_

### Debug Log References

### Completion Notes List

### File List
