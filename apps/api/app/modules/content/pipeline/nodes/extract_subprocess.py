"""
PDF extraction subprocess — invoked by extract_node via asyncio.create_subprocess_exec.

Security: runs in an isolated process so that parsing untrusted PDFs cannot
crash the ARQ worker (CLAUDE.md §18).
PyMuPDF (fitz) BANNED — AGPL-3.0 incompatible with SaaS; never import it.

Stack:
  pypdfium2  (Apache 2.0) — text extraction + page rendering at 300 DPI
  pdftext    (Apache 2.0) — structured font/layout metadata for Story 1.3
  pdfplumber (MIT)        — table detection (page.find_tables()) and image bboxes only
  docling    (Apache 2.0) — page-scoped markdown for table-bearing page runs (Story 2-0b)
  pytesseract             — per-page OCR fallback for scanned/image-only pages

Usage::

    python -m app.modules.content.pipeline.nodes.extract_subprocess \\
        <pdf_path> <img_dir> <ocr_threshold>

Stdout: JSON ``{"raw_text": str, "page_count": int, "image_files": list,
"font_blocks": list, "tables_detected": int, "docling_pages": list}``
Stderr: diagnostic messages only
Exit: 0 = success, 1 = error (uncaught exception)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile
from typing import Any

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logger = logging.getLogger(__name__)

# AC-4: images whose bbox covers less than this fraction of the page area, or
# whose rendered size at 300 DPI would be below this pixel-area floor, are
# skipped BEFORE any page render (decorative logos, bullets, rules).
_MIN_IMAGE_PAGE_AREA_FRACTION = 0.05
_MIN_IMAGE_RENDER_PX2 = 10_000

# AC-2: one DocumentConverter per subprocess invocation, created lazily on the
# first table run and reused across runs (model weights load once, ~seconds).
_docling_converter: Any = None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _page_text(pdfium_page: Any) -> str:  # noqa: ANN401
    """Extract raw text from a pypdfium2 page (empty string if none)."""
    try:
        textpage = pdfium_page.get_textpage()
        text: str = textpage.get_text_bounded()
        return text or ""
    except Exception:  # noqa: BLE001
        return ""


def _page_table_count(plumb_page: Any) -> int:  # noqa: ANN401
    """Count tables on a page via pdfplumber (detection only, no cell extraction).

    ``find_tables()`` locates table bboxes without extracting cell text —
    much cheaper than ``extract_tables()``, which is deferred to the docling
    failure fallback path only. Older pdfplumber versions without
    ``find_tables`` fall back to ``extract_tables()`` truthiness.
    """
    try:
        finder = getattr(plumb_page, "find_tables", None)
        if finder is not None:
            return len(finder() or [])
        return len(plumb_page.extract_tables() or [])
    except Exception:  # noqa: BLE001
        return 0


def _release_page(plumb_page: Any, pdfium_page: Any) -> None:  # noqa: ANN401
    """AC-3: free per-page caches every loop iteration so RSS stays O(1 page).

    Each release call is individually guarded — a failure to release must
    never kill extraction.
    """
    with contextlib.suppress(Exception):
        plumb_page.flush_cache()
    with contextlib.suppress(Exception):
        close = getattr(plumb_page, "close", None)
        if close is not None:
            close()
    with contextlib.suppress(Exception):
        pdfium_page.close()


def _group_table_runs(table_page_idxs: list[int], page_count: int) -> list[tuple[int, int]]:
    """Group table pages into contiguous runs for page-scoped docling (AC-2).

    Each table page index is expanded by ±1 page (multi-page-table guard),
    clamped to ``[0, page_count - 1]``, and overlapping or adjacent runs are
    merged. Returns inclusive ``(start, end)`` tuples in ascending order.
    """
    if not table_page_idxs or page_count <= 0:
        return []

    runs: list[tuple[int, int]] = []
    for idx in sorted(set(table_page_idxs)):
        start = max(idx - 1, 0)
        end = min(idx + 1, page_count - 1)
        if runs and start <= runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], max(runs[-1][1], end))
        else:
            runs.append((start, end))
    return runs


def _get_docling_converter() -> Any:  # noqa: ANN401
    """Return the lazily-created, subprocess-wide docling DocumentConverter.

    Docling-internal OCR is disabled: scanned pages are handled by our own
    per-page Tesseract pass (AC-6), and docling is used strictly for table
    structure → markdown.
    """
    global _docling_converter  # noqa: PLW0603
    if _docling_converter is None:
        from docling.datamodel.base_models import (
            InputFormat,
        )
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
        )
        from docling.document_converter import (
            DocumentConverter,
            PdfFormatOption,
        )

        pipeline_options = PdfPipelineOptions(do_ocr=False)
        _docling_converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    return _docling_converter


def _build_sub_pdf(pdf_doc: Any, start: int, end: int, sub_path: str) -> None:  # noqa: ANN401
    """Write pages ``start..end`` (inclusive) of *pdf_doc* to *sub_path*."""
    import pypdfium2 as pdfium

    sub = pdfium.PdfDocument.new()
    try:
        sub.import_pages(pdf_doc, list(range(start, end + 1)))
        sub.save(sub_path)
    finally:
        sub.close()


def _docling_run_pages(sub_pdf_path: str, num_pages: int) -> list[str] | None:
    """Convert a sub-PDF with docling and return per-page markdown.

    Uses docling's page provenance (``export_to_markdown(page_no=k)``, pages
    1-indexed) so each sub-PDF page's markdown can be spliced back onto its
    original page. Returns None on any failure — caller falls back to
    pdfplumber table serialization.
    """
    try:
        converter = _get_docling_converter()
        result = converter.convert(sub_pdf_path)
        document = result.document
        # image_placeholder='' is load-bearing: the default '<!-- image -->' is
        # non-empty, so a scanned/picture-only page inside a run's ±1 expansion
        # would pass the md.strip() splice guard and OVERWRITE that page's
        # Tesseract OCR text with placeholder junk (docling runs do_ocr=False).
        # Empty placeholder → empty markdown → guard keeps the OCR/pypdfium text.
        return [
            document.export_to_markdown(page_no=k, image_placeholder="")
            for k in range(1, num_pages + 1)
        ]
    except Exception:  # noqa: BLE001
        logger.warning("docling conversion failed for %s", sub_pdf_path, exc_info=True)
        return None


def _table_rows_to_markdown(rows: list[list[Any]]) -> str:
    """Serialize pdfplumber table rows as a GitHub markdown table."""
    if not rows:
        return ""

    def _cell(value: Any) -> str:  # noqa: ANN401
        if value is None:
            return ""
        return str(value).replace("\n", " ").replace("|", "\\|").strip()

    n_cols = max(len(row) for row in rows)

    def _fmt(row: list[Any]) -> str:
        padded = list(row) + [None] * (n_cols - len(row))
        return "| " + " | ".join(_cell(c) for c in padded) + " |"

    lines = [_fmt(rows[0]), "| " + " | ".join("---" for _ in range(n_cols)) + " |"]
    lines.extend(_fmt(row) for row in rows[1:])
    return "\n".join(lines)


def _append_fallback_tables(pdf_path: str, table_idxs: list[int], page_texts: list[str]) -> None:
    """Docling-failure fallback: append pdfplumber table rows as markdown.

    Re-opens the PDF with pdfplumber (the main loop's pages were already
    released per AC-3) and appends each table page's rows — serialized as
    GitHub markdown tables — to that page's text. Never raises: tables must
    never be silently dropped, but a fallback failure must not crash
    extraction either.
    """
    if not table_idxs:
        return
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as plumb_pdf:
            for idx in table_idxs:
                try:
                    tables = plumb_pdf.pages[idx].extract_tables() or []
                except Exception:  # noqa: BLE001
                    logger.warning("Fallback extract_tables failed for page %s", idx + 1)
                    continue
                tables_md = [md for md in (_table_rows_to_markdown(t) for t in tables) if md]
                if not tables_md:
                    continue
                joined = "\n\n".join(tables_md)
                page_texts[idx] = (
                    f"{page_texts[idx]}\n\n{joined}" if page_texts[idx].strip() else joined
                )
    except Exception:  # noqa: BLE001
        logger.warning("Fallback table serialization failed for %s", pdf_path, exc_info=True)


def _convert_table_runs(
    pdf_doc: Any,  # noqa: ANN401
    pdf_path: str,
    page_texts: list[str],
    table_page_idxs: list[int],
    page_count: int,
) -> list[int]:
    """AC-2: page-scoped docling — convert each table run, splice per page.

    For each contiguous run of table pages (±1 expansion), builds a temporary
    sub-PDF via pypdfium2 and converts ONLY that run with docling. Each
    sub-PDF page's markdown replaces the matching original page's entry in
    *page_texts* (sub-page ``k`` → original page ``start + k``); all other
    pages keep their pypdfium2 text verbatim.

    On docling failure for a run, that run's table pages get their pdfplumber
    table rows appended as markdown instead — extraction never crashes and
    tables are never silently dropped.

    Returns the sorted list of original page indices whose text docling replaced.
    """
    runs = _group_table_runs(table_page_idxs, page_count)
    if not runs:
        return []

    docling_pages: list[int] = []
    with tempfile.TemporaryDirectory(prefix="docling_runs_") as tmp_dir:
        for run_no, (start, end) in enumerate(runs):
            run_table_idxs = [i for i in table_page_idxs if start <= i <= end]
            sub_path = os.path.join(tmp_dir, f"run_{run_no}.pdf")
            try:
                _build_sub_pdf(pdf_doc, start, end, sub_path)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Sub-PDF build failed for run pages %s-%s — using table fallback",
                    start + 1,
                    end + 1,
                    exc_info=True,
                )
                _append_fallback_tables(pdf_path, run_table_idxs, page_texts)
                continue

            page_mds = _docling_run_pages(sub_path, end - start + 1)
            if page_mds is None:
                logger.warning(
                    "Docling failed for run pages %s-%s — using table fallback",
                    start + 1,
                    end + 1,
                )
                _append_fallback_tables(pdf_path, run_table_idxs, page_texts)
                continue

            for k, md in enumerate(page_mds):
                if md.strip():
                    page_texts[start + k] = md
                    docling_pages.append(start + k)
    return sorted(docling_pages)


def _ocr_page_text(pdfium_page: Any, img_dir: str, page_num: int) -> str:  # noqa: ANN401
    """Render a pypdfium2 page at 300 DPI and run Tesseract OCR on it."""
    try:
        import pytesseract

        bitmap = pdfium_page.render(scale=300 / 72)
        pil_img = bitmap.to_pil()
        img_path = os.path.join(img_dir, f"ocr_p{page_num}.png")
        pil_img.save(img_path, format="PNG")
        return pytesseract.image_to_string(pil_img, lang="eng")  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        logger.warning("OCR failed for page %s", page_num, exc_info=True)
        return ""


def _extract_page_images(
    pdfium_page: Any,  # noqa: ANN401
    plumb_page: Any,  # noqa: ANN401
    img_dir: str,
    page_num: int,
) -> list[dict[str, Any]]:
    """Extract embedded images from a single page at 300 DPI.

    Uses pdfplumber page.images for bbox detection; pypdfium2 for rendering
    the page at 300 DPI (CLAUDE.md: min 300 DPI for extracted images).

    AC-4 pre-filter: images below _MIN_IMAGE_PAGE_AREA_FRACTION of page area
    or below _MIN_IMAGE_RENDER_PX2 rendered pixels are dropped BEFORE any
    render; if none survive, the page is never rendered at all.
    """
    page_images = list(plumb_page.images or [])
    if not page_images:
        return []

    scale = 300 / 72  # points → pixels at 300 DPI
    page_area = float(plumb_page.width or 0) * float(plumb_page.height or 0)

    kept: list[tuple[int, dict[str, Any]]] = []
    skipped = 0
    for j, img_meta in enumerate(page_images):
        x0 = img_meta.get("x0", 0)
        top = img_meta.get("top", 0)
        x1 = img_meta.get("x1", 0)
        bottom = img_meta.get("bottom", 0)
        width = x1 - x0
        height = bottom - top
        if width <= 0 or height <= 0:
            skipped += 1
            continue
        bbox_area = width * height
        render_px2 = (width * scale) * (height * scale)
        if (
            page_area > 0 and bbox_area / page_area < _MIN_IMAGE_PAGE_AREA_FRACTION
        ) or render_px2 < _MIN_IMAGE_RENDER_PX2:
            skipped += 1
            continue
        kept.append((j, img_meta))

    if skipped:
        logger.warning(
            "Page %s: skipped %s below-threshold image(s) before render", page_num, skipped
        )
    if not kept:
        return []

    extracted: list[dict[str, Any]] = []
    try:
        bitmap = pdfium_page.render(scale=scale)
        pil_page = bitmap.to_pil()

        for j, img_meta in kept:
            try:
                x0 = img_meta.get("x0", 0) * scale
                top = img_meta.get("top", 0) * scale
                x1 = img_meta.get("x1", 0) * scale
                bottom = img_meta.get("bottom", 0) * scale
                cropped = pil_page.crop((x0, top, x1, bottom))
                img_path = os.path.join(img_dir, f"p{page_num}_{j}.png")
                cropped.save(img_path, format="PNG")
                extracted.append({"page": page_num, "local_path": img_path})
            except Exception:  # noqa: BLE001
                logger.warning("Skipping image p%s_%s: crop/save failed", page_num, j)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to render page %s for image extraction", page_num)

    return extracted


def _extract_font_blocks(pdf_path: str) -> list[dict[str, Any]]:
    """Extract structured font/layout metadata using pdftext (Apache 2.0).

    Returns a flat list of span-level dicts consumed by Story 1.3 structure
    detection to infer heading hierarchy from font name, size, and bold flag.
    """
    try:
        from pdftext.extraction import dictionary_output

        pages_data: list[dict[str, Any]] = dictionary_output(pdf_path)
        font_blocks: list[dict[str, Any]] = []
        for page_data in pages_data:
            page_num = page_data.get("page", 0)
            for block in page_data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font_info = span.get("font", {})
                        font_blocks.append(
                            {
                                "text": span.get("text", ""),
                                "bbox": span.get("bbox", [0, 0, 0, 0]),
                                "font": {
                                    "name": font_info.get("name", ""),
                                    "size": float(font_info.get("size", 12.0)),
                                    "bold": bool(font_info.get("bold", False)),
                                },
                                "page": page_num,
                            }
                        )
        return font_blocks
    except Exception:  # noqa: BLE001
        logger.warning(
            "pdftext font extraction failed for %s — font_blocks will be empty", pdf_path
        )
        return []


# ── Public entry point ────────────────────────────────────────────────────────


def extract_pdf(pdf_path: str, img_dir: str, ocr_threshold: int) -> dict[str, Any]:
    """Extract text, font metadata, and embedded images from *pdf_path*.

    Pipeline:
      1. pypdfium2  — text extraction per page (97% accuracy, 100× faster than pdfplumber)
      2. pdfplumber — table detection (page.find_tables()) + image bbox detection only
      3. Tesseract  — per-page OCR when that page's text yield < *ocr_threshold* chars
      4. pdftext    — structured font/layout blocks for Story 1.3 structure detection
      5. docling    — page-scoped: table-page runs (±1 page) converted to markdown
                      and spliced back per page; non-table pages untouched

    Per-page caches are released every loop iteration (AC-3) so memory stays
    O(1 page). Image extraction renders at 300 DPI minimum (CLAUDE.md
    constraint), with a pre-render size filter (AC-4).

    Args:
        pdf_path:      Absolute local path to the PDF.
        img_dir:       Directory to write extracted image PNGs.
        ocr_threshold: Min chars of text yield per page before Tesseract OCR kicks in.

    Returns:
        ``{"raw_text": str, "page_count": int, "image_files": list,
        "font_blocks": list, "tables_detected": int, "docling_pages": list}``
    """
    import pdfplumber
    import pypdfium2 as pdfium

    page_texts: list[str] = []
    image_files: list[dict[str, Any]] = []
    table_page_idxs: list[int] = []
    tables_detected = 0
    page_count: int = 0

    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        page_count = len(pdf_doc)

        with pdfplumber.open(pdf_path) as plumb_pdf:
            for page_idx in range(page_count):
                pdfium_page = pdf_doc[page_idx]
                plumb_page = plumb_pdf.pages[page_idx]
                page_num = page_idx + 1  # 1-indexed for storage paths / logging
                try:
                    # Text via pypdfium2 (97% accuracy, 100× faster than pdfplumber)
                    text = _page_text(pdfium_page)

                    # Table detection via pdfplumber find_tables (bboxes only)
                    n_tables = _page_table_count(plumb_page)
                    if n_tables:
                        table_page_idxs.append(page_idx)
                        tables_detected += n_tables

                    # Image extraction: pdfplumber bboxes + pypdfium2 300 DPI render
                    image_files.extend(
                        _extract_page_images(pdfium_page, plumb_page, img_dir, page_num)
                    )

                    # AC-6: per-page OCR — only pages with low text yield, while
                    # the pdfium page is still alive; replace only on non-empty OCR.
                    if len(text.strip()) < ocr_threshold:
                        ocr_text = _ocr_page_text(pdfium_page, img_dir, page_num)
                        if ocr_text.strip():
                            text = ocr_text

                    page_texts.append(text)
                finally:
                    # AC-3: release per-page caches so RSS stays O(1 page)
                    _release_page(plumb_page, pdfium_page)

        # AC-2: page-scoped docling for table runs (needs pdf_doc open for
        # sub-PDF building via import_pages)
        docling_pages = _convert_table_runs(
            pdf_doc, pdf_path, page_texts, table_page_idxs, page_count
        )
    finally:
        pdf_doc.close()

    raw_text = "\n\n".join(page_texts)

    # pdftext font blocks — consumed by Story 1.3 structure detection
    font_blocks = _extract_font_blocks(pdf_path)

    return {
        "raw_text": raw_text,
        "page_count": page_count,
        "image_files": image_files,
        "font_blocks": font_blocks,
        "tables_detected": tables_detected,
        "docling_pages": docling_pages,
    }


def main() -> None:
    """CLI entry point — called by the ARQ worker's extract_node subprocess."""
    if len(sys.argv) < 4:  # noqa: PLR2004
        sys.stderr.write("Usage: extract_subprocess <pdf_path> <img_dir> <ocr_threshold>\n")
        sys.exit(1)

    pdf_path_arg = sys.argv[1]
    img_dir_arg = sys.argv[2]
    threshold_arg = int(sys.argv[3])

    result = extract_pdf(pdf_path_arg, img_dir_arg, threshold_arg)
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
