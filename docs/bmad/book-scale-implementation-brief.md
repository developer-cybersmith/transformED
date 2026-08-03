# Implementation Brief — Book-Scale Ingestion

**Owner:** Dev 1
**Created:** 2026-08-03
**Status:** approved, not started
**Tracker:** `docs/book-scale-phase-tracker.md`
**Related:** `docs/decisions/ADR-002-book-scale-ingestion-and-chapter-lessons.md`,
`docs/decisions/BOOK-SLICING-AND-PDF-LIFECYCLE.md`

---

## 1. Context

Sprint 1 and Sprint 2 were built and validated against `demo-assets/sample-chapter.pdf`
(41 pages). Every default in the pipeline hardened around that one document.

Feeding the pipeline a real book does **not** fail loudly. It produces a lesson marked
`ready`, built from roughly **4% of the source**, with the remaining 96% dropped behind a
log warning. A failure we can see is manageable; a success that is wrong is not.

The specification has said something different since day one
(`CLAUDE.md` §9, `docs/bmad/epics/epic-1-content-pipeline.md:47,56`):

> **Phase A — Book Ingestion** — once per book, ~2–5 min
> **Phase B — Chapter Generation** — per chapter, student-triggered, ~5–15 min

A student uploads a book once, then learns any chapter from it. **The concept is not
misaligned; the code is.**

This was never a recorded decision. The one-chapter assumption exists only as an inline
comment at `apps/api/app/modules/content/pipeline/graph.py:609`, carrying no `D-nn`
register ID — which binding rule 5 in `CLAUDE.md` forbids. That is precisely the failure
mode the register was created to prevent.

### Why it was not caught earlier

The evaluation harness crashed on all five test documents and **wrote a success-shaped
result file anyway** (`apps/api/tests/evals/runner.py:277-316`). The mechanism meant to
catch this reported that everything was fine.

---

## 2. End goal — the only success criterion

> **Upload a 1,000-page PDF. Sprint 1 and Sprint 2 run to completion without failing.**

Nothing else. Sprint 3 begins after this is proven, not before.

---

## 3. Explicitly out of scope

Each is registered with a `D-nn` ID and scheduled separately. None is required for the end
goal above.

| Deferred | Why |
|---|---|
| Splitting the LangGraph into two compiled graphs | Not needed — see §4 |
| Cost-tracking split, `progress_pct`, `/admin/costs` | Alignment work, not a blocker |
| Book-scoped storage re-pathing, content-hash dedup | Optimisation |
| Frontend chapter picker and book library | Dev 2, follows this |
| RLS re-rooting | Zero users today; follows immediately after |
| WebSocket auth hole, session close-out, CES/attention, tutor state machine | Sprint 3 |
| Fallback ladder rungs 2–5 | Only if Phase 1 shows rung 1 is insufficient |

**One exception to "defer":** the WebSocket auth gap
(`apps/api/app/modules/tutor/websocket.py:139-146`) lets anyone who guesses a session ID
drive another student's tutor and read their messages. It is out of *this* scope, but it is
a security defect and is being raised with Dev 4 immediately rather than waiting for a
sprint boundary.

---

## 4. Approach — and why the estimate collapsed

An earlier estimate put this at ~6 weeks, assuming the pipeline had to be split into two
compiled graphs. **That is not required.**

For a big book to work, the pipeline only needs to **see one chapter at a time**. Feed it
pages 272–306 instead of 1–1151 and every existing default becomes correct again — because
~40 pages is exactly what it was built for. **All eleven generation nodes stay untouched.**

Two measured facts make this cheap:

1. **`get_toc()` reads a book's chapter list without extracting any text** — no page
   rendering, no table scanning. **4 seconds** on a 1,151-page book. So chapter detection
   does not need the LangGraph at all; it becomes a small ARQ job.
2. **Re-extracting one chapter's pages costs ~26 seconds.** So the "ingest once, reuse
   everywhere" optimisation can be skipped for now and the system is still fast. It
   remains the correct end state, just not a prerequisite.

### Measured evidence

All measured this session in the project venv (`apps/api/.venv`, `pypdfium2` 4.30.0)
against *Dive into Deep Learning* — 1,151 pages, 44.7 MB.

| Measurement | Result |
|---|---|
| `get_toc()` entries / top-level chapters | 1,335 / **27** |
| Time to read the chapter list | **4 s** |
| Chapter start-page accuracy | **27 / 27** |
| Text extraction, whole book | 7 ms/page → **8.3 s** |
| 300-DPI render | 61 ms/page → 1.2 min |
| **pdfplumber table scan** | **579 ms/page → 11.1 min** (≈90% of extraction cost) |
| LLM page-spine fallback, if ever needed | 57k tokens → **$0.0085** per book |

**The slow part was never reading the PDF.** It was scanning every page for tables — work
that chapter detection does not need, and that per-chapter processing shrinks from 11
minutes to ~26 seconds.

**Caveat:** all five repo fixtures and the demo chapter return **zero** bookmarks. They are
script-generated, so this says nothing about real books — but it does mean rung 1 has never
been exercised in CI. Phase 1 exists to close that gap.

### Three pieces already exist and were never used

1. `chapters` already has `book_id`, `page_start`, `page_end`, `chapter_index`
2. `extract_subprocess.py` already computes per-page text, then flattens it away
3. `_build_sub_pdf` (`extract_subprocess.py:144-153`) is already a page-range primitive

---

## 5. The phases

Order is forced by dependency. Each phase leaves the system working.
**Full exit criteria and test procedures live in `docs/book-scale-phase-tracker.md`.**

### Phase 1 — Prove chapter detection *(spike, no production code)*

Run `get_toc()` against 3–4 real target textbooks; record usable-chapter-list rate and
start-page accuracy.

API confirmed present: `PdfDocument.get_toc()`; `PdfOutlineItem` fields
`(level, title, is_closed, n_kids, page_index, view_mode, view_pos)`.

Level-selection heuristic already prototyped: pick the coarsest level with 4–80 entries and
a median span ≥ 3 pages. On the real book this picked level 0 → 27 chapters; on an academic
paper it picked level 1 → 23 sections.

**This is the only real unknown and it gates the shape of Phase 3.**

### Phase 2 — Make chapters storable

New migration:

- `chapters.lesson_id` → **nullable** (today `NOT NULL REFERENCES lessons ON DELETE CASCADE`,
  `supabase/migrations/20260611000000_initial_schema.sql:132`)
- Add `lessons.chapter_id` (nullable, FK)
- Add `UNIQUE (book_id, chapter_index)` — no such constraint exists
- Add `chapters.boundary_confidence` (`toc` | `font` | `fallback`)

Direction is **permissive**, so no existing row can be invalidated. Note `chunks.chapter_id`
is `NOT NULL` — that chain is why a chapter is currently impossible without a lesson.

**FROZEN CONTRACT — 4-developer review required (`CLAUDE.md` §16).**

### Phase 3 — Detect and store real chapters at upload

New ARQ job `book_ingest_job(book_id)`. Does **not** use the graph.

- Read the chapter list via `get_toc()`; fall back to the existing `detect_headings()`
  (`nodes/structure_detection.py:29`) over text-only extraction when absent
- Write **N** chapter rows with real page ranges, sequential `chapter_index`, and
  `boundary_confidence`
- Set `books.status='ready'` (pattern at `graph.py:914`) and `'failed'` on error — `'failed'`
  is currently never written anywhere
- `POST /lessons` (`content/router.py:242`) becomes ingestion-only: creates the `books` row,
  stores the PDF, enqueues this job. It stops creating a `lessons` row (`:338`) and stops
  enqueuing the pipeline (`:378`)

Replaces the hardcoded single chapter row at `graph.py:609-638` — including
`"chapter_index": 1` (`:624`) and the title/page range read off `sections[0]`/`sections[-1]`
(`:610-612`), which on a real book names the chapter after its copyright page and claims to
span pages 1–1151.

### Phase 4 — Extract one chapter's pages

- Add `page_start`/`page_end` to the subprocess argv contract and to `extract_page_data(...)`
  — signature today is `(pdf_path, img_dir, ocr_threshold)`
  (`extract_subprocess.py:436-445`)
- Change `for page_idx in range(page_count)` (`extract_subprocess.py:460`) to the bounded range
- Reuse `_build_sub_pdf` (`:144-153`)
- Skip the per-page table scan `_page_table_count` (`:469`) during chapter detection

### Phase 5 — Chapter-scoped generation

- `chapter_id` becomes a required input on `PipelineState`
- `extract_node` (`graph.py:280-330`) resolves the chapter's page range and passes bounds
- **All remaining nodes untouched** — they now receive ~40 pages, the size they were built for
- Drop the checkpoint-based `chapter_id` recovery at `graph.py:738` and `:3742` (closes D33)
- Add a cheap idempotency guard so regenerating a chapter does not re-embed, protecting the
  "never regenerate stored chunk embeddings" rule

Caps become correct **without being changed**: `structure_max_sections=15` (`config.py:301`)
and the 6,000-char prompt cap (`graph.py:1751-1770`, warns at `:1763`) stop binding at
chapter scale, and `_MAX_PHASE1_SECTIONS=60` (`graph.py:4173`) stops silently dropping
sections (`graph.py:4243-4254`).

### Phase 6 — Endpoints

The content router has exactly three routes today, none mentioning books or chapters
(`router.py:242`, `:426`, `:477`).

- `GET /books`
- `GET /books/{book_id}/chapters` — makes `chapters` readable; today it has one INSERT and
  **zero SELECTs** in the entire backend
- `POST /books/{book_id}/chapters/{chapter_id}/lessons`
- **`tier` moves here** off the upload form (`router.py:255-261`). The column placement
  (`lessons.tier`) is already right; only the collection point is wrong. A student must be
  able to take chapter 3 at T1 and chapter 7 at T3 from one book.
- Add a page-count gate beside the existing 50 MB cap (`router.py:48`)

### Phase 7 — Prove it end to end

- Commit a real book-scale fixture **with** a bookmark tree and one **without**
- Integration test: chapter count, page ranges, valid package, **no truncation warning**
- A guard that fails if `chapter_index` reverts to a constant or a cap silently moves
- One green eval run as the calibration baseline

---

## 6. What does not change

Worth stating plainly, because it is most of the system:

- **All eleven generation nodes**, their prompts, and their Pydantic response models
- **Learner Mode tier logic** — T1 20–25 / T2 12–15 / T3 6–8 slides; quiz bands per segment.
  These are chapter-shaped numbers that become correct the moment one lesson = one chapter
- **The fan-out / fan-in machinery**, the reducer channels, the atomic checkpoint RPC, and
  the per-attempt `thread_id` uniquifier
- **The provider layer** — LLM, embeddings, image, TTS behind abstract interfaces, with
  retry, circuit breaker, and the Sarvam → Azure → Browser fallback chain
- **The player, quiz, and teach-back UI**, and session minting
- **Extraction internals** — `pypdfium2` + `pdftext` + page-scoped `docling` + 300-DPI
  rendering + the OCR trigger threshold. Right tools, right licensing
- **Upload safety** — magic bytes, MIME check, dual size enforcement, rate limiting, cleanup
  on failure
- **Most of the schema** — the migration is constraints and one direction reversal, not new
  columns

---

## 7. Process

Per `CLAUDE.md`, each phase is story-first: the story file is committed **alone** and pushed
before any implementation commit, then RED → GREEN → REFACTOR, then a 5-agent
`/bmad-code-review` before merge. Sprint 2 work shares one branch.

Verification scope is **repo-wide**, never "touched files" (binding rule 1).

**Phase gate:** a phase is complete only when tested end to end and observed working. See
the gate rule at the top of `docs/book-scale-phase-tracker.md`.

---

## 8. Open risk

Chapter detection on books with **no bookmark tree and no clean text layer**. Scanned books
carry no font metadata at all, and our 120-page fixture already yields zero headings from
3,000 font spans.

**Phase 1 resolves this before any code is committed.** If rung 1 proves insufficient, add
fallback rungs 2–5 (printed contents page, position/font signals we already discard, chapter
scoring, and a ~$0.0085 LLM page-spine check) and re-plan before proceeding.
