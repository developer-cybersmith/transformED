"""
Synthetic PDF fixture generator for the S2-14 eval harness.

Generates 5 PDFs covering the eval harness's required categories
(docs/dev1-tracker.md S2-14): short, long, dense-text, table-heavy,
image-heavy. No real textbook content is available in this environment -
these are synthetic stand-ins. The generator is deterministic and
re-runnable (Story 2-14 AC-2) so real PDFs can replace these later without
changing the eval runner.

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


def _build_short() -> bytes:
    """<=10 pages: a brief 3-page chapter."""
    pdf = _new_pdf()
    for page in range(3):
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
        pdf.multi_cell(0, 8, text=_LOREM * 10, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _build_long() -> bytes:
    """>=100 pages: a long chapter sequence."""
    pdf = _new_pdf()
    for page in range(120):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(
            0, 10, text=f"Section {page // 10 + 1}.{page % 10 + 1}", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 7, text=_LOREM * 6, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def _build_dense_text() -> bytes:
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


def _build_table_heavy() -> bytes:
    """Table-heavy: multiple fpdf2 tables per page, triggering docling's
    table-page detection/extraction path."""
    pdf = _new_pdf()
    for page in range(8):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, text=f"Data Tables - Page {page + 1}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for table_index in range(3):
            data = [["Enzyme", "Substrate", "Product", "Rate (µmol/min)"]]
            for row in range(5):
                data.append(
                    [
                        f"E{table_index}{row}",
                        f"S{table_index}{row}",
                        f"P{table_index}{row}",
                        str(10 + row),
                    ]
                )
            with pdf.table() as table:
                for data_row in data:
                    row_obj = table.row()
                    for datum in data_row:
                        row_obj.cell(datum)
            pdf.ln(4)
    return bytes(pdf.output())


def _synthetic_image(seed: int) -> Image.Image:
    """A small deterministic gradient/shape image - no external asset files."""
    img = Image.new("RGB", (200, 150), color=(255, 255, 255))
    pixels = img.load()
    for x in range(200):
        for y in range(150):
            pixels[x, y] = ((x + seed * 17) % 256, (y + seed * 31) % 256, (seed * 53) % 256)
    return img


def _build_image_heavy() -> bytes:
    """Image-heavy: multiple embedded raster images per page."""
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


_GENERATORS: dict[str, object] = {
    "short": _build_short,
    "long": _build_long,
    "dense_text": _build_dense_text,
    "table_heavy": _build_table_heavy,
    "image_heavy": _build_image_heavy,
}


def generate_all(output_dir: Path = _OUTPUT_DIR) -> dict[str, Path]:
    """Generate all 5 eval PDFs, returning {name: path}. Overwrites existing files."""
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
