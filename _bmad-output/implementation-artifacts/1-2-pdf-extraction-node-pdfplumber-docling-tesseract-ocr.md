---
baseline_commit: d12638d96ea3f9e9e2a6efda5b46af9f17f6de7a
---

# Story 1.2: PDF Extraction Node — pypdfium2 + pdftext + Docling + Tesseract OCR

Status: done

## Story

As a content pipeline,
I want to extract all text, tables, and images from a PDF in an isolated subprocess,
so that malicious PDFs cannot exploit the main ARQ worker process.

## Acceptance Criteria

### Original ACs (Tasks 1–5, completed)
1. ~~Uses pdfplumber (MIT) for text extraction~~ → **Revised in stack upgrade (AC1-R):** pdfplumber retained only for table detection; pypdfium2 handles all text extraction
2. Docling (Apache 2.0) for table extraction: when `pdfplumber` detects `>= 1` table structure on any page, docling converts the **whole document** to structured markdown — **unchanged**
3. Tesseract OCR fallback triggered when text yield < `settings.ocr_text_yield_threshold` chars/page (env var `OCR_TEXT_YIELD_THRESHOLD`, default 50) — **unchanged**
4. PDF parsed in an **isolated subprocess** — never call any PDF parser directly in the ARQ worker process — **unchanged**
5. Embedded images extracted and stored to Supabase Storage bucket `lesson-images`; storage paths returned in `extracted_images` list on `PipelineState` — **updated: 300 DPI (see AC5-R)**
6. `books.page_count` written to DB after extraction — **unchanged**
7. Node is idempotent — if `lesson_jobs.node_outputs["extract"]` already exists, restore cached output and return immediately without re-extracting — **unchanged**
8. Checkpoint written on success: `lesson_jobs.last_node = 'extract'` and `lesson_jobs.node_outputs = {extract: {...}}` — **unchanged**
9. `pymupdf` removed from `pyproject.toml` (AGPL-3.0 licence violates closed-source SaaS) — **completed**

### Stack Upgrade ACs (Tasks 6–10, new)
1-R. **pypdfium2** (Apache 2.0, `>=5.11.0,<6.0.0`) replaces pdfplumber for ALL text extraction — 97% accuracy vs 75%, 100× faster. `pdfplumber` retained only for `page.extract_tables()` table detection trigger.
5-R. Embedded images extracted at **300 DPI** (not 150 DPI) using `pypdfium2` page rendering — `page.render(scale=300/72).to_pil()` then crop image bounding boxes.
10. **pdftext** (Apache 2.0, `>=0.6.0,<1.0.0`) extracts structured font/layout metadata; subprocess JSON gains `font_blocks` field: `[{"text": str, "bbox": [x0,y0,x1,y1], "font": {"name": str, "size": float, "bold": bool}}]`. This field is consumed by Story 1.3 structure detection — do not omit.
11. `pypdfium2.*` and `pdftext.*` added to `[[tool.mypy.overrides]]` `ignore_missing_imports` in `pyproject.toml`.

## Tasks / Subtasks

- [x] **Task 1: Config + dependencies** (AC: 1, 3, 9)
  - [x] Add `ocr_text_yield_threshold: int = Field(default=50, ...)` to `Settings` in `apps/api/app/config.py`
  - [x] Add `"docling>=2.0.0"` to `pyproject.toml` `[project.dependencies]`; run `pip install docling` in venv
  - [x] Remove `"pymupdf>=1.24.0"` from `pyproject.toml` (AGPL-3.0 banned); add `fitz.*` to `mypy` ignore override if not already there
  - [x] Add `"docling.*"` to `[[tool.mypy.overrides]]` `ignore_missing_imports` list in `pyproject.toml`

- [x] **Task 2: Fix `content_pipeline_job` to pass PDF path + book_id** (AC: 4)
  - [x] In `apps/api/app/workers/jobs/content_pipeline.py`: change DB query from `lesson_jobs` to `lessons` to fetch `user_id`, `source_file_path`, `book_id`
  - [x] Pass `source_pdf_path=source_file_path, book_id=book_id` to `run_pipeline()`
  - [x] Update `run_pipeline()` signature in `graph.py` to accept `source_pdf_path: str = ""` and `book_id: str = ""`
  - [x] Add `book_id: str` and `source_pdf_path: str` to `PipelineState` TypedDict in `graph.py` (they already exist in the TypedDict but `book_id` is missing)

- [x] **Task 3: Create isolated extraction subprocess** (AC: 1, 2, 3, 4, 5)
  - [x] Create `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`
  - [x] Entry point: reads PDF file path + image output dir + OCR threshold from `sys.argv`; writes JSON to stdout
  - [x] pdfplumber pass: extract text per page; compute per-page char count; detect tables via `page.extract_tables()`
  - [x] Docling pass: for pages with tables detected by pdfplumber, run `docling.document_converter.DocumentConverter` on those pages; merge table markdown into extracted text
  - [x] OCR pass: for each page where `len(page_text) / max(1, page_char_count) < ocr_threshold`, run `pytesseract.image_to_string(pil_image)` on the rendered page image
  - [x] Image extraction: for each embedded image object from pdfplumber (`page.images`), save to `{image_output_dir}/p{page}_{idx}.png`; collect paths
  - [x] Stdout JSON schema: `{"raw_text": str, "page_count": int, "image_files": [{"page": int, "local_path": str}]}`
  - [x] Stderr: any exception message; non-zero exit code on failure

- [x] **Task 4: Implement `extract_node` in `graph.py`** (AC: 4, 5, 6, 7, 8)
  - [x] Replace the `TODO` body in `extract_node` with the full implementation
  - [x] **Idempotency check** first: query `lesson_jobs.node_outputs` for `lesson_id`; if `"extract"` key exists, return cached state immediately
  - [x] Download PDF bytes: `supabase.storage.from_("source-pdfs").download(state["source_pdf_path"])` → `bytes`
  - [x] Create `tempfile.TemporaryDirectory(prefix=f"hie_{lesson_id}_")` as context manager
  - [x] Write PDF bytes to `{tmpdir}/input.pdf`; create `{tmpdir}/images/` dir
  - [x] Invoke subprocess via `asyncio.create_subprocess_exec(sys.executable, "-m", "app.modules.content.pipeline.nodes.extract_subprocess", pdf_path, img_dir, str(settings.ocr_text_yield_threshold))`
  - [x] `await proc.communicate()`; raise `RuntimeError` on non-zero exit
  - [x] Parse stdout JSON → `raw_text`, `page_count`, `image_files`
  - [x] Upload each image to Supabase Storage `lesson-images` bucket at path `{lesson_id}/p{page}_{idx}.png`; collect storage paths
  - [x] Update `books.page_count` in DB: `supabase.table("books").update({"page_count": page_count}).eq("book_id", state["book_id"]).execute()`
  - [x] Write checkpoint: `supabase.table("lesson_jobs").update({"last_node": "extract", "node_outputs": {**existing_outputs, "extract": extract_cache}}).eq("lesson_id", lesson_id).execute()`
  - [x] `_update_job_progress(lesson_id, 7.0, "extract")` — call this AFTER checkpoint write (existing helper, fails silently)
  - [x] Return `{**state, "raw_text": raw_text, "extracted_images": storage_images, "progress_pct": 7.0}`

- [x] **Task 5: Tests** (all ACs)
  - [x] Create `apps/api/tests/unit/test_extract_node.py`
  - [x] `test_extract_node_happy_path`: mock subprocess returns valid JSON, mock storage download/upload, mock DB — verify `raw_text` and `extracted_images` in returned state
  - [x] `test_extract_node_idempotent`: pre-populate `node_outputs = {"extract": {...}}` in DB mock — assert subprocess NOT called, cached values returned
  - [x] `test_extract_node_writes_page_count`: verify `books.update({"page_count": N})` called with correct value
  - [x] `test_extract_node_writes_checkpoint`: verify `lesson_jobs.update({"last_node": "extract", ...})` called
  - [x] `test_extract_node_subprocess_failure`: subprocess returns exit code 1 — assert `RuntimeError` raised, error propagated
  - [x] `test_content_pipeline_job_queries_lessons`: verify `content_pipeline_job` queries `lessons` (not `lesson_jobs`) for `source_file_path` and `user_id`

---

### Stack Upgrade — Tasks 6–10 (pypdfium2 + pdftext replacement)

> **Context:** pdfplumber was used for text extraction in Tasks 1–5. Decision made 2026-07-01 to replace with pypdfium2 (100× faster, 97% vs 75% accuracy) and add pdftext for font/layout metadata needed by Story 1.3. pdfplumber stays for table detection only. All changes are confined to `extract_subprocess.py` and `pyproject.toml`.

- [x] **Task 6: Update dependencies** (AC: 1-R, 10, 11)
  - [x] Add `"pypdfium2>=5.11.0,<6.0.0"` to `[project.dependencies]` in `apps/api/pyproject.toml`
  - [x] Add `"pdftext>=0.6.0,<1.0.0"` to `[project.dependencies]` in `apps/api/pyproject.toml`
  - [x] Add `"pypdfium2.*"` and `"pdftext.*"` to `[[tool.mypy.overrides]]` `ignore_missing_imports` list
  - [x] Run `uv pip install pypdfium2 pdftext` in venv to verify installation succeeds

- [x] **Task 7: Replace text extraction with pypdfium2** (AC: 1-R)
  - [x] In `extract_subprocess.py`, replace `_page_text(page)` pdfplumber call with `pypdfium2.PdfDocument` text extraction
  - [x] Use `doc = pypdfium2.PdfDocument(pdf_path)` → iterate pages → `page.get_textpage().get_text_range()`
  - [x] Keep `pdfplumber.open(pdf_path)` ONLY for `_page_has_tables()` table detection — no other pdfplumber usage
  - [x] Verify: `_ocr_page_text()` now uses pypdfium2 rendering (not pdfplumber `page.to_image()`)

- [x] **Task 8: Upgrade image extraction to 300 DPI** (AC: 5-R)
  - [x] In `_extract_page_images()`, replace `page.to_image(resolution=150)` pdfplumber render with pypdfium2 render
  - [x] Use `pypdfium2` page: `bitmap = page.render(scale=300/72)` → `pil_img = bitmap.to_pil()`
  - [x] Keep the bbox crop logic the same; adjust scale factor: `scale = 300 / 72` (was `150 / 72`)
  - [x] Verify images are saved as PNG at ~2× the previous resolution

- [x] **Task 9: Add pdftext font block extraction** (AC: 10)
  - [x] Add `_extract_font_blocks(pdf_path: str) -> list[dict]` function to `extract_subprocess.py`
  - [x] Use `from pdftext.extraction import dictionary_output` → `pages = dictionary_output(pdf_path)`
  - [x] For each page → block → line → span, extract: `{"text": str, "bbox": [x0,y0,x1,y1], "font": {"name": str, "size": float, "bold": bool}}`
  - [x] Add `font_blocks` field to the subprocess stdout JSON: `{"raw_text": ..., "page_count": ..., "image_files": ..., "font_blocks": [...]}`
  - [x] Update `SUBPROCESS_STDOUT` constant in `test_extract_node.py` to include `"font_blocks": []`
  - [x] Update `PipelineState` in `graph.py` to include `font_blocks: list` field
  - [x] Update `extract_node` in `graph.py` to pass `font_blocks` through in returned state and checkpoint cache

- [x] **Task 10: Update unit tests** (all upgrade ACs)
  - [x] Update `SUBPROCESS_STDOUT` in `test_extract_node.py` to include `"font_blocks": []`
  - [x] Update `test_extract_node_happy_path` to assert `font_blocks` is a list in returned state
  - [x] Update `test_extract_node_idempotent` to include `font_blocks` in cached dict and assert it's restored
  - [x] Update `test_extract_node_writes_checkpoint` to assert `font_blocks` in checkpoint cache
  - [x] Run `uv run pytest tests/unit/ -m unit` — all 22 tests pass

## Dev Notes — Stack Upgrade (Tasks 6–10)

### pypdfium2 Text Extraction Pattern

```python
import pypdfium2  # type: ignore[import-not-found]

def _extract_text_pypdfium2(pdf_path: str) -> tuple[list[str], int]:
    """Extract raw text per page using pypdfium2 (Apache 2.0, 97% accuracy)."""
    doc = pypdfium2.PdfDocument(pdf_path)
    page_texts: list[str] = []
    for page in doc:
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        page_texts.append(text or "")
    return page_texts, len(doc)
```

**IMPORTANT:** Do NOT use `get_charbox(loose=True)` — broken in pypdfium2 v5.7+ (Issue #421 on GitHub). Use `loose=False` if charbox is needed.

### pypdfium2 Page Rendering at 300 DPI

```python
def _render_page_pil(page: Any, dpi: int = 300) -> Any:
    """Render a pypdfium2 page to PIL Image at specified DPI."""
    from PIL import Image  # type: ignore[import-not-found]
    bitmap = page.render(scale=dpi / 72)
    return bitmap.to_pil()
```

Use this for BOTH image extraction crops AND OCR preprocessing (replaces `pdfplumber.page.to_image(resolution=150)`).

### pdftext Font Block Extraction Pattern

```python
def _extract_font_blocks(pdf_path: str) -> list[dict]:
    """Extract structured font/layout metadata using pdftext (Apache 2.0).

    Returns blocks consumed by Story 1.3 structure detection node.
    Each span: {"text": str, "bbox": [x0,y0,x1,y1], "font": {"name": str, "size": float, "bold": bool}}
    """
    from pdftext.extraction import dictionary_output  # type: ignore[import-not-found]

    font_blocks: list[dict] = []
    try:
        pages = dictionary_output(pdf_path)
        for page_data in pages:
            for block in page_data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font_info = span.get("font", {})
                        font_blocks.append({
                            "text": span.get("text", ""),
                            "bbox": span.get("bbox", [0, 0, 0, 0]),
                            "font": {
                                "name": font_info.get("name", ""),
                                "size": float(font_info.get("size", 12.0)),
                                "bold": bool(font_info.get("bold", False)),
                            },
                        })
    except Exception:  # noqa: BLE001
        logger.warning("pdftext font extraction failed for %s — font_blocks will be empty", pdf_path)
    return font_blocks
```

### Updated Subprocess JSON Schema

```json
{
  "raw_text": "string",
  "page_count": 3,
  "image_files": [{"page": 1, "local_path": "/tmp/img/p1_0.png"}],
  "font_blocks": [
    {
      "text": "Chapter 3: The Cell",
      "bbox": [72.0, 680.0, 400.0, 700.0],
      "font": {"name": "TimesNewRoman-Bold", "size": 18.0, "bold": true}
    }
  ]
}
```

Story 1.3 structure detection reads `font_blocks` from `node_outputs["extract"]["font_blocks"]` — the font size + bold flag determine heading level without needing to re-open the PDF.

### Updated `extract_subprocess.py` call order (Tasks 6–9)

```
1. pypdfium2 → text extraction (replaces pdfplumber text)
2. pdfplumber → table detection only (has_tables flag)
3. docling → markdown conversion if has_tables (unchanged)
4. pypdfium2 → OCR page rendering at 300 DPI if avg_chars < threshold (replaces pdfplumber render)
5. pytesseract → OCR engine (unchanged)
6. pypdfium2 → image extraction at 300 DPI (replaces 150 DPI pdfplumber crop)
7. pdftext → font block extraction (new)
```

### PipelineState Update Required

Add `font_blocks` to `PipelineState` TypedDict in `graph.py`:

```python
class PipelineState(TypedDict):
    ...
    font_blocks: list  # populated by extract_node; consumed by structure_detect_node (Story 1.3)
```

Update `extract_node` to return `font_blocks` in state and include in checkpoint cache:
```python
extract_cache = {
    "raw_text": raw_text,
    "extracted_images": storage_images,
    "page_count": page_count,
    "font_blocks": font_blocks,  # NEW — for Story 1.3
}
```

### Testing the Subprocess Directly

After Tasks 6–9, test without any external services:
```bash
cd apps/api
uv run python -m app.modules.content.pipeline.nodes.extract_subprocess \
    /path/to/any_textbook.pdf /tmp/img_output 50
# Stdout: JSON with raw_text, page_count, image_files, font_blocks
```

---

## Dev Notes

### Files to UPDATE (read each before touching)

| File | Current State | This Story Changes |
|------|---------------|--------------------|
| `apps/api/app/config.py` | Has `Settings` with redis_url, LLM aliases, CES weights | Add `ocr_text_yield_threshold: int` |
| `apps/api/app/modules/content/pipeline/graph.py` | `extract_node` body is all `TODO`; `PipelineState` has `source_pdf_path` but no `book_id` | Implement node body; add `book_id` to state; update `run_pipeline` signature |
| `apps/api/app/workers/jobs/content_pipeline.py` | Queries `lesson_jobs` for `user_id`/`source_pdf_path` — both columns don't exist there | Fix to query `lessons`; pass `source_pdf_path` and `book_id` to `run_pipeline` |
| `apps/api/pyproject.toml` | Has `pymupdf>=1.24.0` (BANNED) and `pdfplumber>=0.11.0` | Remove pymupdf; add docling |

### File to CREATE (NEW)

| File | Purpose |
|------|---------|
| `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py` | Subprocess entry point — all PDF parsing happens here in isolation |
| `apps/api/tests/unit/test_extract_node.py` | Unit tests for `extract_node` and the `content_pipeline_job` fix |

### Critical: PyMuPDF is BANNED — NEVER use `import fitz`

**`pymupdf` (a.k.a. `fitz`) is AGPL-3.0.** Using it in a closed-source SaaS product requires either a commercial licence (not purchased) or open-sourcing the product. Either outcome is unacceptable.

- `pyproject.toml` currently lists `pymupdf>=1.24.0` — **this must be removed**
- `graph.py:112` comment says "Uses PyMuPDF (fitz)" — **update this comment**
- `[[tool.mypy.overrides]]` already ignores `fitz.*` — leave it (keeps mypy happy if any stale import exists during transition)
- Use **pdfplumber** (MIT) for all text/table extraction
- Use **docling** (Apache 2.0) for hierarchical table structure extraction on table-heavy pages

### Critical: Subprocess Isolation is Non-Negotiable

CLAUDE.md §18: "parse user-uploaded PDFs in an isolated subprocess — calling `fitz.open()` directly in the main FastAPI process is a security risk with untrusted files."

The same rule applies to the ARQ worker process. A malicious PDF could exploit memory bugs in PDF parsers (pdfplumber uses pdfminer.six which is pure Python and safer, but Tesseract and Pillow interact with binary image data — subprocess isolation is still required by policy).

Subprocess invocation pattern:
```python
import asyncio
import sys

proc = await asyncio.create_subprocess_exec(
    sys.executable,
    "-m", "app.modules.content.pipeline.nodes.extract_subprocess",
    pdf_path,           # sys.argv[1]
    img_output_dir,     # sys.argv[2]
    str(ocr_threshold), # sys.argv[3]
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
if proc.returncode != 0:
    raise RuntimeError(f"PDF extraction subprocess failed (exit={proc.returncode}): {stderr.decode()[:1000]}")
result = json.loads(stdout.decode())
```

Why `-m app.modules.content.pipeline.nodes.extract_subprocess` (not a path)? The worker runs with the app package on `sys.path` via the virtualenv, so module invocation is the cleanest approach. The subprocess inherits the same Python env.

### Critical: DB Column Bug in `content_pipeline_job` — Must Fix

The existing code in `content_pipeline.py` queries `lesson_jobs` for `user_id` and `source_pdf_path`, but these columns **do not exist** in `lesson_jobs`. They are on `lessons`.

**Current (wrong):**
```python
result = supabase.table("lesson_jobs").select("*").eq("lesson_id", lesson_id).single().execute()
user_id = lesson_row.get("user_id", "")          # always ""
chapter_content = lesson_row.get("extracted_text", "")  # always ""
# ...
if not chapter_content and lesson_row.get("source_pdf_path"):  # source_pdf_path also always ""
```

**Fixed:**
```python
# Fetch lesson metadata from lessons table (NOT lesson_jobs — wrong table)
lesson_resp = (
    supabase.table("lessons")
    .select("user_id, source_file_path, book_id")
    .eq("lesson_id", lesson_id)
    .single()
    .execute()
)
lesson_row: dict[str, Any] = lesson_resp.data or {}
user_id: str = lesson_row.get("user_id", "")
source_file_path: str = lesson_row.get("source_file_path", "")
book_id: str = lesson_row.get("book_id", "") or ""
```

Then pass these to `run_pipeline`:
```python
lesson_package = await run_pipeline(
    lesson_id=lesson_id,
    user_id=user_id,
    source_pdf_path=source_file_path,
    book_id=book_id,
)
```

### Critical: `_update_job_progress` writes non-existent columns

The helper `_update_job_progress()` in `graph.py` writes `progress_pct` and `current_node` to `lesson_jobs` — neither column exists in the schema. These writes silently fail (wrapped in `try/except`).

**Do NOT fix `_update_job_progress` in this story** — it's used by all 14 nodes and is a cross-cutting concern. Write the checkpoint for `extract_node` **directly** (bypassing `_update_job_progress`), using the actual DB columns: `last_node` and `node_outputs`.

Correct checkpoint write:
```python
# Load existing node_outputs first to avoid overwriting other nodes' data
jobs_resp = supabase.table("lesson_jobs").select("node_outputs").eq("lesson_id", lesson_id).single().execute()
existing_outputs: dict = (jobs_resp.data or {}).get("node_outputs") or {}

extract_cache = {
    "raw_text": raw_text,
    "extracted_images": storage_images,
    "page_count": page_count,
}
supabase.table("lesson_jobs").update({
    "last_node": "extract",
    "node_outputs": {**existing_outputs, "extract": extract_cache},
}).eq("lesson_id", lesson_id).execute()
```

### Critical: `PipelineState` changes

Add `book_id: str` to `PipelineState` TypedDict in `graph.py`. This is needed by `extract_node` to write `books.page_count`.

Update `run_pipeline()` to accept `source_pdf_path` and `book_id`, then include them in `initial_state`:

```python
async def run_pipeline(
    lesson_id: str,
    chapter_content: str = "",
    user_id: str = "",
    source_pdf_path: str = "",
    book_id: str = "",
) -> dict[str, Any]:
    ...
    initial_state: PipelineState = {
        "lesson_id": lesson_id,
        "user_id": user_id,
        "chapter_content": chapter_content,
        "source_pdf_path": source_pdf_path,
        "book_id": book_id,
        "progress_pct": 0.0,
        "error": None,
    }
```

### Idempotency Pattern (AC: 7, 8)

The `lesson_jobs.node_outputs` JSONB column caches node outputs. The idempotency check is keyed on whether `"extract"` is present in the outputs dict:

```python
async def extract_node(state: PipelineState) -> PipelineState:
    lesson_id = state["lesson_id"]

    # ── Idempotency check ─────────────────────────────────────────────────────
    from app.core.db import get_supabase
    supabase = get_supabase()
    jobs_resp = (
        supabase.table("lesson_jobs")
        .select("node_outputs")
        .eq("lesson_id", lesson_id)
        .single()
        .execute()
    )
    node_outputs: dict = (jobs_resp.data or {}).get("node_outputs") or {}
    if "extract" in node_outputs:
        cached = node_outputs["extract"]
        logger.info("[%s] extract_node: cache hit — skipping re-extraction", lesson_id)
        return {
            **state,
            "raw_text": cached["raw_text"],
            "extracted_images": cached["extracted_images"],
            "progress_pct": 7.0,
        }
    
    # ... proceed with extraction
```

### OCR Threshold Logic

The `OCR_TEXT_YIELD_THRESHOLD` controls when Tesseract kicks in. Logic per page in the subprocess:

```python
chars_per_page = len(page_text.strip())
if chars_per_page < ocr_threshold:
    # Render page as image and run OCR
    pil_image = page.to_image(resolution=200).original
    ocr_text = pytesseract.image_to_string(pil_image, lang="eng")
    page_text = ocr_text if len(ocr_text.strip()) > len(page_text.strip()) else page_text
```

The OCR result replaces the pdfplumber text only if it yields more characters.

### Docling Integration (Table-Heavy Pages)

Docling is for complex hierarchical table extraction. Use it selectively on pages where pdfplumber detects tables:

```python
import pdfplumber

pages_with_tables: list[int] = []
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        if tables:
            pages_with_tables.append(i)

if pages_with_tables:
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    # result.document.export_to_markdown() gives structured table output
    # Merge table markdown into raw_text for table-heavy pages
    docling_md = result.document.export_to_markdown()
    # Append docling-extracted tables after pdfplumber text
    raw_text += "\n\n--- TABLES ---\n" + docling_md
```

Note: Docling processes the whole PDF but is only invoked when `len(pages_with_tables) > 0`. The cost of running Docling on a PDF with no tables is avoided.

### DB Schema — Relevant Tables

**`books`** (from migration `20260625000000_chunks_inline_embedding.sql`):
```sql
book_id    uuid  PRIMARY KEY
user_id    uuid  NOT NULL
filename   text  NOT NULL
page_count integer          -- NULL until extraction writes it
status     text  CHECK ('processing', 'ready', 'failed')
```

**`lesson_jobs`** (from migration `20260611000000_initial_schema.sql`):
```sql
lesson_id   uuid
status      text  CHECK ('pending', 'running', 'completed', 'failed')
last_node   text                    -- checkpoint: name of last completed node
node_outputs jsonb                  -- cached outputs per node: {"extract": {...}}
error       text
```

**`lessons`** (from migration `20260611000000_initial_schema.sql` + `20260625000000_chunks_inline_embedding.sql`):
```sql
lesson_id        uuid
user_id          uuid
source_file_path text    -- Supabase Storage path, e.g. "{user_id}/{book_id}/{filename}"
book_id          uuid    -- nullable FK to books
```

### Supabase Storage: Download + Upload Pattern

Download PDF (in `extract_node` before subprocess):
```python
pdf_bytes: bytes = supabase.storage.from_("source-pdfs").download(state["source_pdf_path"])
```

Upload extracted image (after subprocess returns image paths):
```python
with open(local_img_path, "rb") as f:
    img_bytes = f.read()
storage_path = f"{lesson_id}/p{page}_{idx}.png"
supabase.storage.from_("lesson-images").upload(
    path=storage_path,
    file=img_bytes,
    file_options={"content-type": "image/png"},
)
storage_images.append({"page": page, "path": storage_path, "caption": ""})
```

The `lesson-images` bucket must exist in Supabase Storage (pre-created in the project alongside `source-pdfs`).

### extract_subprocess.py Structure

```
apps/api/app/modules/content/pipeline/nodes/
├── __init__.py              # empty (exists)
└── extract_subprocess.py    # NEW — isolated subprocess entry point
```

The module is invoked via `python -m app.modules.content.pipeline.nodes.extract_subprocess <pdf_path> <img_dir> <ocr_threshold>`. It must have a `if __name__ == "__main__":` guard.

```python
# extract_subprocess.py — skeleton
import json, sys, os
import pdfplumber
import pytesseract
from PIL import Image

def extract(pdf_path: str, img_dir: str, ocr_threshold: int) -> dict:
    raw_text_parts: list[str] = []
    image_files: list[dict] = []
    pages_with_tables: list[int] = []
    page_count = 0

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < ocr_threshold:
                pil_img = page.to_image(resolution=200).original
                ocr_text = pytesseract.image_to_string(pil_img, lang="eng")
                if len(ocr_text.strip()) > len(page_text.strip()):
                    page_text = ocr_text
            if page.extract_tables():
                pages_with_tables.append(i)
            raw_text_parts.append(page_text)
            for j, img in enumerate(page.images or []):
                # Extract raw image bytes from pdfplumber image dict
                # pdfplumber gives bbox; use page.to_image() to crop
                ...

    raw_text = "\n\n".join(raw_text_parts)

    if pages_with_tables:
        from docling.document_converter import DocumentConverter
        result = DocumentConverter().convert(pdf_path)
        raw_text += "\n\n--- TABLES ---\n" + result.document.export_to_markdown()

    return {"raw_text": raw_text, "page_count": page_count, "image_files": image_files}


if __name__ == "__main__":
    pdf_path, img_dir, ocr_threshold_str = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(img_dir, exist_ok=True)
    try:
        result = extract(pdf_path, img_dir, int(ocr_threshold_str))
        sys.stdout.write(json.dumps(result))
        sys.exit(0)
    except Exception as exc:
        sys.stderr.write(str(exc))
        sys.exit(1)
```

### `config.py` Addition

```python
# In Settings class, under "Cost limits" section:
ocr_text_yield_threshold: int = Field(
    default=50,
    description="Min chars/page from pdfplumber before OCR fallback (env: OCR_TEXT_YIELD_THRESHOLD)",
)
```

### Test Patterns from Story 1.1 to Reuse

- Test file location: `apps/api/tests/unit/test_extract_node.py` (follow same structure as `test_content_router.py`)
- conftest.py already has all env stubs including `REDIS_URL`
- Mock pattern for Supabase: `MagicMock()` with `.table().select().eq().single().execute().data = {...}`
- Mock async subprocess: `patch("asyncio.create_subprocess_exec")` → return mock proc with `.communicate()` returning `(json_bytes, b"")`
- Mark all tests with `@pytest.mark.unit`
- Use valid UUID strings for fake IDs (e.g., `"11111111-1111-1111-1111-111111111111"`)

### Known Issues NOT to Fix in This Story

1. **`_update_job_progress` writes to non-existent DB columns** (`progress_pct`, `current_node`) — out of scope; fails silently
2. **`lesson_jobs.status` CHECK constraint** only allows `('pending', 'running', 'completed', 'failed')` — `content_pipeline_job` uses `'ready'` on success (violates constraint). Out of scope for 1.2.
3. **`workers/main.py._build_redis_settings` missing TLS flag** — same bug fixed in app `main.py` in story 1.1 (`ssl=parsed.scheme == "rediss"`). Fix in a separate task or story 1.3.
4. **Docling version pinning** — add after first successful integration test; use `>=2.0.0` for now.

### References

- CLAUDE.md §18: PDF security subprocess isolation requirement
- CLAUDE.md technology table: pdfplumber (MIT), PyMuPDF BANNED (AGPL-3.0), Tesseract fallback chain
- `supabase/migrations/20260611000000_initial_schema.sql`: `lesson_jobs` schema (last_node, node_outputs)
- `supabase/migrations/20260625000000_chunks_inline_embedding.sql`: `books.page_count`, `lessons.book_id`
- `apps/api/app/modules/content/pipeline/graph.py:107-121`: current `extract_node` (all TODO)
- `apps/api/app/workers/jobs/content_pipeline.py:57-68`: bug in DB query to fix
- `apps/api/app/core/retry.py`: `with_retry` decorator — NOT needed for extract_node (it's a node, not a provider call; ARQ itself handles job-level retries)

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6 (create-story)

### Debug Log References

- Patching lazy imports: `from app.core.db import get_supabase` inside node functions must be patched at the ORIGINAL module (`"app.core.db.get_supabase"`), not at the consumer module. Same for `"app.config.get_settings"`.
- `asyncio.create_subprocess_exec` is async — mock must be `AsyncMock(return_value=proc)` where `proc` is the process object. A plain `MagicMock(return_value=proc)` fails because the `await` can't resolve.
- `sb.table(...)` returns the same mock regardless of args by default — must use `side_effect` to distinguish `lesson_jobs` vs `books` mocks in tests.

### Completion Notes List

- docling installed in venv (background task); mocked in unit tests so docling is not required at test time.
- image extraction from PDF pages intentionally returns empty `image_files: []` for MVP — pdfplumber's `page.images` gives metadata only; extracting raw bytes requires lower-level access deferred to a future story.
- `_update_job_progress` still writes non-existent DB columns (`progress_pct`, `current_node`) — tracked in `deferred-work.md` W1; silently swallowed by try/except, does not block pipeline.
- `lesson_jobs.status` CHECK constraint only allows `('pending', 'running', 'completed', 'failed')` but `content_pipeline_job` writes `'ready'` on success — constraint violation deferred to Story 2.7.

### File List

- `apps/api/app/config.py`
- `apps/api/app/modules/content/pipeline/graph.py`
- `apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py` (NEW)
- `apps/api/app/workers/jobs/content_pipeline.py`
- `apps/api/pyproject.toml`
- `apps/api/tests/unit/test_extract_node.py` (NEW)

### Review Findings

#### Decision Needed

- [x] [Review][Decision] D1 — AC5 image extraction not implemented → **resolved: implemented** — `_extract_page_images()` added to `extract_subprocess.py`; renders page at 150 DPI, crops each `page.images` bbox, saves PNG; `test_extract_node_uploads_images` verifies upload path
- [x] [Review][Decision] D2 — AC2 docling scope → **resolved: accepted** — whole-document replacement is correct behavior; AC2 wording updated to reflect intent

#### Patches

- [x] [Review][Patch] P1 — OCR inverts priority over docling → **fixed**: `docling_succeeded` flag added; OCR only runs when `not docling_succeeded` [`apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`]
- [x] [Review][Patch] P2 — `proc.communicate()` has no timeout → **fixed**: wrapped in `asyncio.wait_for(..., timeout=600.0)` with `proc.kill()` on `TimeoutError`; `test_extract_node_subprocess_timeout_raises` verifies [`apps/api/app/modules/content/pipeline/graph.py`]
- [x] [Review][Patch] P3 — `_ocr_page_text` silent exception → **fixed**: added `logger.warning("OCR failed for page %s", page_num, exc_info=True)` [`apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`]
- [x] [Review][Patch] P4 — `books` row orphaned in error handler → **fixed**: error handler now hard-deletes `lesson_jobs`, `lessons`, then `books` in FK order (clean slate for retry) [`apps/api/app/modules/content/router.py`]
- [x] [Review][Patch] P5 — ARQ dedup guard unreachable → **fixed**: `enqueue_job(..., _job_id=f"pipeline:{lesson_id}")` — deduplication is now real [`apps/api/app/modules/content/router.py`]
- [x] [Review][Patch] P6 — `page_count=0` falsy → **fixed**: `if book_id and page_count:` → `if book_id:` [`apps/api/app/modules/content/pipeline/graph.py`]
- [x] [Review][Patch] P7 — `page_count` unbound → **fixed**: initialized `page_count: int = 0` before `with pdfplumber.open()` [`apps/api/app/modules/content/pipeline/nodes/extract_subprocess.py`]
- [x] [Review][Patch] P8 — `docling>=2.0.0` no upper bound → **fixed**: pinned to `>=2.0.0,<3.0.0` per CLAUDE.md policy [`apps/api/pyproject.toml`]

#### Deferred (pre-existing)

- [x] [Review][Defer] W1 — `lesson_jobs.status="ready"` violates CHECK constraint — deferred to Story 2.7 in dev notes [`apps/api/app/workers/jobs/content_pipeline.py`] — deferred, pre-existing
- [x] [Review][Defer] W2 — `lessons.status` never updated on success — pre-existing `content_pipeline_job` gap (client sees "generating" forever) [`apps/api/app/workers/jobs/content_pipeline.py`] — deferred, pre-existing
- [x] [Review][Defer] W3 — `status="cost_limit_exceeded"` violates CHECK — pre-existing, silently swallowed [`apps/api/app/workers/jobs/content_pipeline.py`] — deferred, pre-existing
- [x] [Review][Defer] W4 — `_update_job_progress` writes `progress_pct`/`current_node` (non-existent columns) — explicitly tracked in deferred-work.md W1 [`apps/api/app/modules/content/pipeline/graph.py`] — deferred, pre-existing
- [x] [Review][Defer] W5 — `workers/main.py` missing `ssl=` flag for Railway Redis TLS — noted for Story 1.3 in dev notes [`apps/api/app/workers/main.py`] — deferred, pre-existing
- [x] [Review][Defer] W6 — Rate limiter `memory://` default bypassed across multiple Railway worker processes — deployment/config concern, not code bug [`apps/api/app/core/rate_limit.py`] — deferred, pre-existing
- [x] [Review][Defer] W7 — Checkpoint `node_outputs` read-modify-write not atomic — safe with current sequential LangGraph; actionable only if nodes are parallelised [`apps/api/app/modules/content/pipeline/graph.py`] — deferred, pre-existing
- [x] [Review][Defer] W8 — ElevenLabs reference in `tts_node` TODO (banned per CLAUDE.md) — pre-existing, outside story scope [`apps/api/app/modules/content/pipeline/graph.py`] — deferred, pre-existing
- [x] [Review][Defer] W9 — `fitz.*` still in mypy overrides after pymupdf removed — intentional per dev notes (transition guard) [`apps/api/pyproject.toml`] — deferred, intentional
