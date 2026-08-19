"""
Unit tests for Story 2-14 (S2-14): eval harness runner (AC-4, AC-7).

Mocks run_pipeline/get_supabase/get_langfuse at their source modules
(runner.py's lazy in-function imports — established convention, see
test_slide_generator_node.py's module docstring). No live services.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.test_lesson_ready_pubsub import REAL_LESSON_PACKAGE

FAKE_LESSON_ID = "60606060-6060-6060-6060-606060606060"
FAKE_USER_ID = "10101010-1010-1010-1010-101010101010"


FAKE_CHAPTER_ID = "30303030-3030-3030-3030-303030303030"


def _mock_supabase() -> MagicMock:
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"book_id": "20202020-2020-2020-2020-202020202020"}
    ]
    sb.storage.from_.return_value.upload.return_value = MagicMock()
    # D124: run_eval now queries `chapters` (populated by book_ingest_job,
    # itself mocked below) after ingest — one fake chapter row is enough for
    # these tests, which exercise run_eval's own scoring/isolation logic,
    # not real chapter detection.
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {
            "chapter_id": FAKE_CHAPTER_ID,
            "book_id": "20202020-2020-2020-2020-202020202020",
            "page_start": 1,
            "page_end": 10,
            "chapter_index": 0,
            "boundary_confidence": "fallback",
        }
    ]
    return sb


def _mock_book_ingest_job() -> AsyncMock:
    """D124: run_eval now calls the real production ingestion entry point
    before the chapters query above — mocked here so these tests exercise
    run_eval's own logic, not real PDF parsing/chapter detection (covered
    separately by `tests/unit/test_book_ingest_job.py`)."""
    return AsyncMock(return_value={"chapters_written": 1})


def _mock_langfuse_span() -> MagicMock:
    span = MagicMock()
    span.score_trace = MagicMock()
    span.end = MagicMock()
    return span


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_eval_valid_package_scores_and_records_langfuse(tmp_path: Path) -> None:
    from tests.evals.runner import run_eval

    pdf_path = tmp_path / "short.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")

    sb = _mock_supabase()
    span = _mock_langfuse_span()
    mock_langfuse = MagicMock()
    mock_langfuse.start_observation.return_value = span

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.langfuse.get_langfuse", return_value=mock_langfuse),
        patch("app.workers.jobs.book_ingest.book_ingest_job", new=_mock_book_ingest_job()),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(return_value=REAL_LESSON_PACKAGE),
        ) as mock_run_pipeline,
    ):
        result = await run_eval(pdf_path, "short", FAKE_LESSON_ID, FAKE_USER_ID)

    assert result.package_valid is True
    assert result.error is None
    assert result.slide_quality is not None
    assert result.quiz_relevance is not None
    mock_run_pipeline.assert_awaited_once()
    span.score_trace.assert_any_call(
        name="slide_quality", value=result.slide_quality, data_type="NUMERIC"
    )
    span.score_trace.assert_any_call(
        name="quiz_relevance", value=result.quiz_relevance, data_type="NUMERIC"
    )
    span.end.assert_called_once()
    # Storage upload happened before the pipeline ran.
    sb.storage.from_.assert_any_call("source-pdfs")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_eval_pipeline_failure_isolated_not_raised(tmp_path: Path) -> None:
    """AC-4: a pipeline exception is caught and recorded, never propagated —
    one PDF's failure must not abort the harness run for the other 4."""
    from tests.evals.runner import run_eval

    pdf_path = tmp_path / "short.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")

    sb = _mock_supabase()
    span = _mock_langfuse_span()
    mock_langfuse = MagicMock()
    mock_langfuse.start_observation.return_value = span

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.langfuse.get_langfuse", return_value=mock_langfuse),
        patch("app.workers.jobs.book_ingest.book_ingest_job", new=_mock_book_ingest_job()),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(side_effect=RuntimeError("cost ceiling exceeded")),
        ),
    ):
        result = await run_eval(pdf_path, "short", FAKE_LESSON_ID, FAKE_USER_ID)

    assert result.package_valid is False
    assert result.slide_quality is None
    assert result.quiz_relevance is None
    assert result.error == "cost ceiling exceeded"
    # Span still closed even on failure.
    span.end.assert_called_once()
    # No scores recorded on a failed run.
    span.score_trace.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_eval_invalid_package_shape_is_isolated_as_failure(tmp_path: Path) -> None:
    """A pipeline that returns a malformed (schema-invalid) LessonPackage
    dict is treated as a failed run, not an uncaught exception."""
    from tests.evals.runner import run_eval

    pdf_path = tmp_path / "short.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")

    sb = _mock_supabase()
    span = _mock_langfuse_span()
    mock_langfuse = MagicMock()
    mock_langfuse.start_observation.return_value = span

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.langfuse.get_langfuse", return_value=mock_langfuse),
        patch("app.workers.jobs.book_ingest.book_ingest_job", new=_mock_book_ingest_job()),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(return_value={"not": "a valid lesson package"}),
        ),
    ):
        result = await run_eval(pdf_path, "short", FAKE_LESSON_ID, FAKE_USER_ID)

    assert result.package_valid is False
    assert result.error is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_all_evals_isolates_per_pdf_failures_and_writes_results(tmp_path: Path) -> None:
    """AC-6: run_all_evals writes a timestamped results JSON; AC-4: one
    failing PDF (mocked to raise) doesn't stop the remaining PDFs."""
    from tests.evals.runner import run_all_evals
    from tests.fixtures.generate_eval_pdfs import generate_all

    fixtures_dir = tmp_path / "fixtures"
    results_dir = tmp_path / "results"
    generate_all(fixtures_dir)

    sb = _mock_supabase()
    span = _mock_langfuse_span()
    mock_langfuse = MagicMock()
    mock_langfuse.start_observation.return_value = span

    call_count = 0

    async def _flaky_run_pipeline(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # second PDF fails, the rest succeed
            raise RuntimeError("simulated node crash")
        return REAL_LESSON_PACKAGE

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.langfuse.get_langfuse", return_value=mock_langfuse),
        patch("app.workers.jobs.book_ingest.book_ingest_job", new=_mock_book_ingest_job()),
        patch("app.modules.content.pipeline.graph.run_pipeline", new=_flaky_run_pipeline),
    ):
        results = await run_all_evals(fixtures_dir=fixtures_dir, results_dir=results_dir)

    assert len(results) == 20
    assert sum(1 for r in results if r.package_valid) == 19
    assert sum(1 for r in results if not r.package_valid) == 1

    written = list(results_dir.glob("*.json"))
    assert len(written) == 1
    import json

    payload = json.loads(written[0].read_text())
    assert payload["summary"]["pdfs_run"] == 20
    assert payload["summary"]["pdfs_valid"] == 19
    assert payload["summary"]["pdfs_crashed"] == 1


# ── S3-1: 20-PDF expansion guards ────────────────────────────────────────────


@pytest.mark.unit
def test_eval_pdf_keys_matches_generator_keys_exactly() -> None:
    """Story 3-57 (S3-1): _EVAL_PDF_KEYS (runner.py) and _GENERATORS (the
    fixture generator) are two independently-edited lists of the same names —
    the "two documents both claiming authority drift" pattern CLAUDE.md's
    binding rule 5 names as a recorded defect class in this repo. This must
    fail loudly the moment either list is edited without the other."""
    from tests.evals.runner import _EVAL_PDF_KEYS
    from tests.fixtures.generate_eval_pdfs import _GENERATORS

    runner_keys = set(_EVAL_PDF_KEYS)
    generator_keys = set(_GENERATORS.keys())

    assert runner_keys == generator_keys, (
        f"_EVAL_PDF_KEYS and _GENERATORS have drifted. "
        f"Only in runner.py: {runner_keys - generator_keys}. "
        f"Only in generate_eval_pdfs.py: {generator_keys - runner_keys}."
    )
    assert len(_EVAL_PDF_KEYS) == 20, f"S3-1 requires exactly 20 PDFs, got {len(_EVAL_PDF_KEYS)}"


@pytest.mark.unit
def test_generated_pdfs_satisfy_their_category_page_count_boundary(tmp_path: Path) -> None:
    """Story 3-57 AC: short (<=10 pages), long (>=100 pages) — verified against
    the REAL page count of the generated bytes (pypdfium2), not assumed from
    the builder's own page-count parameter."""
    import pypdfium2 as pdfium

    from tests.fixtures.generate_eval_pdfs import generate_all

    written = generate_all(tmp_path)

    # Review finding (AC Completeness): the story's own Verification section
    # promises "20 real PDF files are produced, each non-empty" — neither half
    # was previously asserted here (page-count boundaries were checked, but
    # not the count or non-emptiness the same sentence claims).
    assert len(written) == 20, f"S3-1 requires exactly 20 PDFs, got {len(written)}"

    for name, path in written.items():
        assert path.stat().st_size > 0, f"{name}: generated PDF must be non-empty"

        doc = pdfium.PdfDocument(str(path))
        try:
            n_pages = len(doc)
        finally:
            doc.close()

        if name.startswith("short_"):
            assert n_pages <= 10, f"{name}: short category must be <=10 pages, got {n_pages}"
        elif name.startswith("long_"):
            assert n_pages >= 100, f"{name}: long category must be >=100 pages, got {n_pages}"
