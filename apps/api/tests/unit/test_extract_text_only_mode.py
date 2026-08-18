"""Text-only extraction mode — Story 1-10 T4 (book-scale Phase 3).

Chapter detection needs per-page text and the PDF outline, and nothing else. The
existing extraction mode renders images at 300 DPI, runs OCR, scans every page
for tables with pdfplumber (579 ms/page — ~90 % of extraction cost) and runs
docling on table pages. Doing all that to read a table of contents would put a
1,000-page book minutes over the 15 s budget in AC15.

All PDF parsing here still happens in the isolated subprocess (CLAUDE.md §18) —
including `get_toc()`, which parses the document just as much as text extraction
does.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
SAMPLE_PDF = _REPO_ROOT / "demo-assets" / "sample-chapter.pdf"
EVAL_PDFS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "eval_pdfs"
API_DIR = pathlib.Path(__file__).resolve().parents[2]


def run_text_only(pdf: pathlib.Path) -> dict:
    """Invoke the subprocess exactly as book_ingest_job will."""
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "app.modules.content.pipeline.nodes.extract_subprocess",
            "--text-only",
            str(pdf),
        ],
        capture_output=True,
        text=True,
        cwd=str(API_DIR),
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, f"text-only extraction failed: {proc.stderr[-2000:]}"
    return json.loads(proc.stdout)


@pytest.mark.unit
@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="demo-assets/sample-chapter.pdf absent")
def test_text_only_returns_one_text_per_page_plus_the_outline() -> None:
    out = run_text_only(SAMPLE_PDF)
    assert out["page_count"] > 0
    assert len(out["page_texts"]) == out["page_count"], (
        "page_texts must be per-page — flattening it is what the old mode did, and "
        "is exactly the data chapter detection needs back"
    )
    assert isinstance(out["toc"], list)
    assert any(t.strip() for t in out["page_texts"]), "no text extracted at all"


@pytest.mark.unit
@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="demo-assets/sample-chapter.pdf absent")
def test_text_only_does_no_rendering_ocr_or_table_scanning() -> None:
    """AC11/AC15. The keys the expensive work produces must be absent — their
    presence would mean the cost is being paid."""
    out = run_text_only(SAMPLE_PDF)
    for expensive in ("image_files", "tables_detected", "docling_pages", "font_blocks"):
        assert expensive not in out, (
            f"{expensive!r} present — the text-only path is doing work chapter "
            f"detection does not need"
        )


@pytest.mark.unit
@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="demo-assets/sample-chapter.pdf absent")
def test_text_only_writes_no_files() -> None:
    """It takes no img_dir and must not create one."""
    before = set(pathlib.Path(API_DIR).glob("*"))
    run_text_only(SAMPLE_PDF)
    assert set(pathlib.Path(API_DIR).glob("*")) == before


@pytest.mark.unit
@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="demo-assets/sample-chapter.pdf absent")
def test_text_only_is_fast_enough_for_the_budget() -> None:
    """AC15 budget is 15 s for a 1,000-page book. Phase 1 measured the sweep at
    2.8-7.9 ms/page; this asserts the same order of magnitude on the sample so a
    regression (e.g. someone reinstating the table scan) is caught here rather
    than on a real book."""
    started = time.perf_counter()
    out = run_text_only(SAMPLE_PDF)
    elapsed = time.perf_counter() - started
    per_page_ms = 1000 * elapsed / max(out["page_count"], 1)
    assert per_page_ms < 200, (
        f"{per_page_ms:.0f} ms/page including interpreter startup — the sweep alone "
        f"was measured at 2.8-7.9 ms/page in Phase 1"
    )


@pytest.mark.unit
def test_text_only_reports_a_corrupt_pdf_as_a_nonzero_exit() -> None:
    """AC18 — book_ingest_job turns this into books.status='failed'. A crash that
    still exits 0, or a hang, would strand the book instead."""
    bad = API_DIR / "tests" / "fixtures" / "_not_a_pdf.tmp"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf" + b"\x00" * 64)
    try:
        proc = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "app.modules.content.pipeline.nodes.extract_subprocess",
                "--text-only",
                str(bad),
            ],
            capture_output=True,
            text=True,
            cwd=str(API_DIR),
            timeout=120,
            check=False,
        )
        assert proc.returncode != 0, "a corrupt PDF must not exit 0"
    finally:
        bad.unlink(missing_ok=True)


@pytest.mark.unit
def test_legacy_three_argument_contract_is_unchanged() -> None:
    """The generation pipeline still calls the old form (graph.py:280-290). Adding
    a mode must not move its arguments."""
    src = (
        API_DIR / "app" / "modules" / "content" / "pipeline" / "nodes" / "extract_subprocess.py"
    ).read_text(encoding="utf-8")
    assert "Usage: extract_subprocess" in src
    graph = (API_DIR / "app" / "modules" / "content" / "pipeline" / "graph.py").read_text(
        encoding="utf-8"
    )
    assert "nodes.extract_subprocess" in graph
    # the legacy call passes pdf, img_dir, ocr_threshold positionally and no mode flag
    assert "--text-only" not in graph


@pytest.mark.unit
@pytest.mark.skipif(not (EVAL_PDFS / "short_3page.pdf").exists(), reason="eval fixture absent")
def test_text_only_handles_a_script_generated_pdf_with_no_outline() -> None:
    """The repo's own fixtures have zero bookmarks — Phase 1 flagged this. The mode
    must return an empty toc rather than fail."""
    out = run_text_only(EVAL_PDFS / "short_3page.pdf")
    assert out["toc"] == []
    assert out["page_count"] >= 1
