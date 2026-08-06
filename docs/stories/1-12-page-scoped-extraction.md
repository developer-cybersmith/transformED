# Story 1.12: Extract one chapter's pages (book-scale Phase 4)

Status: review

**Sprint:** Book-scale ingestion, Phase 4 of 9
**Owner:** Dev 1
**Branch:** `book-scale/phase-4-page-scoped-extraction` — from `book-scale/integration`, not `main` (D41)
**Depends on:** Phase 3.5 ✅ Verified 2026-08-04
**Blocks:** Phase 5 (chapter-scoped generation)

---

## Story

As **the content pipeline**,
I want **to extract only the pages of one chapter**,
so that **generation sees ~40 pages — the size it was built and validated for — instead of 1,151**.

## Context

Every default in the pipeline hardened around `demo-assets/sample-chapter.pdf` (41 pages). Phases
1–3.5 established *where* chapters are: the real book yields 21 chapters, `ch9` at pages 272–306.
This story makes the extractor able to read just those pages. **No generation node changes here** —
that is Phase 5. This is the primitive Phase 5 consumes.

Phase 1 measured the prize: whole-book extraction costs 11.1 minutes, ~90 % of it the pdfplumber
table scan at 579 ms/page. A ~40-page chapter should cost about 26 s.

---

## THE CONTRACT — implementer and test-author both build to this

Two agents work from this section in parallel, in different files. It is the single source of
truth; if it is wrong, say so rather than diverging from it.

### Signatures

```python
def extract_pdf(
    pdf_path: str, img_dir: str, ocr_threshold: int,
    page_start: int | None = None, page_end: int | None = None,
) -> dict[str, Any]: ...

def extract_text_only(
    pdf_path: str, front_pages: int = 0, head_chars: int = 0,
    page_start: int | None = None, page_end: int | None = None,
) -> dict[str, Any]: ...
```

### CLI (both forms stay backward compatible)

```
extract_subprocess <pdf_path> <img_dir> <ocr_threshold> [page_start] [page_end]
extract_subprocess --text-only <pdf_path> [front_pages] [head_chars] [page_start] [page_end]
```

### Semantics

- `page_start` / `page_end` are **0-based and INCLUSIVE**, matching `DetectedChapter` and
  `chapters.page_start/page_end`. Chapter 9 of the real book is `(272, 306)` → 35 pages.
- **Both omitted → whole document, byte-identical behaviour to today.** This is non-negotiable:
  `graph.py:280-290` still calls the 3-argument form and must not change.
- Only one supplied → error. A half-specified range is a bug, not a default.
- Out of range (`page_start < 0`, `page_end >= page_count`, `page_start > page_end`) → **exit
  non-zero with a message naming the bad value and the document's page count.** Never clamp
  silently: a clamped range means Phase 5 generates a lesson from the wrong pages and nothing says so.

### Return shape

Existing keys keep their existing meanings. Three keys are added:

| Key | Meaning |
|---|---|
| `page_count` | **UNCHANGED — the document's total page count.** Callers depend on it. |
| `extracted_page_count` | pages actually extracted (`page_end - page_start + 1`, or `page_count` when unbounded) |
| `page_offset` | `page_start`, or `0` when unbounded |
| `page_texts` (text-only mode) | the **slice only** — `page_texts[0]` is the page at `page_offset` |

### Page numbering — the part that will bite

`page_num = page_idx + 1` (`extract_subprocess.py:463`) feeds image storage paths and log lines.
It **MUST stay absolute** (real book page). If it becomes chapter-relative, every chapter's images
collide in storage at `page_1.png`, and a slide referencing "page 3" means three different pages in
three different lessons. Absolute page numbers, chapter-relative list indices — keep the two
straight and say which is which at each site.

---

## Acceptance Criteria

1. `extract_pdf` and `extract_text_only` accept `page_start`/`page_end` per the contract above.
2. The extraction loop iterates the bounded range, not `range(page_count)`
   (`extract_subprocess.py:460`, `:577`).
3. **Omitting bounds reproduces today's behaviour exactly** — same keys, same values, same page
   numbering. Proven by extracting a small PDF both ways and comparing.
4. Out-of-range or half-specified bounds exit non-zero with a diagnostic naming the bad value.
   **Never clamped.**
5. Extracting pages 272–306 of the real 1,151-page book returns **that chapter's text and only
   that chapter's** — and **page 0's content is provably ABSENT** from the output.
6. `extracted_page_count == 35` for `(272, 306)`; `page_offset == 272`; `page_count == 1151`.
7. Image filenames and log page numbers are **absolute** — a chapter starting at page 272 produces
   `page_273...`, not `page_1...`.
8. **`_extract_font_blocks` is bounded too.** It currently runs `pdftext.dictionary_output` over the
   WHOLE document (`:382-394`) regardless of any range — leaving it unbounded means a "35-page"
   extraction still parses 1,151 pages, defeating the phase. Build a sub-PDF with the existing
   `_build_sub_pdf` (`:144-153`) and **remap the returned page numbers by `+page_start`** so they
   stay absolute.
9. **The docling table-run splice stays consistent.** `_convert_table_runs(pdf_doc, pdf_path,
   page_texts, table_page_idxs, page_count)` (`:493`) mixes absolute page indices (for
   `_build_sub_pdf`) with `page_texts` list positions (for the splice). Under bounds those bases
   diverge. Make the base explicit; a silent off-by-`page_start` here corrupts table markdown into
   the wrong pages.
10. Wall-clock for a ~35-page chapter of the real book is **recorded**, and is far below the
    whole-document cost. Phase 1's baseline for the comparison: 11.1 min whole-book, ~26 s expected
    for a chapter.
11. Repo-wide, against a `main` baseline measured with the identical command: gating scope green;
    `ruff check .` clean; `ruff format --check` and `mypy app` show no new findings.

---

## Tasks / Subtasks

- [ ] **T1 — Implement the contract** in `extract_subprocess.py`: both functions, `main()` argv,
      bounded loops, validation, the three new return keys. (AC1–4, AC6, AC7)
- [ ] **T2 — Bound `_extract_font_blocks`** via `_build_sub_pdf` + page-number remap. (AC8)
- [ ] **T3 — Fix the table-run index base** so absolute and relative indices cannot be confused. (AC9)
- [ ] **T4 — Tests** in `tests/unit/test_extract_page_bounds.py`, written to the contract. (AC1–9)
- [ ] **T5 — Real-book verification** on pages 272–306, with the timing recorded. (AC5, AC10)
- [ ] **T6 — Repo-wide gates + tracker update** with observed numbers. (AC11)

---

## Dev Notes

### What NOT to change

- **`graph.py:280-290` still calls the 3-argument form.** Passing bounds from `extract_node` is
  **Phase 5**, not this story. If the 3-argument call changes behaviour, this story has failed.
- Do not touch the chapter-creation block at `graph.py:609-651`. It goes in Phase 5, when a real
  `chapter_id` first exists — `chunks.chapter_id` is `NOT NULL` and `chapter_id` from that block is
  consumed at `:659`.
- `--text-only`'s `front_pages`/`head_chars` truncation (Story 1-10) stays. Note the interaction:
  `front_pages` counts from the START OF THE SLICE, not the document. Say so in the docstring —
  for a bounded call the "front matter" of a chapter is not the book's front matter.

### Existing primitives — reuse, do not rebuild

- `_build_sub_pdf(pdf_doc, start, end, sub_path)` (`:144-153`) already writes a page range to a new
  PDF via `import_pages`. It is what AC8 needs and what `_convert_table_runs` already uses.
- `_release_page` (`:80-93`) is the per-page cache discipline that keeps RSS O(1 page). Bounded
  loops must keep calling it.
- `_page_table_count` (`:63-77`) is the 579 ms/page cost. It stays in `extract_pdf` — that path
  genuinely needs tables. `--text-only` already skips it.

### Testing standards

- Markers `unit`, `integration`, `slow`, `live_eval`, `postgres`; `--strict-markers`;
  `filterwarnings = ["error"]`.
- Repo PDF fixtures: `tests/fixtures/eval_pdfs/{short,long,dense_text,table_heavy,image_heavy}.pdf`
  and `demo-assets/sample-chapter.pdf` (41 pages). The 1,151-page book is **not** in the repo —
  real-book verification is a recorded manual run (T5), not a committed test.
- Running locally: Postgres `55432`, PostgREST `53000`, API `8077`.

### References

- [Source: docs/book-scale-phase-tracker.md#Phase-4] — exit criterion and the 5-step e2e test
- [Source: docs/reports/PHASE-1-TOC-SPIKE.md] — 579 ms/page table scan; 11.1 min whole-book
- [Source: docs/stories/1-11-book-chapter-read-endpoints.md] — Phase 3.5, and the chapter ranges
- [Source: CLAUDE.md] — §18 subprocess isolation; 300 DPI render floor; binding rules 1, 2, 7

---

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] — 2026-08-04. Contract-first: one agent implemented, one wrote tests to the
same spec in a different file, in parallel.

### Debug Log References

**Real-book verification — chapter 9 of the 1,151-page book, pages 272-306:**

| | |
|---|---|
| `page_texts[0]` first line | `'7 Convolutional Neural Networks'` — the right chapter |
| `extracted_page_count` / `page_offset` / `page_count` | **35 / 272 / 1151** |
| Slice equals `whole[272:307]` byte for byte | **True** |
| Page 0 present in the slice | **False** |
| Off-by-one guards (`first != whole[271]`, `last != whole[307]`) | both **True** |
| Wall-clock | **2.75 s** vs 10.02 s whole-document — **3.6x faster** |
| AC3 unbounded == explicit full bounds | **True** |
| AC4 out-of-range | exit 1, message names the bad value and the page count — **never clamped** |

A naive first leak check flagged the token `'Learning'` as escaping from page 0. It is a generic
word in a deep-learning textbook; the distinctive tokens (`ZACHARY`, `LIPTON`, `ALEXANDER`) did
not appear. Replaced with slice equality against the whole-document extraction, which is
decisive rather than heuristic.

**Two problems found that neither agent introduced:**

1. **A pre-existing test forbade the very thing its name promised.**
   `test_output_contract_preserved_with_additive_keys` asserted `set(result) == {...}` — exact
   equality — so `extracted_page_count` and `page_offset` failed a test written to permit
   additive keys. Relaxed to a superset check. A consumer breaks when a key disappears or changes
   meaning, never when one is added.
2. **24 of these 28 tests would have skipped in CI.** `apps/api/.gitignore:40` ignores
   `tests/fixtures/eval_pdfs/*.pdf`, so on a fresh clone the fixtures do not exist. A guard that
   skips in CI is not a guard (binding rule 7). They now generate on demand — the generator is
   deterministic and re-runnable by design (Story 2-14 AC-2).

   **My first attempt at that was wrong and I caught it by testing it.** I used a session-scoped
   autouse fixture; `skipif` is evaluated at COLLECTION time, so the PDFs regenerated but the
   tests had already been marked skipped — `4 passed, 24 skipped` with 5 files on disk afterwards.
   Moved to import time. Verified by deleting every PDF and re-running: **28 passed from clean.**

**Deliberate scope holds:** `graph.py:280-290` still calls the 3-argument form (Phase 5 passes
bounds), and `graph.py:609-651` is untouched (Phase 5 deletes it, when a real `chapter_id` exists).

**Interface decision the contract did not specify:** in bounded `--text-only`, the `toc` stays
whole-document with absolute `page_index`. An outline is a document-level object the caller uses
to *find* chapters, so filtering it to the slice would be lossy.

### Completion Notes List

- T1-T6 complete. 28 new tests; gating scope **898 passed, 1 skipped** (was 870).
- `ruff check .` clean; `mypy app` 24 errors / 3 files, unchanged from `main`.
  `ruff format --check` flags only the pre-existing `tests/test_tutor_service.py`.
- `_extract_font_blocks` is now bounded via `_build_sub_pdf` with a `+page_start` remap — measured
  2,830 blocks in 0.5 s for pages 5-9 against 31,726 in 7.3 s whole-document, with identical page
  numbers and span text for the overlapping range. Left unbounded it would have parsed all 1,151
  pages and defeated the phase.
- `_convert_table_runs` / `_group_table_runs` / `_append_fallback_tables` now carry an explicit
  index base: everything absolute, one documented conversion at the splice
  (`rel = abs - page_start`).

### File List

- `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py` (modified)
- `apps/api/tests/unit/test_extract_page_bounds.py` (new — 28 tests)
- `apps/api/tests/unit/test_extract_subprocess.py` (modified — superset assertion)
