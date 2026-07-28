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


def _cleanup_eval_rows(
    supabase: Any, pdf_key: str, lesson_id: str, book_id: str | None, storage_path: str | None
) -> None:
    """Best-effort teardown of everything run_eval's setup created — mirrors
    app/modules/content/router.py::upload_lesson's own rollback sequence
    (2026-07-17 review finding, Blind Hunter + Acceptance Auditor,
    independently: without this, every eval run — success or failure —
    permanently accumulated books/lessons/lesson_jobs rows and a Storage
    object, defeating the harness's own "cheap, frequent" design goal).
    Each delete is isolated so one failing cleanup step doesn't abandon the
    rest — same pattern router.py already uses. Never raises.

    Called on EVERY outcome, including success: the eval harness's unit of
    value is the `EvalResult` (already captured in memory and written to
    the results JSON by the time this runs), not a lingering `lessons` row
    under a throwaway/placeholder `user_id` — there is no real product user
    who needs that row to persist.
    """
    try:
        supabase.table("lesson_jobs").delete().eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning(
            "eval:%s — cleanup: failed to delete lesson_jobs row", pdf_key, exc_info=True
        )
    try:
        supabase.table("lessons").delete().eq("lesson_id", lesson_id).execute()
    except Exception:  # noqa: BLE001
        logger.warning("eval:%s — cleanup: failed to delete lessons row", pdf_key, exc_info=True)
    if storage_path:
        try:
            supabase.storage.from_("source-pdfs").remove([storage_path])
        except Exception:  # noqa: BLE001
            logger.warning(
                "eval:%s — cleanup: failed to remove Storage object", pdf_key, exc_info=True
            )
    if book_id:
        try:
            supabase.table("books").delete().eq("book_id", book_id).execute()
        except Exception:  # noqa: BLE001
            logger.warning("eval:%s — cleanup: failed to delete books row", pdf_key, exc_info=True)


async def run_eval(pdf_path: Path, pdf_key: str, lesson_id: str, user_id: str) -> EvalResult:
    """Run one PDF through the real pipeline and score the output.

    Never raises (AC-4) — every failure mode, including a malformed
    `pdf_key`/`user_id` or a Langfuse client that can't even be constructed,
    is caught and recorded in `EvalResult.error`; the caller
    (`run_all_evals`) continues to the next PDF regardless. (2026-07-17
    review finding, Edge Case Hunter: the original version had two
    unguarded failure points — the `_SAFE_PATH_RE` check and
    `get_langfuse()` — sitting BEFORE any try block, so either one raising
    contradicted this exact docstring claim. Both are now inside the single
    outer try/except below.)

    Rows/Storage objects created during setup are cleaned up in `finally`
    regardless of outcome (see `_cleanup_eval_rows`).
    """
    from app.core.db import get_supabase
    from app.core.langfuse import get_langfuse
    from app.modules.content.pipeline.graph import run_pipeline
    from app.schemas.lesson import LessonPackage

    started = time.monotonic()
    span = None
    book_id: str | None = None
    storage_path: str | None = None
    supabase = None

    try:
        if not _SAFE_PATH_RE.match(pdf_key):
            raise ValueError(f"unsafe pdf_key for storage path: {pdf_key!r}")
        if not _SAFE_PATH_RE.match(user_id):
            raise ValueError(f"unsafe user_id for storage path: {user_id!r}")

        try:
            langfuse = get_langfuse()
            span = langfuse.start_observation(
                name=f"eval:{pdf_key}",
                as_type="span",
                input={"pdf_key": pdf_key, "lesson_id": lesson_id},
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "eval:%s — failed to open Langfuse span, continuing without it",
                pdf_key,
                exc_info=True,
            )
            span = None

        supabase = get_supabase()

        # ── Setup: books/lessons/lesson_jobs rows + Storage upload ─────────────
        # Mirrors app/modules/content/router.py::upload_lesson's setup sequence
        # (S1-10) minus the ARQ enqueue — this harness calls run_pipeline()
        # directly instead of going through the worker.
        books_resp = (
            supabase.table("books")
            .insert({"user_id": user_id, "filename": f"{pdf_key}.pdf"})
            .execute()
        )
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
        supabase.table("lesson_jobs").insert(
            {"lesson_id": lesson_id, "status": "pending"}
        ).execute()

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
        if supabase is not None:
            _cleanup_eval_rows(supabase, pdf_key, lesson_id, book_id, storage_path)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


async def run_all_evals(
    fixtures_dir: Path = _FIXTURES_DIR,
    results_dir: Path = _RESULTS_DIR,
    user_id: str = "00000000-0000-0000-0000-000000000000",
) -> list[EvalResult]:
    """Run all 5 eval PDFs and write a timestamped results JSON.

    Each PDF's failure is isolated (AC-4) — one crash never prevents the
    remaining PDFs from running. `run_eval()` itself is designed to never
    raise, but this loop wraps it anyway (2026-07-17 review finding, Edge
    Case Hunter): relying solely on a callee's "never raises" contract with
    no caller-side guard means any future bug in `run_eval` (or a bug this
    review round missed) would abort the ENTIRE run and discard every
    already-computed result — exactly the failure mode AC-4 exists to
    prevent, applied one layer up from where the docstring alone can
    guarantee it.
    """
    import uuid

    results: list[EvalResult] = []
    for pdf_key in _EVAL_PDF_KEYS:
        pdf_path = fixtures_dir / f"{pdf_key}.pdf"
        lesson_id = str(uuid.uuid4())
        try:
            result = await run_eval(pdf_path, pdf_key, lesson_id, user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "eval:%s — run_eval raised unexpectedly, isolating as a failure",
                pdf_key,
                exc_info=True,
            )
            result = EvalResult(
                pdf_key=pdf_key,
                lesson_id=lesson_id,
                package_valid=False,
                slide_quality=None,
                quiz_relevance=None,
                error=str(exc),
            )
        results.append(result)

    valid_count = sum(1 for r in results if r.package_valid)
    summary: dict[str, Any] = {
        "pdfs_run": len(results),
        "pdfs_valid": valid_count,
        "pdfs_crashed": len(results) - valid_count,
        "mean_slide_quality": _mean(
            [r.slide_quality for r in results if r.slide_quality is not None]
        ),
        "mean_quiz_relevance": _mean(
            [r.quiz_relevance for r in results if r.quiz_relevance is not None]
        ),
    }

    # 2026-07-17 review finding (Edge Case Hunter): a plain second-resolution
    # timestamp silently overwrites a same-second prior run's results with
    # no error. A short random suffix makes a collision astronomically
    # unlikely without needing a real uniqueness check.
    import uuid as _uuid

    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    output_path = results_dir / f"{timestamp}-{_uuid.uuid4().hex[:6]}.json"
    output_path.write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2)
    )
    logger.info("Eval run complete: %s", output_path)

    return results
