"""
Eval harness runner (Story 2-14/S2-14) — implements the 5-PDF subset of the
pre-existing `/run-evals` command spec (.claude/commands/run-evals.md).

`run_eval()` runs ONE PDF through the real content pipeline (`run_pipeline`,
unmodified) and scores the result. `run_all_evals()` runs all 5 fixture PDFs
and writes a timestamped results JSON, matching the command spec's
documented `tests/evals/results/<timestamp>.json` output location.

A single PDF's failure never aborts the others — matches the pipeline's own
per-node "never hard-fail" philosophy, applied at the harness level (AC-4).

This module is pure library code (`run_eval`/`run_all_evals`) — the actual
live 5-PDF pytest entry point (gated behind the `live_eval` marker, Story
2-14 AC-8) lives in `tests/evals/test_live_run.py` so it's discoverable by
pytest's default `test_*.py` collection pattern. Run it explicitly with::

    pytest tests/evals/test_live_run.py -v -m live_eval
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tests.evals.scoring import score_quiz_relevance, score_slide_quality

logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "eval_pdfs"
_RESULTS_DIR = Path(__file__).parent / "results"

_EVAL_PDF_KEYS: tuple[str, ...] = ("short", "long", "dense_text", "table_heavy", "image_heavy")

_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class EvalResult:
    pdf_key: str
    lesson_id: str
    package_valid: bool
    slide_quality: float | None
    slide_quality_issues: list[str] = field(default_factory=list)
    quiz_relevance: float | None = None
    quiz_relevance_issues: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str | None = None


async def run_eval(pdf_path: Path, pdf_key: str, lesson_id: str, user_id: str) -> EvalResult:
    """Run one PDF through the real pipeline and score the output.

    Never raises (AC-4) — a pipeline exception is caught and recorded in
    `EvalResult.error`; the caller (`run_all_evals`) continues to the next
    PDF regardless.
    """
    from app.core.db import get_supabase
    from app.core.langfuse import get_langfuse
    from app.modules.content.pipeline.graph import run_pipeline
    from app.schemas.lesson import LessonPackage

    if not _SAFE_PATH_RE.match(pdf_key):
        raise ValueError(f"unsafe pdf_key for storage path: {pdf_key!r}")

    started = time.monotonic()
    langfuse = get_langfuse()
    span = None
    try:
        span = langfuse.start_observation(
            name=f"eval:{pdf_key}", as_type="span", input={"pdf_key": pdf_key, "lesson_id": lesson_id}
        )
    except Exception:  # noqa: BLE001
        logger.warning("eval:%s — failed to open Langfuse span, continuing without it", pdf_key, exc_info=True)

    try:
        supabase = get_supabase()

        # ── Setup: books/lessons/lesson_jobs rows + Storage upload ─────────────
        # Mirrors app/modules/content/router.py::upload_lesson's setup sequence
        # (S1-10) minus the ARQ enqueue — this harness calls run_pipeline()
        # directly instead of going through the worker.
        books_resp = supabase.table("books").insert(
            {"user_id": user_id, "filename": f"{pdf_key}.pdf"}
        ).execute()
        book_id = books_resp.data[0]["book_id"]

        storage_path = f"{user_id}/{book_id}/{pdf_key}.pdf"
        supabase.storage.from_("source-pdfs").upload(
            path=storage_path,
            file=pdf_path.read_bytes(),
            file_options={"content-type": "application/pdf"},
        )

        supabase.table("lessons").insert(
            {
                "lesson_id": lesson_id,
                "user_id": user_id,
                "book_id": book_id,
                "status": "generating",
                "source_file_path": storage_path,
            }
        ).execute()
        supabase.table("lesson_jobs").insert({"lesson_id": lesson_id, "status": "pending"}).execute()

        # ── Run ──────────────────────────────────────────────────────────────
        lesson_package = await run_pipeline(
            lesson_id=lesson_id,
            user_id=user_id,
            source_pdf_path=storage_path,
            book_id=book_id,
        )

        LessonPackage.model_validate(lesson_package)
        slide_score = score_slide_quality(lesson_package)
        quiz_score = score_quiz_relevance(lesson_package)

        if span is not None:
            try:
                span.score_trace(name="slide_quality", value=slide_score.value, data_type="NUMERIC")
                span.score_trace(name="quiz_relevance", value=quiz_score.value, data_type="NUMERIC")
            except Exception:  # noqa: BLE001
                logger.warning("eval:%s — failed to record Langfuse scores", pdf_key, exc_info=True)

        return EvalResult(
            pdf_key=pdf_key,
            lesson_id=lesson_id,
            package_valid=True,
            slide_quality=slide_score.value,
            slide_quality_issues=slide_score.issues,
            quiz_relevance=quiz_score.value,
            quiz_relevance_issues=quiz_score.issues,
            elapsed_seconds=time.monotonic() - started,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("eval:%s — pipeline run failed: %s", pdf_key, exc, exc_info=True)
        return EvalResult(
            pdf_key=pdf_key,
            lesson_id=lesson_id,
            package_valid=False,
            slide_quality=None,
            quiz_relevance=None,
            elapsed_seconds=time.monotonic() - started,
            error=str(exc),
        )
    finally:
        if span is not None:
            try:
                span.end()
            except Exception:  # noqa: BLE001
                logger.warning("eval:%s — failed to close Langfuse span", pdf_key, exc_info=True)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


async def run_all_evals(
    fixtures_dir: Path = _FIXTURES_DIR,
    results_dir: Path = _RESULTS_DIR,
    user_id: str = "00000000-0000-0000-0000-000000000000",
) -> list[EvalResult]:
    """Run all 5 eval PDFs and write a timestamped results JSON.

    Each PDF's failure is isolated (AC-4) — one crash never prevents the
    remaining PDFs from running.
    """
    import uuid

    results: list[EvalResult] = []
    for pdf_key in _EVAL_PDF_KEYS:
        pdf_path = fixtures_dir / f"{pdf_key}.pdf"
        lesson_id = str(uuid.uuid4())
        result = await run_eval(pdf_path, pdf_key, lesson_id, user_id)
        results.append(result)

    valid_count = sum(1 for r in results if r.package_valid)
    summary: dict[str, Any] = {
        "pdfs_run": len(results),
        "pdfs_valid": valid_count,
        "pdfs_crashed": len(results) - valid_count,
        "mean_slide_quality": _mean([r.slide_quality for r in results if r.slide_quality is not None]),
        "mean_quiz_relevance": _mean([r.quiz_relevance for r in results if r.quiz_relevance is not None]),
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    output_path = results_dir / f"{timestamp}.json"
    output_path.write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2)
    )
    logger.info("Eval run complete: %s", output_path)

    return results
