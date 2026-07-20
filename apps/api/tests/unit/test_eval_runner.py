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


def _mock_supabase() -> MagicMock:
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"book_id": "20202020-2020-2020-2020-202020202020"}
    ]
    sb.storage.from_.return_value.upload.return_value = MagicMock()
    return sb


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
    span.score_trace.assert_any_call(name="slide_quality", value=result.slide_quality, data_type="NUMERIC")
    span.score_trace.assert_any_call(name="quiz_relevance", value=result.quiz_relevance, data_type="NUMERIC")
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
        patch("app.modules.content.pipeline.graph.run_pipeline", new=_flaky_run_pipeline),
    ):
        results = await run_all_evals(fixtures_dir=fixtures_dir, results_dir=results_dir)

    assert len(results) == 5
    assert sum(1 for r in results if r.package_valid) == 4
    assert sum(1 for r in results if not r.package_valid) == 1

    written = list(results_dir.glob("*.json"))
    assert len(written) == 1
    import json

    payload = json.loads(written[0].read_text())
    assert payload["summary"]["pdfs_run"] == 5
    assert payload["summary"]["pdfs_valid"] == 4
    assert payload["summary"]["pdfs_crashed"] == 1
