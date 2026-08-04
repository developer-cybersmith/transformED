# Phase 3 Re-Plan — Chapter Detection Ladder

**Owner:** Dev 1
**Created:** 2026-08-03
**Status:** re-planned, not started — blocked on Phase 2 (`✅ Verified` required)
**Supersedes:** the Phase 3 work list in `docs/bmad/book-scale-implementation-brief.md` §5
**Evidence:** `docs/reports/PHASE-1-TOC-SPIKE.md` (Phase 1, `✅ Verified` 2026-08-03)
**Tracker:** `docs/book-scale-phase-tracker.md` → Phase 3

---

## 1. Why Phase 3 is being re-planned

Phase 1 measured `get_toc()` on 8 real textbooks. It works — 164 chapters, 99.4 %
strict start-page accuracy — on 5 of them, and on **none** of the three NCERT Indian
school physics books, which are the product's actual market.

The original plan treated everything past `get_toc()` as a single fallback to the
existing `detect_headings()`. The spike showed that is the wrong shape, for two
measured reasons:

1. **The failing books are born-digital**, not scans (2,300–2,800 chars/page). A
   text-only detector resolves them. No OCR, no vision model, no LLM.
2. **The two text signals are complementary, not alternatives.** On NCERT XI Parts 1
   and 2 the in-body heading sweep resolves every chapter and the contents page is
   unparseable; on NCERT XII Part 1 the reverse is exactly true. Running them as an
   either/or ladder solves 2 of 3 books. **Merging them solves 3 of 3.**

A prototype of the merged detector was run in the spike and resolved **22 of 22
chapters across all three books, with 22/22 title-on-start-page accuracy.**

---

## 2. Rung naming — read this before comparing to the brief

The brief §8 numbered a hypothetical ladder. The measured ladder is not the same
shape, and reusing its numbers would silently redefine them. Rungs are therefore
**named**, and mapped here once:

| This plan | Brief §8 equivalent | Status |
|---|---|---|
| **R1 outline** — `get_toc()` + level heuristic | rung 1 | proven, unchanged |
| **R2 contents-page** — parse the printed contents page | rung 2 | **in scope** |
| **R3 heading-sweep** — in-body chapter openers | *no equivalent — new* | **in scope** |
| **R4 font-signals** — existing `detect_headings()` | rung 3 | wired, not tuned |
| **R5 whole-document** — one chapter, today's behaviour | *no equivalent* | **in scope** (terminal) |
| — chapter scoring | rung 4 | **deferred** |
| — LLM page-spine check (~$0.0085/book) | rung 5 | **deferred** |

R2 and R3 are the added scope. R4 already exists at
`apps/api/app/modules/content/pipeline/nodes/structure_detection.py:29` and is kept as
a rung but is **not** tuned in this phase. R5 is new and is what makes the ladder
total — today there is no defined behaviour when detection finds nothing.

---

## 3. The detector

One ARQ job, `book_ingest_job(book_id)`. No LangGraph, no LLM, no page rendering, no
table scan.

```
                 ┌─ R1 outline ─────────────────┐
 open PDF ──────►│ get_toc() + level heuristic  │──► accept? ──► store
                 └──────────────────────────────┘        │
                                                     reject
                                                         ▼
                 ┌─ one text-only page sweep ───────────────────┐
                 │ pypdfium2 get_text_bounded(), ~3-8 ms/page   │
                 │ classify contents-like pages once            │
                 └──────────────┬───────────────────────────────┘
                                ├──► R3 heading-sweep ──┐
                                └──► R2 contents-page ──┤
                                                        ▼
                                                    MERGE ──► accept? ──► store
                                                                  │
                                                              reject
                                                                  ▼
                                              R4 font-signals ──► accept? ──► store
                                                                  │
                                                              reject
                                                                  ▼
                                              R5 whole-document (always accepts)
```

**The single text sweep is shared.** R2 and R3 both read it; it is never done twice.

### R1 — outline

Unchanged from the Phase 1 spike. `get_toc()`, group entries by level, choose the
coarsest level with 4–80 entries and median span ≥ 3 pages. Correct on 5/5 books with
no manual override, worst case 1.76 s. `boundary_confidence = 'toc'`.

### R3 — heading-sweep

For each page not classified contents-like, examine the first 4 non-blank lines for
`CHAPTER <n>` (digits, ASCII number words, or roman). Title is the remainder of the
line, or the next line. Then:

- keep the **first** page for each chapter number — back matter references the same
  chapter later (`p 175 Chapter 1`, `p 186 CHAPTER 9`)
- require consecutive starts to be **≥ 3 pages apart**
- require the sequence to be **strictly increasing**

`boundary_confidence = 'heading'`.

### R2 — contents-page

A page is **contents-like** if a line in its first 8 carries a bare `Contents` /
`Table of Contents` header, **or** ≥ 5 of its lines match `N.M  Title  <page>`.
Concatenate the contiguous block and parse `CHAPTER <n>` headers; the **first section
row beneath each header** carries that chapter's printed start page.

`boundary_confidence = 'contents'`.

### The merge, and the mechanism that was dropped

Chapters found by R3 are authoritative. For every chapter R2 found that R3 did not,
resolve its page by **title-anchored search**, not by page-number arithmetic:

> Search outward from the predicted page for the nearest **non-contents** page whose
> first 400 characters carry the chapter title. Accept the nearest hit.

**Printed-page-to-PDF-index offset derivation is explicitly not implemented.** Phase 1
flagged it as required design work; the prototype showed it is not. A folio-mode
estimator reached only 28 % consensus and was 2 pages wrong on NCERT XII Part 1, while
title-anchored search resolved **8 of 8** chapters in that same book with no offset at
all. Where R3 supplies at least one confirmed chapter, its page difference seeds the
search window; where it supplies none, the search covers the document, constrained by
monotonicity and the 3-page floor.

This is a real simplification against the Phase 1 write-up, and it is the reason
design item (1) recorded there is now closed rather than scheduled.

### R5 — whole-document

One chapter, `page_start = 0`, `page_end = n-1`, title from document metadata or
filename, `boundary_confidence = 'fallback'`. This is today's implicit behaviour made
explicit and, critically, **labelled** — so a downstream consumer can tell a real
chapter list from a degenerate one. `books.status` is still `'ready'`; only genuine
errors write `'failed'`.

---

## 4. Acceptance gate

The same gate is applied to every rung's candidate set. A rung that fails falls
through; R5 cannot fail.

| # | Rule | Why |
|---|---|---|
| 1 | ≥ 1 chapter | — |
| 2 | Starts strictly increasing | non-monotonic outlines exist (D2L level 3) |
| 3 | Consecutive starts ≥ 3 pages apart, unless N = 1 | kills contents-page false starts |
| 4 | No start on a contents-like page | see §5 |
| 5 | No chapter > 40 % of the book, unless N = 1 | catches a collapsed detection |
| 6 | ≥ 80 % of starts carry their title in the first 400 chars | measured 100 % on the prototype |
| 7 | Page ranges within `[0, n-1]`, non-overlapping | Phase 4 slices on these |

**Rule 6 is necessary but not sufficient, and that is the point.** In the v1 prototype
the title check *passed* on two pages that were not chapters at all — a contents page
contains every title in the book. Rule 4 exists because rule 6 was fooled. Any
implementation that keeps 6 and drops 4 will regress to the v1 result silently.

---

## 5. Non-content filtering

Phase 1 §4: outlines list front and back matter as peers of real chapters — 6 of 53 in
OpenStax Biology, 8 of 20 in MML. Unfiltered, the chapter picker offers "Index" as a
lesson.

Drop entries whose normalised title matches: `contents`, `preface`, `foreword`,
`acknowledgements`, `index`, `glossary`, `bibliography`, `references`, `notation`,
`installation`, `answer key`, `exercises`, `about the authors`, `appendix *`.

**Consequence that changes an existing acceptance test:** dropped entries leave gaps in
page coverage. The current Phase 3 e2e test asserts page ranges "covering the book".
That assertion is now wrong and is amended in the tracker to: *ascending,
non-overlapping, within bounds — gaps permitted only where a non-content entry was
dropped.*

`chapter_index` stays sequential and gap-free **over kept chapters**, starting at 0.

---

## 6. Impact on Phase 2 — must be settled before Phase 2 starts

Phase 2 is a **frozen contract requiring 4-developer review** and has not started, so
this costs no rework — but it must be folded in before that review, not after.

`chapters.boundary_confidence` was specified as `toc | font | fallback`. The measured
ladder has five distinct provenances, and collapsing them destroys the one signal that
tells us which detector is failing in production:

```
boundary_confidence ∈ ('toc', 'contents', 'heading', 'font', 'fallback')
```

Nothing else in the Phase 2 migration changes.

---

## 7. Work list

1. `book_ingest_job(book_id)` in `apps/api/app/workers/jobs/` — orchestrates the ladder,
   writes N chapter rows, sets `books.status`.
2. A `chapter_detection` module under `modules/content/` holding R1–R5, the acceptance
   gate, and the non-content filter. **Pure functions over `(page_count, toc, page_texts)`**
   — no DB, no I/O, so every rung is testable against a fixture without a Supabase mock
   (binding rule 2).
3. PDF parsing stays in the **isolated subprocess** (`CLAUDE.md` §18) — the text sweep
   is added to `extract_subprocess.py`'s contract as a text-only mode that skips
   rendering and the 579 ms/page table scan.
4. `books.status = 'failed'` on error — currently never written anywhere.
5. `POST /lessons` becomes ingestion-only: creates the `books` row, stores the PDF,
   enqueues the job. Stops creating a `lessons` row (`router.py:338`) and stops enqueuing
   the pipeline (`:378`).
6. Delete the hardcoded single chapter row at `graph.py:609-638`, including
   `"chapter_index": 1` (`:624`) and the title/range read off `sections[0]`/`sections[-1]`.
7. Register entries for what stays deferred (binding rule 5 — no `TODO` without a `D-nn`):
   image-only scans, non-English chapter tokens, chapter scoring, LLM page-spine.

---

## 8. Budget

Measured, this session, in `apps/api/.venv`:

| Step | Cost |
|---|---|
| R1 `get_toc()` | 0.03–1.76 s (1,671-page book: 0.03 s) |
| Text-only sweep | **2.8–7.9 ms/page** → 4.15 s @ 1,475 p, 5.53 s @ 1,671 p |
| R2 / R3 / merge | pure string work, negligible |
| LLM / OCR / rendering / table scan | **none** |

Target: `books.status = 'ready'` within **15 s** for a 1,000-page book on either path.
For contrast, the table scan this path avoids costs 579 ms/page — 11.1 minutes on the
same book.

---

## 9. Acceptance criteria

| AC | Criterion |
|---|---|
| AC1 | A 1,000+ page book **with** an outline → correct chapter rows, `boundary_confidence='toc'`, ≤ 15 s |
| AC2 | NCERT XI Physics Part 1 (no outline) → **7** chapters, `'heading'` |
| AC3 | NCERT XII Physics Part 1 (no outline, no in-body openers) → **8** chapters, `'contents'` |
| AC4 | Every detected start carries its title in the first 400 chars |
| AC5 | No chapter starts on a contents-like page — asserted directly, not implied by AC4 |
| AC6 | Non-content entries dropped; `chapter_index` sequential from 0 over kept chapters |
| AC7 | A **single-chapter** PDF → exactly 1 chapter row, not an error (NCERT ships most of its catalogue this way) |
| AC8 | A PDF with no usable signal → 1 chapter, `'fallback'`, `books.status='ready'` |
| AC9 | A corrupt PDF → `books.status='failed'` |
| AC10 | No LLM call, no OCR, no page render, no table scan on this path — asserted, not assumed |
| AC11 | Text sweep runs in the isolated subprocess, never in the FastAPI process |

---

## 10. Known gaps, to be registered rather than assumed

| Gap | Disposition |
|---|---|
| **Image-only scans.** No genuinely scanned textbook was tested. R2/R3/R4 all need a text layer, so such a book lands on R5 and becomes one chapter. | Register `D-nn`; revisit only if a real upload hits it. OCR already exists (Tesseract) but is not on this path. |
| **Non-English chapter tokens.** R3's pattern is English-only. NCERT ships Hindi editions (`Bhautiki-I/II`) using `अध्याय`. **Untested.** | Extend the token list in this phase; add a Hindi fixture. Do not claim coverage without one. |
| **Publisher PDFs** (Pearson, McGraw-Hill) could not be tested legally. | Unknown, unmeasurable pre-launch. |
| **Merged multi-part books.** A user concatenating NCERT Part 1 + Part 2 produces duplicate chapter numbers (both start at 1 / restart at 9). R3 keeps the first and drops the second. | Register `D-nn`. |
