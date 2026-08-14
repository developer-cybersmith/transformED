"""
Synthetic PDF fixture generator for the eval harness (S2-14 built 5, S3-1
expands to 20).

Generates 20 PDFs — 4 meaningfully-distinct variants per required category
(docs/dev1-tracker.md S3-1): short, long, dense-text, table-heavy,
image-heavy. No real textbook content is available in this environment -
these are synthetic stand-ins. The generator is deterministic and
re-runnable (Story 2-14 AC-2, unchanged by S3-1) so real PDFs can replace
these later without changing the eval runner.

Run from ``apps/api/``::

    python -m tests.fixtures.generate_eval_pdfs

Writes into ``tests/fixtures/eval_pdfs/``.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from PIL import Image

_OUTPUT_DIR = Path(__file__).parent / "eval_pdfs"

# Fixed seed content - no randomness, so two runs produce structurally
# identical PDFs (Story 2-14 AC-2).
_LOREM = (
    "The mitochondrion is the primary site of cellular respiration, converting "
    "nutrients into adenosine triphosphate through a series of enzymatic "
    "reactions collectively known as the electron transport chain. "
)


def _new_pdf() -> FPDF:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", size=12)
    return pdf


# ── short (<=10 pages) — 4 variants ─────────────────────────────────────────


def _build_short(pages: int, *, sparse: bool = False) -> bytes:
    """<=10 pages. ``sparse=True`` puts near-empty content on each page instead
    of a full paragraph — a different extraction load than "few but full" pages."""
    pdf = _new_pdf()
    for page in range(pages):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(
            0,
            10,
            text=f"Chapter 1: Introduction to Cell Biology (Page {page + 1})",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("Helvetica", size=12)
        repeats = 1 if sparse else 10
        pdf.multi_cell(0, 8, text=_LOREM * repeats, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── long (>=100 pages) — 4 variants ─────────────────────────────────────────


def _build_long(pages: int) -> bytes:
    """>=100 pages: a long chapter sequence at the given page count."""
    pdf = _new_pdf()
    for page in range(pages):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(
            0, 10, text=f"Section {page // 10 + 1}.{page % 10 + 1}", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 7, text=_LOREM * 6, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── dense_text — 4 variants ──────────────────────────────────────────────────


def _build_dense_text_uniform() -> bytes:
    """Dense-text: many paragraphs per page, minimal whitespace, no tables/images."""
    pdf = _new_pdf()
    for page in range(15):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Dense Chapter - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for _ in range(4):
            pdf.multi_cell(0, 5, text=_LOREM * 2, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _build_dense_text_long_paragraphs() -> bytes:
    """Dense-text: few, very long unbroken paragraphs per page."""
    pdf = _new_pdf()
    for page in range(12):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Long-form Chapter - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 5, text=_LOREM * 14, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _build_dense_text_short_paragraphs() -> bytes:
    """Dense-text: many short, fragment-like paragraphs per page."""
    pdf = _new_pdf()
    for page in range(15):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Fragments - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for i in range(10):
            pdf.multi_cell(0, 5, text=f"{i + 1}. {_LOREM[:80]}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _build_dense_text_with_headers() -> bytes:
    """Dense-text: same density, but broken up by frequent subheadings —
    a different structure-detection load than uniform density."""
    pdf = _new_pdf()
    for page in range(15):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Structured Chapter - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        for sub in range(4):
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, text=f"{page + 1}.{sub + 1} Subsection", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
            pdf.multi_cell(0, 5, text=_LOREM, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── table_heavy — 4 variants ─────────────────────────────────────────────────


def _table_page(pdf: FPDF, page_num: int, rows: int, cols: int, tables_per_page: int) -> None:
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, text=f"Data Tables - Page {page_num}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    headers = [f"Col{c}" for c in range(cols)]
    for table_index in range(tables_per_page):
        data = [headers]
        for row in range(rows):
            data.append([f"r{table_index}{row}c{c}" for c in range(cols)])
        with pdf.table() as table:
            for data_row in data:
                row_obj = table.row()
                for datum in data_row:
                    row_obj.cell(datum)
        pdf.ln(4)


def _build_table_heavy_small() -> bytes:
    """Small tables (4 cols x 5 rows), several per page — S2-14's original shape."""
    pdf = _new_pdf()
    for page in range(8):
        _table_page(pdf, page + 1, rows=5, cols=4, tables_per_page=3)
    return bytes(pdf.output())


def _build_table_heavy_wide() -> bytes:
    """Wide tables (many columns), one per page."""
    pdf = _new_pdf()
    for page in range(8):
        _table_page(pdf, page + 1, rows=4, cols=9, tables_per_page=1)
    return bytes(pdf.output())


def _build_table_heavy_tall() -> bytes:
    """Tall tables (many rows), one per page."""
    pdf = _new_pdf()
    for page in range(8):
        _table_page(pdf, page + 1, rows=20, cols=3, tables_per_page=1)
    return bytes(pdf.output())


def _build_table_heavy_mixed() -> bytes:
    """Tables interspersed with narrative paragraph text, not pure-table pages."""
    pdf = _new_pdf()
    for page in range(8):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Mixed Content - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 5, text=_LOREM * 2, new_x="LMARGIN", new_y="NEXT")
        data = [["Enzyme", "Rate"], ["E1", "10"], ["E2", "12"], ["E3", "9"]]
        with pdf.table() as table:
            for data_row in data:
                row_obj = table.row()
                for datum in data_row:
                    row_obj.cell(datum)
        pdf.ln(4)
        pdf.multi_cell(0, 5, text=_LOREM, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# ── image_heavy — 4 variants ─────────────────────────────────────────────────


def _synthetic_image(seed: int, size: tuple[int, int] = (200, 150)) -> Image.Image:
    """A small deterministic gradient/shape image - no external asset files."""
    img = Image.new("RGB", size, color=(255, 255, 255))
    pixels = img.load()
    w, h = size
    for x in range(w):
        for y in range(h):
            pixels[x, y] = ((x + seed * 17) % 256, (y + seed * 31) % 256, (seed * 53) % 256)
    return img


def _build_image_heavy_small() -> bytes:
    """Many small embedded images per page — S2-14's original shape."""
    pdf = _new_pdf()
    for page in range(10):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Illustrations - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for slot in range(4):
            img = _synthetic_image(seed=page * 4 + slot)
            x = 10 + (slot % 2) * 95
            y = 25 + (slot // 2) * 60
            pdf.image(img, x=x, y=y, w=85, h=50)
        pdf.multi_cell(
            0,
            6,
            text="Figure captions describe the illustrations above.",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    return bytes(pdf.output())


def _build_image_heavy_large() -> bytes:
    """Few large images per page."""
    pdf = _new_pdf()
    for page in range(8):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Full-page Figure - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        img = _synthetic_image(seed=page, size=(400, 300))
        pdf.image(img, x=20, y=25, w=170, h=127)
    return bytes(pdf.output())


def _build_image_heavy_captioned() -> bytes:
    """Images with substantial caption text — tests mixed text+image extraction."""
    pdf = _new_pdf()
    for page in range(8):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Captioned Figures - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        img = _synthetic_image(seed=page, size=(300, 200))
        pdf.image(img, x=30, y=25, w=150, h=100)
        pdf.set_y(130)
        pdf.set_font("Helvetica", size=9)
        pdf.multi_cell(
            0,
            5,
            text=f"Figure {page + 1}: {_LOREM * 3}",
            new_x="LMARGIN",
            new_y="NEXT",
        )
    return bytes(pdf.output())


def _build_image_heavy_grid() -> bytes:
    """Dense grid of many small images per page — stress case."""
    pdf = _new_pdf()
    for page in range(6):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Figure Grid - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        for slot in range(12):
            img = _synthetic_image(seed=page * 12 + slot, size=(80, 60))
            x = 10 + (slot % 4) * 47
            y = 25 + (slot // 4) * 55
            pdf.image(img, x=x, y=y, w=42, h=35)
    return bytes(pdf.output())


_GENERATORS: dict[str, object] = {
    # short (<=10 pages)
    "short_1page": lambda: _build_short(1),
    "short_3page": lambda: _build_short(3),
    "short_10page": lambda: _build_short(10),
    "short_sparse": lambda: _build_short(5, sparse=True),
    # long (>=100 pages)
    "long_100page": lambda: _build_long(100),
    "long_150page": lambda: _build_long(150),
    "long_250page": lambda: _build_long(250),
    "long_400page": lambda: _build_long(400),
    # dense_text
    "dense_text_uniform": _build_dense_text_uniform,
    "dense_text_long_paragraphs": _build_dense_text_long_paragraphs,
    "dense_text_short_paragraphs": _build_dense_text_short_paragraphs,
    "dense_text_with_headers": _build_dense_text_with_headers,
    # table_heavy
    "table_heavy_small": _build_table_heavy_small,
    "table_heavy_wide": _build_table_heavy_wide,
    "table_heavy_tall": _build_table_heavy_tall,
    "table_heavy_mixed": _build_table_heavy_mixed,
    # image_heavy
    "image_heavy_small": _build_image_heavy_small,
    "image_heavy_large": _build_image_heavy_large,
    "image_heavy_captioned": _build_image_heavy_captioned,
    "image_heavy_grid": _build_image_heavy_grid,
}


def generate_all(output_dir: Path = _OUTPUT_DIR) -> dict[str, Path]:
    """Generate all 20 eval PDFs, returning {name: path}. Overwrites existing files."""
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
