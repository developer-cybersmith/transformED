"""
PDF extraction subprocess — invoked by extract_node via asyncio.create_subprocess_exec.

Security: runs in an isolated process so that parsing untrusted PDFs cannot
crash the ARQ worker (CLAUDE.md §18).
PyMuPDF (fitz) BANNED — AGPL-3.0 incompatible with SaaS; never import it.

Stack:
  pypdfium2  (Apache 2.0) — text extraction + page rendering at 300 DPI
  pdftext    (Apache 2.0) — structured font/layout metadata for Story 1.3
  pdfplumber (MIT)        — table detection (page.extract_tables()) and image bboxes only
  docling    (Apache 2.0) — whole-document markdown when tables detected
  pytesseract             — OCR fallback for scanned/image-only pages

Usage::

    python -m app.modules.content.pipeline.nodes.extract_subprocess \\
        <pdf_path> <img_dir> <ocr_threshold>

Stdout: JSON ``{"raw_text": str, "page_count": int, "image_files": list, "font_blocks": list}``
Stderr: diagnostic messages only
Exit: 0 = success, 1 = error (uncaught exception)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _page_text(pdfium_page: Any) -> str:
    """Extract raw text from a pypdfium2 page (empty string if none)."""
    try:
        textpage = pdfium_page.get_textpage()
        text: str = textpage.get_text_bounded()
        return text or ""
    except Exception:  # noqa: BLE001
        return ""


def _page_has_tables(plumb_page: Any) -> bool:
    """Return True if pdfplumber detects any table on this page."""
    try:
        return bool(plumb_page.extract_tables())
    except Exception:  # noqa: BLE001
        return False


def _docling_to_markdown(pdf_path: str) -> str | None:
    """Convert the whole PDF to markdown using docling (preserves table structure).

    Only called when at least one page has tables; returns None on any error.
    Whole-document replacement is intentional — docling's structured markdown
    is uniformly higher quality than pypdfium2 for table-containing documents.
    """
    try:
        from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]

        result = DocumentConverter().convert(pdf_path)
        return result.document.export_to_markdown()
    except Exception:  # noqa: BLE001
        logger.warning("docling conversion failed for %s", pdf_path)
        return None


def _ocr_page_text(pdfium_page: Any, img_dir: str, page_num: int) -> str:
    """Render a pypdfium2 page at 300 DPI and run Tesseract OCR on it."""
    try:
        import pytesseract  # type: ignore[import-not-found]

        bitmap = pdfium_page.render(scale=300 / 72)
        pil_img = bitmap.to_pil()
        img_path = os.path.join(img_dir, f"ocr_p{page_num}.png")
        pil_img.save(img_path, format="PNG")
        return pytesseract.image_to_string(pil_img, lang="eng")  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        logger.warning("OCR failed for page %s", page_num, exc_info=True)
        return ""


def _extract_page_images(
    pdfium_page: Any,
    plumb_page: Any,
    img_dir: str,
    page_num: int,
) -> list[dict[str, Any]]:
    """Extract embedded images from a single page at 300 DPI.

    Uses pdfplumber page.images for bbox detection; pypdfium2 for rendering
    the page at 300 DPI (CLAUDE.md: min 300 DPI for extracted images).
    """
    page_images = list(plumb_page.images or [])
    if not page_images:
        return []

    extracted: list[dict[str, Any]] = []
    try:
        scale = 300 / 72  # points → pixels at 300 DPI
        bitmap = pdfium_page.render(scale=scale)
        pil_page = bitmap.to_pil()

        for j, img_meta in enumerate(page_images):
            try:
                x0 = img_meta.get("x0", 0) * scale
                top = img_meta.get("top", 0) * scale
                x1 = img_meta.get("x1", 0) * scale
                bottom = img_meta.get("bottom", 0) * scale
                if x1 <= x0 or bottom <= top:
                    continue
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
        from pdftext.extraction import dictionary_output  # type: ignore[import-not-found]

        pages_data: list[dict[str, Any]] = dictionary_output(pdf_path)
        font_blocks: list[dict[str, Any]] = []
        for page_data in pages_data:
            page_num = page_data.get("page", 0)
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
                            "page": page_num,
                        })
        return font_blocks
    except Exception:  # noqa: BLE001
        logger.warning("pdftext font extraction failed for %s — font_blocks will be empty", pdf_path)
        return []


# ── Public entry point ────────────────────────────────────────────────────────


def extract_pdf(pdf_path: str, img_dir: str, ocr_threshold: int) -> dict[str, Any]:
    """Extract text, font metadata, and embedded images from *pdf_path*.

    Pipeline:
      1. pypdfium2  — text extraction per page (97% accuracy, 100× faster than pdfplumber)
      2. pdfplumber — table detection (page.extract_tables()) + image bbox detection only
      3. pdftext    — structured font/layout blocks for Story 1.3 structure detection
      4. docling    — if any page has tables, replaces pypdfium2 text with table-aware markdown
      5. Tesseract  — OCR fallback at 300 DPI if avg chars/page < *ocr_threshold* AND docling skipped

    Image extraction renders at 300 DPI minimum (CLAUDE.md constraint).

    Args:
        pdf_path:      Absolute local path to the PDF.
        img_dir:       Directory to write extracted image PNGs.
        ocr_threshold: Min average chars/page before Tesseract OCR kicks in.

    Returns:
        ``{"raw_text": str, "page_count": int, "image_files": list, "font_blocks": list}``
    """
    import pdfplumber  # type: ignore[import-not-found]
    import pypdfium2 as pdfium  # type: ignore[import-not-found]

    page_texts: list[str] = []
    image_files: list[dict[str, Any]] = []
    has_tables = False
    total_chars = 0
    page_count: int = 0

    pdf_doc = pdfium.PdfDocument(pdf_path)
    try:
        page_count = len(pdf_doc)

        with pdfplumber.open(pdf_path) as plumb_pdf:
            for page_idx in range(page_count):
                pdfium_page = pdf_doc[page_idx]
                plumb_page = plumb_pdf.pages[page_idx]
                page_num = page_idx + 1  # 1-indexed for storage paths / logging

                # Text via pypdfium2 (97% accuracy, 100× faster than pdfplumber)
                text = _page_text(pdfium_page)
                total_chars += len(text)
                page_texts.append(text)

                # Table detection via pdfplumber (retained only for this trigger)
                if not has_tables and _page_has_tables(plumb_page):
                    has_tables = True

                # Image extraction: pdfplumber bboxes + pypdfium2 300 DPI render
                image_files.extend(
                    _extract_page_images(pdfium_page, plumb_page, img_dir, page_num)
                )
    finally:
        pdf_doc.close()

    raw_text = "\n\n".join(page_texts)

    # pdftext font blocks — consumed by Story 1.3 structure detection
    font_blocks = _extract_font_blocks(pdf_path)

    # Docling upgrade: whole-document markdown when any page has tables
    docling_succeeded = False
    if has_tables:
        md_text = _docling_to_markdown(pdf_path)
        if md_text:
            raw_text = md_text
            docling_succeeded = True

    # P1: OCR only when docling did NOT already produce output — prevents OCR
    # from overwriting valid docling markdown using pre-docling char counts.
    avg_chars = total_chars // max(page_count, 1)
    if avg_chars < ocr_threshold and page_count > 0 and not docling_succeeded:
        ocr_parts: list[str] = []
        pdf_doc_ocr = pdfium.PdfDocument(pdf_path)
        try:
            for page_idx in range(page_count):
                pdfium_page = pdf_doc_ocr[page_idx]
                ocr_parts.append(_ocr_page_text(pdfium_page, img_dir, page_idx + 1))
        finally:
            pdf_doc_ocr.close()
        ocr_text = "\n\n".join(ocr_parts)
        if ocr_text.strip():
            raw_text = ocr_text

    return {
        "raw_text": raw_text,
        "page_count": page_count,
        "image_files": image_files,
        "font_blocks": font_blocks,
    }


def main() -> None:
    """CLI entry point — called by the ARQ worker's extract_node subprocess."""
    if len(sys.argv) < 4:  # noqa: PLR2004
        sys.stderr.write(
            "Usage: extract_subprocess <pdf_path> <img_dir> <ocr_threshold>\n"
        )
        sys.exit(1)

    pdf_path_arg = sys.argv[1]
    img_dir_arg = sys.argv[2]
    threshold_arg = int(sys.argv[3])

    result = extract_pdf(pdf_path_arg, img_dir_arg, threshold_arg)
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
