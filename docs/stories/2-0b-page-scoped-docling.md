# Story 2-0b — Page-Scoped Docling + Extraction Performance (Tier 2)

**Status:** in-progress
**Sprint:** 2 (pre-work — unblocks realistic PDF ingestion for all Sprint 2 stories)
**Owner:** Dev 1
**Branch:** `sprint2/s2-0b-page-scoped-docling`
**Source:** Deep analysis Tier-2 plan (`learning-docs/PIPELINE-DEEP-ANALYSIS.md` §4, items 9–15). All three
independent redesign strategies converged on page-scoped docling as the core fix.

## Context

Extraction currently runs whole-document docling ML conversion whenever ANY page contains a table
(`extract_subprocess.py:229`), making table-bearing PDFs of any real size unextractable: measured 2.3 s/page
without docling vs DNF at the timeout with it (41-page excerpt of a real textbook never finished; 1120-page
book hopeless). Tier 1 (Story 2-0) made these failures clean; this story makes them not happen.
Baseline measurements to beat, on this dev machine with the same PDFs:
- `/tmp/mini.pdf` (3 pages, no tables): extract ≈ 7 s
- 41-page excerpt (`/tmp/excerpt.pdf`, contains ≥1 table): extract DNF ≥ 600 s
- full book (1120 pages): DNF (measured 22 min still running before kill)

## Acceptance Criteria

### AC-1 Table-page detection (cheap trigger)
- The per-page pdfplumber pass records `table_page_idxs: list[int]` (0-indexed) using `page.find_tables()`
  (detection only), replacing the current `extract_tables()` boolean trigger.
- The single document-wide `has_tables` flag is removed.
- **Test:** synthetic 3-page PDF with a table on page 1 only → `table_page_idxs == [1]`; table-free PDF → `[]`.

### AC-2 Page-scoped docling conversion
- Table pages are grouped into contiguous runs, each run expanded by ±1 page (multi-page-table guard),
  clamped to document bounds, and overlapping runs merged.
- For each run, a temporary sub-PDF is built via `pypdfium2 PdfDocument.new().import_pages(...)` and converted
  by docling; ONE `DocumentConverter` instance is created lazily per subprocess invocation and reused across runs.
- Docling markdown REPLACES only the corresponding pages' text in `page_texts` (per-page splice using docling's
  page provenance); all non-run pages keep their pypdfium2 text verbatim. The whole-document replacement
  (`raw_text = md_text`) is removed — `page_texts` stays the canonical source joined at the end.
- Docling failure for a run: log warning, fall back to serializing that run's `pdfplumber` table rows as GitHub
  markdown tables appended to the affected pages' text; NEVER crash extraction, NEVER silently drop tables.
- Output JSON gains `"tables_detected": int` and `"docling_pages": list[int]` for observability.
- **Tests:** grouping/expansion/merge pure-function tests (single page → 3-page run; adjacent runs merge;
  bounds clamped); splice test (docling output lands only on run pages; other pages byte-identical);
  docling-failure fallback test (table rows appear as markdown, extraction succeeds).

### AC-3 Per-page memory release
- Inside the main page loop: `plumb_page.flush_cache()` (and `close()` where the pdfplumber version exposes it)
  and `pdfium_page.close()` every iteration, so RSS stays O(1 page) instead of growing to ~4 GB.
- **Test:** loop-body test asserting the release calls happen per page (mock-based; RSS assertion is E2E scope).

### AC-4 Image pre-filter before rendering
- Skip images whose bbox area < 5% of page area OR whose rendered size would be < 10,000 px² at 300 DPI,
  BEFORE any page render; skip the full-page 300 DPI render entirely when no image on the page survives the
  filter. Thresholds module-level constants; skipped counts logged. The 300 DPI floor for KEPT images is untouched.
- **Test:** page with only a tiny logo → no render call; page with a half-page figure → rendered at 300 DPI.

### AC-5 Parallel image uploads (worker side)
- In `extract_node` (graph.py), the per-image Supabase uploads run concurrently via `asyncio.gather` with
  `asyncio.to_thread` under a `Semaphore(8)`; a single failed upload fails the node as before (no silent loss).
- **Test:** N images → uploads overlap (call ordering not serial), semaphore bound respected, one failure raises.

### AC-6 Per-page OCR decision
- Replace the whole-document average-chars trigger: OCR runs ONLY for pages where `len(page_text.strip()) <
  ocr_text_yield_threshold`; OCR output replaces only that page's text and only when non-empty. The second full
  `PdfDocument` reopen for OCR is removed (reuse the open document).
- Mixed books (text + scanned pages) OCR exactly their scanned pages; fully-digital books trigger zero OCR.
- **Test:** 3-page doc with one empty-text page → OCR called once, that page only; good pages byte-identical.

### AC-7 Performance acceptance (measured, not estimated)
- Direct `extract_pdf()` timing on this dev machine (WSL venv, uncontended):
  - `/tmp/mini.pdf` (3p): ≤ 15 s (no regression)
  - `/tmp/excerpt.pdf` (41p, tables): **≤ 240 s** (was DNF ≥ 600 s)
- Live E2E: the 41-page excerpt uploaded through the full stack (FastAPI + ARQ + Supabase + OpenAI) reaches
  `lesson_jobs.status='completed'` with all non-empty chunks embedded.
- **Test:** timing harness script recorded in the story's Dev Notes with actual numbers (not CI-enforced).

## Constraints (unchanged, non-negotiable)
No fitz/PyMuPDF. Parsing stays in the isolated subprocess. 300 DPI floor for kept images. ARQ only.
No hardcoded model strings. Existing extract output contract (`raw_text`, `page_count`, `image_files`,
`font_blocks`) preserved — new keys are additive.

## Out of scope (Tier 3)
Checkpoint offload to Storage, page-ledger provenance contract, structure-LLM boundary-only rework,
multiprocessing page shards, region renders via pdfium crop, extraction concurrency gate.

## Definition of Done
- All ACs tested; full unit suite green.
- AC-7 timings recorded with real numbers in Dev Notes.
- 5-agent code review before merge.
