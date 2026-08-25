"""Real-world PDF extraction coverage — D127/D128 (docs/DEFECT-REGISTER.md).

Every existing extraction test — including all 20 of the S3-1 eval-harness
fixtures — runs against `fpdf`-generated PDFs: clean, well-formed pages with
a real text layer. That library cannot produce what breaks in practice: a
scanned page with no extractable text, a rotated scan, a truncated file, or
a password-locked one. The OCR fallback path (`_ocr_page_text`,
`extract_subprocess.py`) already existed and already worked before this
file, but every test that touched it monkeypatched the real Tesseract call
out — nothing in this repo had ever run it against real scanned pixels.

These tests call the REAL `extract_pdf()` — no mocks — against 4 fixtures
derived from a real textbook (`generate_real_world_pdfs.py`). No live
credentials, no API cost: this is pure local PDF parsing plus local
Tesseract, exactly like the pipeline's own subprocess-isolated extraction
step (CLAUDE.md §18).
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from app.modules.content.pipeline.nodes.extract_subprocess import extract_pdf
from tests.fixtures.generate_real_world_pdfs import (
    _GENERATORS,
    _OUTPUT_DIR,
    _SOURCE_BOOK,
    generate_all,
)

pytestmark = pytest.mark.unit

_SKIP_REASON = (
    f"real-world fixtures need {_SOURCE_BOOK} (tracked at the repo root) — "
    "not present in this checkout"
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_fixtures() -> None:
    """Generate the 4 fixtures on demand — they're gitignored (one is a
    multi-MB partial copy of the source book), same convention as the
    existing 20 eval PDFs. Skips the whole module, not each test
    individually, when d2l.pdf itself isn't in this checkout."""
    if not _SOURCE_BOOK.exists():
        pytest.skip(_SKIP_REASON)
    generate_all()


def _fixture_path(name: str) -> Path:
    return _OUTPUT_DIR / f"{name}.pdf"


def test_real_world_generator_has_exactly_four_fixtures() -> None:
    """Drift guard, same pattern as S3-1's
    `test_eval_pdf_keys_matches_generator_keys_exactly` — this file's own
    fixture list below must track `_GENERATORS` exactly."""
    assert set(_GENERATORS.keys()) == {
        "real_scan_like",
        "real_scan_like_rotated",
        "real_corrupted_truncated",
        "real_encrypted_locked",
    }


def test_scan_like_fixture_has_zero_extractable_text_layer() -> None:
    """Confirms the fixture actually IS scan-shaped before trusting any
    OCR result below — a raster page with no text operators, not
    accidentally still carrying a text layer."""
    doc = pdfium.PdfDocument(str(_fixture_path("real_scan_like")))
    try:
        for page in doc:
            assert page.get_textpage().get_text_bounded() == ""
    finally:
        doc.close()


def test_ocr_fallback_recovers_real_text_from_an_upright_scan(tmp_path: Path) -> None:
    """The real Tesseract call, not a mock — proves the OCR fallback that
    has existed since Story 1-4 actually works against a genuine scanned
    page, which nothing in this repo had ever verified."""
    result = extract_pdf(str(_fixture_path("real_scan_like")), str(tmp_path), ocr_threshold=50)
    assert result["page_count"] == 3
    # The source page's real opening line (page 40 of d2l.pdf) — OCR noise
    # is expected (this is real Tesseract output, not a fixture), but the
    # actual words must be recoverable, not empty and not garbage.
    assert "Introduction" in result["raw_text"]
    assert "computer program" in result["raw_text"]
    assert len(result["raw_text"]) > 500


def test_ocr_on_a_rotated_scan_is_accepted_but_flagged_low_confidence(
    tmp_path: Path,
) -> None:
    """D128 (docs/DEFECT-REGISTER.md) — real, live-confirmed fix, not just a
    documented gap. Tesseract has no orientation correction here, so a
    90-degree-rotated real scan produces non-empty but UNREADABLE text —
    live-confirmed 2026-08-21: a real, fully-billed lesson built from this
    exact fixture scored a PERFECT slide_quality=1.0/quiz_relevance=1.0
    while carrying this garbage content. The content is still ACCEPTED
    (never silently dropped — a lesser defect than losing real content), but
    now the real `extract_pdf()` (not a re-derived confidence check) must
    name the page in `low_confidence_ocr_pages` — the explicit, surfaced
    degradation flag downstream code and a future admin view can act on."""
    result = extract_pdf(
        str(_fixture_path("real_scan_like_rotated")), str(tmp_path), ocr_threshold=50
    )
    # Still succeeds in the same sense as before the fix — non-empty text,
    # no exception, page_count intact. The fix adds a flag, not a rejection.
    assert result["page_count"] == 3
    assert len(result["raw_text"]) > 0
    # Still not the real content — the correct opening line is absent.
    assert "Introduction" not in result["raw_text"]
    # The fix itself: every one of the 3 pages (1-based) is named as
    # low-confidence — this fixture has no readable page to contrast against.
    assert result["low_confidence_ocr_pages"] == [1, 2, 3]


def test_ocr_on_an_upright_scan_is_not_flagged(tmp_path: Path) -> None:
    """Companion to the rotated case — the real, correctly-read scan must
    NOT be flagged, proving the confidence check discriminates real content
    from garbage rather than flagging every OCR'd page indiscriminately."""
    result = extract_pdf(str(_fixture_path("real_scan_like")), str(tmp_path), ocr_threshold=50)
    assert result["low_confidence_ocr_pages"] == []


def test_corrupted_pdf_fails_loud_not_silent(tmp_path: Path) -> None:
    """A real truncated file (cut off a third of the way through real
    bytes, not hand-written garbage) must raise, not return an empty or
    partial result that looks like a valid extraction."""
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 — pdfium's own exception type
        extract_pdf(str(_fixture_path("real_corrupted_truncated")), str(tmp_path), ocr_threshold=50)
    assert (
        "data format" in str(exc_info.value).lower()
        or "failed to load" in str(exc_info.value).lower()
    )


def test_encrypted_pdf_fails_loud_with_an_identifiable_cause(tmp_path: Path) -> None:
    """A password-locked PDF must raise, and the failure must name the real
    cause (a password), not surface as an indistinguishable generic crash —
    this is what a clean, future user-facing message would key off of."""
    with pytest.raises(Exception) as exc_info:  # noqa: PT011
        extract_pdf(str(_fixture_path("real_encrypted_locked")), str(tmp_path), ocr_threshold=50)
    assert "password" in str(exc_info.value).lower()
