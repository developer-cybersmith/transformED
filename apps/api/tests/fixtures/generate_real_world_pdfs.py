"""
Real-world PDF fixture generator — derives messy, non-synthetic fixtures
from a real textbook instead of a programmatic PDF writer.

``generate_eval_pdfs.py``'s 20 fixtures are all built with fpdf2 — a
programmatic *writer* that can only ever produce clean, well-formed pages
with a real text layer. It structurally cannot produce what breaks in
practice: a scanned page with no extractable text, a rotated scan, a
truncated/corrupted file, or a password-locked one. D127
(``docs/DEFECT-REGISTER.md``) registers this as a real, previously
undocumented coverage gap.

These 4 fixtures close it without adding any new copyrighted content and
without a new dependency — pypdfium2 (render), PIL (rotate), and fpdf2's
own ``set_encryption()`` are already dependencies of this repo:

- ``real_scan_like.pdf``           — 3 real pages of ``d2l.pdf`` ("Dive into
                                       Deep Learning", CC BY-SA 4.0, tracked
                                       at the repo root — its license
                                       permits this derivative use, unlike
                                       ``EvadingEDR.pdf``, a commercial book
                                       deliberately never used here)
                                       rendered to images at 300 DPI (CLAUDE.md
                                       constraint) and re-embedded with NO
                                       text layer — a genuine OCR-required
                                       fixture built from real content.
- ``real_scan_like_rotated.pdf``   — the same 3 pages, each image rotated
                                       90 degrees before embedding — a
                                       sideways scan.
- ``real_corrupted_truncated.pdf`` — real ``d2l.pdf`` bytes, cut off a third
                                       of the way through — a real damaged
                                       upload, not synthetic garbage bytes.
- ``real_encrypted_locked.pdf``    — real, readable text content, password-
                                       protected via fpdf2's native
                                       ``set_encryption()`` — exactly what a
                                       student-uploaded locked PDF looks like.

Run from ``apps/api/``::

    python -m tests.fixtures.generate_real_world_pdfs

Writes into ``tests/fixtures/real_pdfs/``. Deterministic and re-runnable,
same as ``generate_eval_pdfs.py`` — as long as ``d2l.pdf`` at the repo root
is unchanged, byte-identical output every run.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from fpdf import FPDF
from PIL import Image

_OUTPUT_DIR = Path(__file__).parent / "real_pdfs"

# apps/api/tests/fixtures -> apps/api/tests -> apps/api -> apps -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SOURCE_BOOK = _REPO_ROOT / "d2l.pdf"

# Real body-text pages (0-based) confirmed to carry clean prose, not
# front-matter/TOC noise — "1 Introduction / Until recently, nearly every
# computer program..." at page 40, continuing into pages 41-42.
_SAMPLE_PAGE_INDICES = (40, 41, 42)

_DPI = 300  # CLAUDE.md: PDF image extraction must render at 300 DPI minimum
_PX_TO_PT = 72 / _DPI

_ENCRYPTED_PASSWORD = "eval-harness-test-only"  # noqa: S105 — test fixture, not a real secret


def _require_source_book() -> None:
    if not _SOURCE_BOOK.exists():
        raise FileNotFoundError(
            f"real-world fixtures require {_SOURCE_BOOK} (tracked at the repo root) — "
            "not found. Run this from a full checkout, not a sparse/shallow one."
        )


def _render_page_image(page_index: int) -> Image.Image:
    doc = pdfium.PdfDocument(str(_SOURCE_BOOK))
    try:
        page = doc[page_index]
        bitmap = page.render(scale=_DPI / 72)
        image: Image.Image = bitmap.to_pil()
        return image
    finally:
        doc.close()


def _image_only_pdf(*, rotate_degrees: int = 0) -> bytes:
    """Build a PDF whose pages are pure raster images with no text draw
    calls at all — exactly what a real scan looks like to the extraction
    pipeline: real embedded pixels, zero extractable text layer."""
    pdf = FPDF(unit="pt")
    for page_index in _SAMPLE_PAGE_INDICES:
        img = _render_page_image(page_index)
        if rotate_degrees:
            img = img.rotate(rotate_degrees, expand=True)
        width_pt = img.width * _PX_TO_PT
        height_pt = img.height * _PX_TO_PT
        pdf.add_page(format=(width_pt, height_pt))
        pdf.image(img, x=0, y=0, w=width_pt, h=height_pt)
    return bytes(pdf.output())


def _build_real_scan_like() -> bytes:
    return _image_only_pdf(rotate_degrees=0)


def _build_real_scan_like_rotated() -> bytes:
    return _image_only_pdf(rotate_degrees=90)


def _build_real_corrupted_truncated() -> bytes:
    """Real book bytes, cut off mid-file — a real damaged upload (network
    interruption, incomplete browser upload), not hand-written garbage
    bytes with a fake ``%PDF`` header."""
    real_bytes = _SOURCE_BOOK.read_bytes()
    cutoff = len(real_bytes) // 3
    return real_bytes[:cutoff]


def _build_real_encrypted_locked() -> bytes:
    """Real, readable text — password-protected. The pipeline is never
    given the password, exactly like a student-uploaded locked PDF."""
    pdf = FPDF()
    pdf.set_encryption(owner_password=_ENCRYPTED_PASSWORD, user_password=_ENCRYPTED_PASSWORD)
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(
        0,
        8,
        text=(
            "This chapter covers cellular respiration and the electron transport "
            "chain. The content is real and extractable in principle, but the file "
            "is locked with a password the pipeline is never given."
        ),
    )
    return bytes(pdf.output())


_GENERATORS: dict[str, object] = {
    "real_scan_like": _build_real_scan_like,
    "real_scan_like_rotated": _build_real_scan_like_rotated,
    "real_corrupted_truncated": _build_real_corrupted_truncated,
    "real_encrypted_locked": _build_real_encrypted_locked,
}


def generate_all(output_dir: Path = _OUTPUT_DIR) -> dict[str, Path]:
    """Generate all 4 real-world fixtures, returning {name: path}. Overwrites
    existing files. Raises FileNotFoundError early (via _require_source_book)
    rather than partially writing some fixtures and silently skipping the
    ones that need d2l.pdf."""
    _require_source_book()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, builder in _GENERATORS.items():
        pdf_bytes = builder()  # type: ignore[operator]
        path = output_dir / f"{name}.pdf"
        path.write_bytes(pdf_bytes)
        written[name] = path
    return written


def main() -> None:
    written = generate_all()
    for name, path in written.items():
        size_kb = path.stat().st_size / 1024
        print(f"{name}: {path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
