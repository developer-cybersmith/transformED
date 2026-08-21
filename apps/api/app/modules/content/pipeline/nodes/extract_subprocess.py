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
        <pdf_path> <img_dir> <ocr_threshold> [page_start] [page_end]

    python -m app.modules.content.pipeline.nodes.extract_subprocess \\
        --text-only <pdf_path> [front_pages] [head_chars] [page_start] [page_end] \\
        [--tail-chars N]

``--tail-chars`` (D115/D116, 2026-08-15) is a named flag, valid in any position —
it is stripped out of argv before the positional args above are parsed, so it can
never collide with them. 0 (unset) reproduces the pre-existing contract exactly.

``page_start``/``page_end`` (Story 1-12) are **0-based and INCLUSIVE**, matching
``DetectedChapter`` and ``chapters.page_start/page_end``. Both omitted = whole
document. Supplying only one, or a range outside the document, is an error —
ranges are NEVER clamped silently.

Stdout: JSON ``{"raw_text": str, "page_count": int, "extracted_page_count": int,
"page_offset": int, "image_files": list, "font_blocks": list,
"tables_detected": int, "docling_pages": list}``
Stderr: diagnostic messages only
Exit: 0 = success, 1 = error (bad page range or uncaught exception)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterator
from typing import Any

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logger = logging.getLogger(__name__)

# AC-4: images whose bbox covers less than this fraction of the page area, or
# whose rendered size at 300 DPI would be below this pixel-area floor, are
# skipped BEFORE any page render (decorative logos, bullets, rules).
_MIN_IMAGE_PAGE_AREA_FRACTION = 0.05
_MIN_IMAGE_RENDER_PX2 = 10_000

# D128 (docs/DEFECT-REGISTER.md): `_ocr_page_text` previously accepted ANY
# non-empty Tesseract output with no confidence gate. A real page rendered
# upright OCRs at ~96% mean per-word confidence; the identical page rotated
# 90 degrees (no orientation correction here) OCRs to unreadable gibberish at
# ~38% — non-empty, so it passed silently. 60 sits with a clear margin below
# the one measured "readable" data point (96%) and a clear margin above the
# one measured "garbage" data point (38%) — a reasoned margin, not a
# Phase-1-benchmarked constant (same status D115's TITLE_TAIL_WINDOW carries).
_OCR_LOW_CONFIDENCE_THRESHOLD = 60

# AC-2: one DocumentConverter per subprocess invocation, created lazily on the
# first table run and reused across runs (model weights load once, ~seconds).
_docling_converter: Any = None


# ── Page-range helpers (Story 1-12) ───────────────────────────────────────────
#
# TWO INDEX BASES coexist below. Getting them confused is the defect this story
# exists to prevent, so every site that uses one says which:
#
#   ABSOLUTE page index  — 0-based index into the *document*. Used for
#       ``pdf_doc[i]`` / ``plumb_pdf.pages[i]``, ``_build_sub_pdf``, table page
#       indices, and (as ``i + 1``) image filenames and log lines.
#   RELATIVE list position — 0-based index into the returned ``page_texts``
#       list, which holds only the extracted slice.
#
#   relative = absolute - page_offset      absolute = relative + page_offset


def _require_paired_bounds(page_start: int | None, page_end: int | None) -> None:
    """Reject a half-specified range before the document is even opened.

    A range with only one end supplied is a bug in the caller, not a request to
    default the other end (contract: "Only one supplied → error").
    """
    if (page_start is None) != (page_end is None):
        raise ValueError(
            "page_start and page_end must both be supplied or both omitted — got "
            f"page_start={page_start!r}, page_end={page_end!r}"
        )


def _resolve_bounds(
    page_start: int | None, page_end: int | None, page_count: int
) -> tuple[int, int]:
    """Resolve the inclusive ABSOLUTE ``[start, end]`` page range to extract.

    Both bounds omitted → the whole document. Out-of-range bounds raise
    ``ValueError`` naming the offending value AND the document's page count —
    they are NEVER clamped, because a clamped range silently generates a lesson
    from the wrong pages with nothing in the output to say so.
    """
    _require_paired_bounds(page_start, page_end)
    if page_start is None or page_end is None:
        return 0, page_count - 1  # unbounded: whole document

    valid = f"document has {page_count} page(s); valid page indices are 0..{page_count - 1}"
    if page_start < 0:
        raise ValueError(f"page_start={page_start} is out of range — {valid}")
    if page_end < 0:
        raise ValueError(f"page_end={page_end} is out of range — {valid}")
    if page_start >= page_count:
        raise ValueError(f"page_start={page_start} is out of range — {valid}")
    if page_end >= page_count:
        raise ValueError(f"page_end={page_end} is out of range — {valid}")
    if page_start > page_end:
        raise ValueError(f"page_start={page_start} is greater than page_end={page_end} — {valid}")
    return page_start, page_end


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


def _group_table_runs(
    table_page_idxs: list[int],
    page_count: int,
    page_start: int = 0,
    page_end: int | None = None,
) -> list[tuple[int, int]]:
    """Group table pages into contiguous runs for page-scoped docling (AC-2).

    All indices here are ABSOLUTE document page indices.

    Each table page index is expanded by ±1 page (multi-page-table guard),
    clamped to the extracted range ``[page_start, page_end]`` (defaulting to the
    whole document ``[0, page_count - 1]``), and overlapping or adjacent runs
    are merged. Returns inclusive ``(start, end)`` tuples in ascending order.
    """
    if not table_page_idxs or page_count <= 0:
        return []

    lo = page_start
    hi = page_count - 1 if page_end is None else page_end

    runs: list[tuple[int, int]] = []
    for idx in sorted(set(table_page_idxs)):
        start = max(idx - 1, lo)
        end = min(idx + 1, hi)
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


def _append_fallback_tables(
    pdf_path: str,
    table_idxs: list[int],
    page_texts: list[str],
    page_offset: int = 0,
) -> None:
    """Docling-failure fallback: append pdfplumber table rows as markdown.

    Re-opens the PDF with pdfplumber (the main loop's pages were already
    released per AC-3) and appends each table page's rows — serialized as
    GitHub markdown tables — to that page's text. Never raises: tables must
    never be silently dropped, but a fallback failure must not crash
    extraction either.

    Index bases (Story 1-12): *table_idxs* are ABSOLUTE document page indices —
    the re-opened pdfplumber document is the whole PDF, so ``plumb_pdf.pages``
    is indexed absolutely. *page_texts* holds only the extracted slice, so it is
    indexed RELATIVELY as ``idx - page_offset``.
    """
    if not table_idxs:
        return
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as plumb_pdf:
            for idx in table_idxs:  # ABSOLUTE page index
                try:
                    tables = plumb_pdf.pages[idx].extract_tables() or []
                except Exception:  # noqa: BLE001
                    # idx + 1 = ABSOLUTE 1-based page number for the log line
                    logger.warning("Fallback extract_tables failed for page %s", idx + 1)
                    continue
                tables_md = [md for md in (_table_rows_to_markdown(t) for t in tables) if md]
                if not tables_md:
                    continue
                joined = "\n\n".join(tables_md)
                rel = idx - page_offset  # RELATIVE position in the page_texts slice
                if not 0 <= rel < len(page_texts):
                    continue
                page_texts[rel] = (
                    f"{page_texts[rel]}\n\n{joined}" if page_texts[rel].strip() else joined
                )
    except Exception:  # noqa: BLE001
        logger.warning("Fallback table serialization failed for %s", pdf_path, exc_info=True)


def _convert_table_runs(
    pdf_doc: Any,  # noqa: ANN401
    pdf_path: str,
    page_texts: list[str],
    table_page_idxs: list[int],
    page_count: int,
    page_start: int = 0,
    page_end: int | None = None,
) -> list[int]:
    """AC-2: page-scoped docling — convert each table run, splice per page.

    For each contiguous run of table pages (±1 expansion), builds a temporary
    sub-PDF via pypdfium2 and converts ONLY that run with docling. Each
    sub-PDF page's markdown replaces the matching original page's entry in
    *page_texts*; all other pages keep their pypdfium2 text verbatim.

    On docling failure for a run, that run's table pages get their pdfplumber
    table rows appended as markdown instead — extraction never crashes and
    tables are never silently dropped.

    Index bases (Story 1-12, AC9) — the two bases are the same number only when
    unbounded, and diverge by ``page_start`` under a page range, so each site
    below states which it uses:

      ABSOLUTE — *table_page_idxs*, run ``(start, end)``, ``pdf_doc`` indices
        passed to ``_build_sub_pdf``, and the returned ``docling_pages``.
      RELATIVE — positions in *page_texts*, which holds only the extracted
        slice: ``relative = absolute - page_start``.

    Args:
        page_start: ABSOLUTE index of ``page_texts[0]`` (0 when unbounded).
        page_end:   ABSOLUTE index of the last extracted page; ``None`` means
                    the last page of the document.

    Returns:
        The sorted list of ABSOLUTE page indices whose text docling replaced.
    """
    runs = _group_table_runs(table_page_idxs, page_count, page_start, page_end)
    if not runs:
        return []

    docling_pages: list[int] = []  # ABSOLUTE
    with tempfile.TemporaryDirectory(prefix="docling_runs_") as tmp_dir:
        for run_no, (start, end) in enumerate(runs):  # ABSOLUTE run bounds
            run_table_idxs = [i for i in table_page_idxs if start <= i <= end]  # ABSOLUTE
            sub_path = os.path.join(tmp_dir, f"run_{run_no}.pdf")
            try:
                # ABSOLUTE: _build_sub_pdf indexes the full document
                _build_sub_pdf(pdf_doc, start, end, sub_path)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Sub-PDF build failed for run pages %s-%s — using table fallback",
                    start + 1,  # ABSOLUTE 1-based page number
                    end + 1,
                    exc_info=True,
                )
                _append_fallback_tables(pdf_path, run_table_idxs, page_texts, page_start)
                continue

            page_mds = _docling_run_pages(sub_path, end - start + 1)
            if page_mds is None:
                logger.warning(
                    "Docling failed for run pages %s-%s — using table fallback",
                    start + 1,  # ABSOLUTE 1-based page number
                    end + 1,
                )
                _append_fallback_tables(pdf_path, run_table_idxs, page_texts, page_start)
                continue

            for k, md in enumerate(page_mds):
                if not md.strip():
                    continue
                abs_idx = start + k  # ABSOLUTE page index
                rel_idx = abs_idx - page_start  # RELATIVE position in page_texts
                if not 0 <= rel_idx < len(page_texts):
                    continue
                page_texts[rel_idx] = md
                docling_pages.append(abs_idx)
    return sorted(docling_pages)


def _ocr_page_text(pdfium_page: Any, img_dir: str, page_num: int) -> tuple[str, float | None]:  # noqa: ANN401
    """Render a pypdfium2 page at 300 DPI and run Tesseract OCR on it.

    D128: also returns the real mean per-word confidence Tesseract itself
    reports (`image_to_data`), so the caller can tell "OCR ran and the page
    was probably readable" from "OCR ran and produced non-empty gibberish" —
    a distinction the return type previously threw away entirely, since a
    bare `str` cannot carry it. `None` confidence means no words were
    detected at all (nothing to average) — a real, different case from a low
    but non-empty confidence, so it is never coerced to 0.0.
    """
    try:
        import pytesseract

        bitmap = pdfium_page.render(scale=300 / 72)
        pil_img = bitmap.to_pil()
        img_path = os.path.join(img_dir, f"ocr_p{page_num}.png")
        pil_img.save(img_path, format="PNG")
        text: str = pytesseract.image_to_string(pil_img, lang="eng")
        data = pytesseract.image_to_data(pil_img, lang="eng", output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if int(c) >= 0]
        mean_confidence = sum(confidences) / len(confidences) if confidences else None
        return text, mean_confidence
    except Exception:  # noqa: BLE001
        logger.warning("OCR failed for page %s", page_num, exc_info=True)
        return "", None


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


@contextlib.contextmanager
def _font_source_pdf(
    pdf_path: str, page_start: int | None, page_end: int | None
) -> Iterator[tuple[str, int]]:
    """Yield the PDF path pdftext should parse, plus the page-number remap offset.

    Unbounded → the original path and an offset of 0 (byte-identical to the
    pre-Story-1-12 behaviour). Bounded → a temporary sub-PDF holding only pages
    ``page_start..page_end`` (built with the existing ``_build_sub_pdf``), so a
    35-page extraction parses 35 pages instead of the whole 1,151-page book
    (AC8), plus ``page_start`` as the offset that puts the returned page numbers
    back on the ABSOLUTE document base.
    """
    if page_start is None or page_end is None:
        yield pdf_path, 0
        return

    import pypdfium2 as pdfium

    with tempfile.TemporaryDirectory(prefix="fontblocks_") as tmp_dir:
        sub_path = os.path.join(tmp_dir, "font_range.pdf")
        pdf_doc = pdfium.PdfDocument(pdf_path)
        try:
            # ABSOLUTE page indices — _build_sub_pdf indexes the full document
            _build_sub_pdf(pdf_doc, page_start, page_end, sub_path)
        finally:
            pdf_doc.close()
        yield sub_path, page_start


def _extract_font_blocks(
    pdf_path: str, page_start: int | None = None, page_end: int | None = None
) -> list[dict[str, Any]]:
    """Extract structured font/layout metadata using pdftext (Apache 2.0).

    Returns a flat list of span-level dicts consumed by Story 1.3 structure
    detection to infer heading hierarchy from font name, size, and bold flag.

    With *page_start*/*page_end* (0-based, INCLUSIVE, ABSOLUTE) pdftext parses
    only a sub-PDF of that range, and each span's ``page`` is remapped by
    ``+page_start`` so the reported page numbers stay on the ABSOLUTE document
    base — the same base ``_extract_font_blocks`` reports when unbounded.
    """
    try:
        from pdftext.extraction import dictionary_output

        with _font_source_pdf(pdf_path, page_start, page_end) as (source_path, page_delta):
            pages_data: list[dict[str, Any]] = dictionary_output(source_path)
        font_blocks: list[dict[str, Any]] = []
        for page_data in pages_data:
            # ABSOLUTE page number: sub-PDF page + page_start (0 when unbounded)
            page_num = page_data.get("page", 0) + page_delta
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


def extract_pdf(
    pdf_path: str,
    img_dir: str,
    ocr_threshold: int,
    page_start: int | None = None,
    page_end: int | None = None,
) -> dict[str, Any]:
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

    Story 1-12: *page_start*/*page_end* restrict extraction to one chapter's
    pages. Page NUMBERS stay absolute (real book pages) while ``page_texts`` /
    ``raw_text`` cover only the slice — see the index-base note at the top of
    this module.

    Args:
        pdf_path:      Absolute local path to the PDF.
        img_dir:       Directory to write extracted image PNGs.
        ocr_threshold: Min chars of text yield per page before Tesseract OCR kicks in.
        page_start:    First page to extract, 0-based INCLUSIVE. ABSOLUTE.
        page_end:      Last page to extract, 0-based INCLUSIVE. ABSOLUTE.
                       Both omitted = the whole document. Supplying only one, or
                       a range outside the document, raises ``ValueError`` — the
                       range is never clamped.

    Returns:
        ``{"raw_text": str, "page_count": int, "extracted_page_count": int,
        "page_offset": int, "image_files": list, "font_blocks": list,
        "tables_detected": int, "docling_pages": list,
        "low_confidence_ocr_pages": list[int]}`` where ``page_count`` is
        the DOCUMENT's total page count (unchanged meaning — callers depend on
        it), ``page_offset`` is the ABSOLUTE index of ``page_texts[0]``, and
        ``low_confidence_ocr_pages`` (D128) names every ABSOLUTE page number
        where OCR ran and returned non-empty text below
        ``_OCR_LOW_CONFIDENCE_THRESHOLD`` mean per-word confidence — real
        content, but flagged as unreliable rather than silently trusted.
    """
    import pdfplumber
    import pypdfium2 as pdfium

    # Reject a half-specified range before touching the file at all.
    _require_paired_bounds(page_start, page_end)

    page_texts: list[str] = []  # RELATIVE: page_texts[0] is the page at start_idx
    image_files: list[dict[str, Any]] = []
    table_page_idxs: list[int] = []  # ABSOLUTE page indices
    tables_detected = 0
    page_count: int = 0
    # D128: ABSOLUTE page numbers where OCR ran and produced non-empty text
    # below _OCR_LOW_CONFIDENCE_THRESHOLD — an explicit, surfaced degradation
    # flag (CLAUDE.md's "silent truncation is never acceptable" rule) rather
    # than accepting any non-empty OCR output as if it were reliable text.
    low_confidence_ocr_pages: list[int] = []

    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        page_count = len(pdf_doc)  # the DOCUMENT's total — never the slice size
        start_idx, end_idx = _resolve_bounds(page_start, page_end, page_count)

        with pdfplumber.open(pdf_path) as plumb_pdf:
            for page_idx in range(start_idx, end_idx + 1):  # ABSOLUTE page index
                pdfium_page = pdf_doc[page_idx]
                plumb_page = plumb_pdf.pages[page_idx]
                # ABSOLUTE 1-based page number — feeds image storage paths and
                # log lines. Must NOT become chapter-relative: every chapter's
                # images would collide at page_1.png (Story 1-12, AC7).
                page_num = page_idx + 1
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
                        ocr_text, ocr_confidence = _ocr_page_text(pdfium_page, img_dir, page_num)
                        if ocr_text.strip():
                            text = ocr_text
                            # D128: flag, don't reject — a low-confidence page
                            # still carries real (if uncertain) content, and a
                            # single bad scan in an otherwise-good chapter
                            # should degrade visibly, not abort the chapter.
                            if (
                                ocr_confidence is not None
                                and ocr_confidence < _OCR_LOW_CONFIDENCE_THRESHOLD
                            ):
                                low_confidence_ocr_pages.append(page_num)

                    page_texts.append(text)
                finally:
                    # AC-3: release per-page caches so RSS stays O(1 page)
                    _release_page(plumb_page, pdfium_page)

        # AC-2: page-scoped docling for table runs (needs pdf_doc open for
        # sub-PDF building via import_pages). Bases passed explicitly: ABSOLUTE
        # run/table indices, RELATIVE page_texts positions (Story 1-12, AC9).
        #
        # The unbounded path keeps the legacy 5-argument call verbatim. The
        # trailing pair defaults to exactly (0, page_count - 1), so the two
        # branches are semantically identical — this preserves the CALL SHAPE
        # that pre-Story-1-12 callers and test doubles bind to.
        if page_start is None and page_end is None:
            docling_pages = _convert_table_runs(
                pdf_doc, pdf_path, page_texts, table_page_idxs, page_count
            )
        else:
            docling_pages = _convert_table_runs(
                pdf_doc, pdf_path, page_texts, table_page_idxs, page_count, start_idx, end_idx
            )
    finally:
        pdf_doc.close()

    raw_text = "\n\n".join(page_texts)

    # pdftext font blocks — consumed by Story 1.3 structure detection. Bounded
    # to the same range (AC8) so a 35-page extraction does not parse 1,151
    # pages; reported page numbers stay ABSOLUTE.
    font_blocks = _extract_font_blocks(pdf_path, page_start, page_end)

    return {
        "raw_text": raw_text,
        "page_count": page_count,  # DOCUMENT total (unchanged meaning)
        "extracted_page_count": len(range(start_idx, end_idx + 1)),
        "page_offset": start_idx,  # ABSOLUTE index of page_texts[0]
        "image_files": image_files,
        "font_blocks": font_blocks,
        "tables_detected": tables_detected,
        "docling_pages": docling_pages,
        # D128: ABSOLUTE page numbers, 1-based — a non-empty list means real
        # content shipped from pages OCR was not confident about.
        "low_confidence_ocr_pages": low_confidence_ocr_pages,
    }


def extract_text_only(
    pdf_path: str,
    front_pages: int = 0,
    head_chars: int = 0,
    page_start: int | None = None,
    page_end: int | None = None,
    *,
    tail_chars: int = 0,
) -> dict[str, Any]:
    """Per-page text + the PDF outline. Nothing else.

    This is what chapter detection (Story 1-10) consumes, and deliberately ALL it
    consumes. Compared with `extract_pdf` this skips:

      - 300-DPI page rendering and image extraction
      - the Tesseract OCR fallback
      - pdfplumber table detection — measured at 579 ms/page in Phase 1, roughly
        90 % of total extraction cost, and irrelevant to finding a chapter boundary
      - docling table-run conversion
      - pdftext font-block extraction

    Phase 1 measured what remains at 2.8-7.9 ms/page: 5.53 s for a 1,671-page book,
    against 11.1 minutes if the table scan were left in.

    `get_toc()` runs here rather than in the caller on purpose. It parses the
    document just as much as text extraction does, and CLAUDE.md §18 requires
    user-uploaded PDFs to be parsed in an isolated subprocess — reading the outline
    in the worker process would be the same class of exposure with a friendlier name.

    Truncation (`front_pages`, `head_chars`) exists for stdout size, and it is not a
    micro-optimisation. This subprocess returns its result as JSON over a pipe, so
    a 1,151-page book ships ~2.4 MB of text the caller then re-parses. Measured on
    the Phase 3 gate: full text put D2L at 14.56 s against a 15 s budget — 3 %
    headroom, on a machine faster than CI.

    The detector needs full text only for the pages the contents scan can reach,
    and `TITLE_WINDOW` characters everywhere else. Passing those two numbers in
    (rather than hardcoding the detector's constants here) keeps the extractor
    ignorant of detection policy.

    Args:
        pdf_path:    absolute path to the PDF.
        front_pages: pages returned in FULL, counted from the START OF THE SLICE
                     — not from the start of the document (Story 1-12). For a
                     bounded call the "front matter" is the chapter's first
                     pages, which is what a chapter-scoped caller means; the
                     book's own front matter is not in range at all.
                     0 = no truncation.
        head_chars:  characters kept per page beyond `front_pages`. 0 = no truncation.
        page_start:  first page to extract, 0-based INCLUSIVE, ABSOLUTE.
        page_end:    last page to extract, 0-based INCLUSIVE, ABSOLUTE. Both
                     omitted = the whole document. Supplying only one, or a
                     range outside the document, raises `ValueError` — never clamped.
        tail_chars:  KEYWORD-ONLY (Story D115/D116, 2026-08-15). On a page that
                     gets truncated to `head_chars`, also keep the LAST
                     `tail_chars` characters, appended after the head slice.
                     0 (default) = no tail, byte-identical to the pre-existing
                     contract. Exists because some publishers emit a chapter's
                     decorative "N / TITLE" opener AFTER the body paragraph in
                     text order, so it lands past `head_chars` and was
                     otherwise discarded before detection ever ran. Bounded and
                     fixed-size like `head_chars` — never proportional to page
                     length — and a genuine widening of what a book-scale
                     ingest's per-page payload can cost: only applied when
                     `len(text) > head_chars + tail_chars` specifically so a
                     page shorter than that never grows past its own length.

    Returns:
        ``{"page_count": int, "extracted_page_count": int, "page_offset": int,
        "page_texts": list[str], "toc": list[dict]}`` where `page_count` is the
        DOCUMENT's total (unchanged meaning), `page_texts` is the SLICE ONLY
        (`page_texts[0]` is the page at `page_offset`), and each toc entry is
        ``{"level", "title", "page_index"}`` with a 0-based ABSOLUTE
        `page_index`. Entries whose destination cannot be resolved are omitted.
        The toc always covers the whole document — an outline is a
        document-level object and the caller uses it to locate chapters.
    """
    import pypdfium2 as pdfium

    # Reject a half-specified range before touching the file at all.
    _require_paired_bounds(page_start, page_end)

    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        page_count = len(pdf_doc)  # the DOCUMENT's total — never the slice size
        start_idx, end_idx = _resolve_bounds(page_start, page_end, page_count)

        toc: list[dict[str, Any]] = []
        for item in pdf_doc.get_toc():
            # PdfBookmark has no `.page_index`/`.title` attributes -- the page
            # index lives on the PdfDest returned by get_dest(), and the title
            # is read via get_title(). Both dest and its index can be None (an
            # unresolvable destination), which is a normal bookmark shape, not
            # an error (review fix, D63 -- reached only by a real PDF with an
            # outline; every local fixture has none, so this path was untested).
            dest = item.get_dest()
            page_index = dest.get_index() if dest is not None else None
            if page_index is None:
                continue  # bookmark with an unresolvable destination
            toc.append(
                {
                    "level": int(item.level),
                    "title": (item.get_title() or "").strip(),
                    "page_index": int(page_index),
                }
            )

        truncate = front_pages > 0 and head_chars > 0
        page_texts: list[str] = []  # RELATIVE: page_texts[0] is the page at start_idx
        for page_idx in range(start_idx, end_idx + 1):  # ABSOLUTE page index
            page = pdf_doc[page_idx]
            try:
                text = _page_text(page)
                # front_pages counts from the START OF THE SLICE, so the
                # comparison uses the RELATIVE position, not the absolute index.
                # Unbounded, start_idx is 0 and the two coincide.
                if truncate and (page_idx - start_idx) >= front_pages:
                    # Only append a tail slice when it doesn't already overlap
                    # the head slice — otherwise a page just over head_chars
                    # long would come back LONGER than before truncation
                    # (e.g. a 450-char page with head_chars=400,
                    # tail_chars=400 would wrongly grow to ~850 chars instead
                    # of shrinking). D115/D116 fix, verified against this
                    # exact edge case.
                    if tail_chars > 0 and len(text) > head_chars + tail_chars:
                        text = text[:head_chars] + "\n" + text[-tail_chars:]
                    else:
                        text = text[:head_chars]
                page_texts.append(text)
            finally:
                # Same per-page cache discipline as extract_pdf (AC-3, Story 2-0):
                # memory stays O(1 page) on a 1,000-page book.
                page.close()
    finally:
        pdf_doc.close()

    return {
        "page_count": page_count,  # DOCUMENT total (unchanged meaning)
        "extracted_page_count": len(range(start_idx, end_idx + 1)),
        "page_offset": start_idx,  # ABSOLUTE index of page_texts[0]
        "page_texts": page_texts,
        "toc": toc,
    }


_TEXT_ONLY_FLAG = "--text-only"
_TAIL_CHARS_FLAG = "--tail-chars"

_USAGE = (
    "Usage: extract_subprocess <pdf_path> <img_dir> <ocr_threshold> [page_start] [page_end]\n"
    "       extract_subprocess --text-only <pdf_path> [front_pages] [head_chars] "
    "[page_start] [page_end] [--tail-chars N]\n"
    "       page_start/page_end are 0-based and INCLUSIVE; supply both or neither.\n"
    "       --tail-chars is a named flag (any position) -- see extract_text_only's "
    "tail_chars kwarg.\n"
)


def _optional_int(argv: list[str], index: int) -> int | None:
    """Parse an optional positional int argument; None when not supplied."""
    return int(argv[index]) if len(argv) > index else None


def _extract_named_int_flag(argv: list[str], flag: str) -> tuple[list[str], int]:
    """Strip `flag value` out of argv (any position), return (remaining argv, value).

    MUST run before positional parsing (`_optional_int` etc.) — appending a
    named flag at the end without first removing it would land it in one of
    the existing positional slots (`page_start`/`page_end`) and raise
    `ValueError` on every call, not just ones that pass the flag (D115/D116).
    Returns 0 when the flag is absent, matching every other "0 = no-op" default
    in this module.
    """
    if flag not in argv:
        return argv, 0
    i = argv.index(flag)
    if i + 1 >= len(argv):
        raise ValueError(f"{flag} requires a value")
    value = int(argv[i + 1])
    return argv[:i] + argv[i + 2 :], value


def main() -> None:
    """CLI entry point — called by the ARQ workers' isolated subprocesses.

    Two modes, both backward compatible. The legacy positional form is what
    `extract_node` still calls (`graph.py:280-290`) and behaves exactly as
    before when no page range is given; `--text-only` is the chapter-detection
    path added by Story 1-10. Story 1-12 appends the optional 0-based INCLUSIVE
    `page_start`/`page_end` pair to both forms.

    A bad page range exits 1 with a diagnostic on stderr naming the offending
    value and the document's page count — it is never clamped.
    """
    try:
        argv, tail_chars = _extract_named_int_flag(list(sys.argv), _TAIL_CHARS_FLAG)

        if len(argv) >= 3 and argv[1] == _TEXT_ONLY_FLAG:  # noqa: PLR2004
            front = int(argv[3]) if len(argv) > 3 else 0  # noqa: PLR2004
            head = int(argv[4]) if len(argv) > 4 else 0  # noqa: PLR2004
            text_start = _optional_int(argv, 5)
            text_end = _optional_int(argv, 6)
            sys.stdout.write(
                json.dumps(
                    extract_text_only(
                        argv[2], front, head, text_start, text_end, tail_chars=tail_chars
                    )
                )
            )
            return

        if len(argv) < 4:  # noqa: PLR2004
            sys.stderr.write(_USAGE)
            sys.exit(1)

        pdf_path_arg = argv[1]
        img_dir_arg = argv[2]
        threshold_arg = int(argv[3])
        page_start_arg = _optional_int(argv, 4)
        page_end_arg = _optional_int(argv, 5)

        result = extract_pdf(pdf_path_arg, img_dir_arg, threshold_arg, page_start_arg, page_end_arg)
        sys.stdout.write(json.dumps(result))
    except ValueError as exc:
        # Bad page range (or non-integer argv). Exit non-zero with the reason —
        # never fall through to a clamped/partial extraction.
        sys.stderr.write(f"{exc}\n")
        sys.stderr.write(_USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
