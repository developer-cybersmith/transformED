"""
Eval harness runner. Story 2-14 (S2-14) built the 5-PDF subset of the
pre-existing `/run-evals` command spec (.claude/commands/run-evals.md);
Story 3-57 (S3-1) expands it to the full 20-PDF gate.

`run_eval()` runs ONE PDF through the real content pipeline (`run_pipeline`,
unmodified) and scores the result. `run_all_evals()` runs all 20 fixture
PDFs and writes a timestamped results JSON, matching the command spec's
documented `tests/evals/results/<timestamp>.json` output location.

A single PDF's failure never aborts the others — matches the pipeline's own
per-node "never hard-fail" philosophy, applied at the harness level (AC-4).

This module is pure library code (`run_eval`/`run_all_evals`) — the actual
live 20-PDF pytest entry point (gated behind the `live_eval` marker, Story
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

_EVAL_PDF_KEYS: tuple[str, ...] = (
    # short (<=10 pages)
    "short_1page",
    "short_3page",
    "short_10page",
    "short_sparse",
    # long (>=100 pages)
    "long_100page",
    "long_150page",
    "long_250page",
    "long_400page",
    # dense_text
    "dense_text_uniform",
    "dense_text_long_paragraphs",
    "dense_text_short_paragraphs",
    "dense_text_with_headers",
    # table_heavy
    "table_heavy_small",
    "table_heavy_wide",
    "table_heavy_tall",
    "table_heavy_mixed",
    # image_heavy
    "image_heavy_small",
    "image_heavy_large",
    "image_heavy_captioned",
    "image_heavy_grid",
)

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
    # Story 2-38: real USD spent on this lesson, read from the cost tracker.
    # `None` means the meter could not be read — deliberately NOT 0.0, which
    # would be indistinguishable from a genuinely free run.
    cost_usd: float | None = None
    # D124: which real chapter this run actually evaluated, and how it was
    # detected — makes it visible in the results JSON when a fixture only
    # ever produced one whole-book "fallback" chapter versus a genuinely
    # detected sub-chapter, which is otherwise invisible in the summary.
    chapter_id: str = ""
    boundary_confidence: str | None = None


async def _read_lesson_cost(lesson_id: str) -> float | None:
    """Read the real USD spent on *lesson_id*, best-effort (Story 2-38 AC-2).

    The pipeline has already run and already been billed by the time this is
    called. Letting a Redis error escape would turn a successful, paid-for run
    into a failed eval — observability displacing the result it observes, which
    is the same mistake `_safe_trace` and `_safe_record` exist to avoid.
    """
    try:
        from app.core.cost_tracker import get_cost

        return float(await get_cost(lesson_id))
    except Exception:  # noqa: BLE001 — the meter must never break the measurement
        logger.warning(
            "eval: could not read cost for lesson %s — reporting unknown", lesson_id, exc_info=True
        )
        return None


async def _clear_lesson_cost_key(lesson_id: str) -> None:
    """Drop the Redis cost key (Story 2-38 AC-4).

    `run_eval` calls `run_pipeline` directly rather than going through the ARQ
    job, so the worker's own `clear_lesson_cost` never runs and every eval would
    otherwise leak a key.
    """
    try:
        from app.core.cost_tracker import clear_lesson_cost

        await clear_lesson_cost(lesson_id)
    except Exception:  # noqa: BLE001
        logger.warning("eval: could not clear cost key for lesson %s", lesson_id, exc_info=True)


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
            # D124: chapters.book_id is ON DELETE CASCADE, so this also
            # removes every chapter row book_ingest_job wrote for this run —
            # no separate chapters delete needed.
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
    from app.core.db import get_supabase, rows
    from app.core.langfuse import get_langfuse
    from app.modules.content.pipeline.graph import run_pipeline
    from app.schemas.lesson import LessonPackage
    from app.workers.jobs.book_ingest import book_ingest_job

    started = time.monotonic()
    span = None
    book_id: str | None = None
    storage_path: str | None = None
    chapter_id: str = ""
    boundary_confidence: str | None = None
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
        book_id = str(rows(books_resp)[0]["book_id"])

        storage_path = f"{user_id}/{book_id}/{pdf_key}.pdf"
        supabase.storage.from_("source-pdfs").upload(
            path=storage_path,
            file=pdf_path.read_bytes(),
            file_options={"content-type": "application/pdf"},
        )

        # D124 (docs/DEFECT-REGISTER.md): Story 1-13 made `extract_node`
        # REQUIRE a real, resolvable `chapter_id` and refuse to run against a
        # whole document — this harness predates that change and was left
        # constructing a fake whole-book lesson with no chapter at all, so
        # every eval run has failed instantly since Story 1-13 landed. Fixed
        # by running the SAME real production ingestion entry point the ARQ
        # worker enqueues (`book_ingest_job` — a plain `async def`, not
        # ARQ-bound, exactly as `tests/unit/test_book_ingest_job.py` already
        # calls it directly) instead of hand-rolling detection here. Makes
        # zero LLM/TTS/image calls (pure PDF parsing + the chapter_detection
        # ladder) — no new real-spend surface.
        await book_ingest_job({}, book_id, storage_path)

        chapters_resp = (
            supabase.table("chapters")
            .select("chapter_id, book_id, page_start, page_end, chapter_index, boundary_confidence")
            .eq("book_id", book_id)
            .execute()
        )
        chapter_rows = rows(chapters_resp)
        if not chapter_rows:
            raise RuntimeError(
                f"eval:{pdf_key} — book_ingest_job wrote zero chapters for book_id={book_id}"
            )
        # Largest page span = most token-cost-representative chapter to
        # evaluate; tie-break on lowest chapter_index for determinism across
        # reruns. A no-op whenever detection falls through to its R5
        # whole-document fallback (one chapter row spanning the whole PDF) —
        # the likely outcome for these synthetic fixtures, none of which
        # carry a real TOC/heading hierarchy (`generate_eval_pdfs.py`).
        chosen_chapter = max(
            chapter_rows,
            key=lambda c: (int(c["page_end"]) - int(c["page_start"]) + 1, -int(c["chapter_index"])),
        )
        chapter_id = str(chosen_chapter["chapter_id"])
        boundary_confidence = chosen_chapter.get("boundary_confidence")

        supabase.table("lessons").insert(
            {
                "lesson_id": lesson_id,
                "user_id": user_id,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "tier": "T2",
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
            chapter_id=chapter_id,
            tier="T2",
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
            cost_usd=await _read_lesson_cost(lesson_id),
            chapter_id=chapter_id,
            boundary_confidence=boundary_confidence,
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("eval:%s — pipeline run failed: %s", pdf_key, exc, exc_info=True)
        return EvalResult(
            pdf_key=pdf_key,
            lesson_id=lesson_id,
            package_valid=False,
            slide_quality=None,
            quiz_relevance=None,
            chapter_id=chapter_id,
            boundary_confidence=boundary_confidence,
            elapsed_seconds=time.monotonic() - started,
            error=str(exc),
            # AC-3: a run that died partway has still spent money, and that is
            # the most useful number when diagnosing a ceiling breach.
            cost_usd=await _read_lesson_cost(lesson_id),
        )
    finally:
        if span is not None:
            try:
                span.end()
            except Exception:  # noqa: BLE001
                logger.warning("eval:%s — failed to close Langfuse span", pdf_key, exc_info=True)
        if supabase is not None:
            _cleanup_eval_rows(supabase, pdf_key, lesson_id, book_id, storage_path)
        await _clear_lesson_cost_key(lesson_id)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# First real live run (2026-08-18) surfaced a second real gap alongside the
# Redis one above: the old default, an all-zeros placeholder UUID, has no
# matching row in the real project's `auth.users`/`public.users` (the latter
# FK-references the former, see `20260611000000_initial_schema.sql:69`), so
# every `books` insert failed `books_user_id_fkey` before any provider was
# ever called. Fixed at the root, not worked around per-call: a dedicated
# real auth user was created via `sb.auth.admin.create_user(...)`
# (`on_auth_user_created` trigger auto-populates the matching `public.users`
# row), specifically so every future live-eval run — not just this one —
# reuses the same real, valid id without hitting this wall again.
# eval-harness@internal.transformed.local
_EVAL_HARNESS_USER_ID = "517b7c57-97d9-4656-b98c-7be3525eb592"


async def run_all_evals(
    fixtures_dir: Path = _FIXTURES_DIR,
    results_dir: Path = _RESULTS_DIR,
    user_id: str = _EVAL_HARNESS_USER_ID,
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

    # First real live run of this harness (2026-08-18) surfaced a genuine gap:
    # every pipeline node reaches Redis via `get_redis()`, which requires
    # `init_redis()` to have run first — normally done once by `main.py`'s
    # FastAPI lifespan on app startup. This harness invokes `run_pipeline`
    # directly, outside that lifespan, so nothing ever called it — every one
    # of the 20 PDFs failed in well under a second with
    # "Redis pool is not initialised", before any provider was ever called
    # (confirmed: zero OpenAI/Sarvam calls in that run's logs). Mirrors
    # `main.py`'s own init/close pattern exactly rather than inventing a new
    # one. `init_redis`/`close_redis` are both safe to call redundantly
    # (`init_redis` warns and no-ops if already initialised; `close_redis`
    # no-ops if never initialised) — safe even if a caller already set this
    # up around this function for some other reason.
    from app.config import get_settings as _get_settings
    from app.core.redis import close_redis, init_redis

    await init_redis(_get_settings().redis_url)
    try:
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
    finally:
        await close_redis()

    valid_count = sum(1 for r in results if r.package_valid)

    # ── Cost (Story 2-38) ────────────────────────────────────────────────────
    # These are the numbers the $3.00/lesson ceiling was always supposed to be
    # calibrated against, and that no harness has ever reported. Every existing
    # cost figure in the docs predates the 16x duplication fix (D1) and is an
    # estimate; the first live run of this harness produces the real baseline.
    #
    # `None` (an unreadable meter) is EXCLUDED from the mean rather than counted
    # as 0.0 — averaging in a zero would quietly understate the baseline, which
    # is the exact direction of error a cost ceiling must not have.
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    ceiling = _get_settings().max_lesson_cost_usd
    breaches = [r.pdf_key for r in results if r.cost_usd is not None and r.cost_usd > ceiling]

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
        "total_cost_usd": sum(costs) if costs else None,
        "mean_cost_usd": _mean(costs),
        "cost_ceiling_usd": ceiling,
        # AC-6: a number in a JSON file that nobody compares against the limit
        # is not a guard. Name the lessons that went over.
        "cost_ceiling_breaches": breaches,
        "cost_unreadable_for": [r.pdf_key for r in results if r.cost_usd is None],
    }

    if breaches:
        logger.error(
            "Eval: %d of %d lessons exceeded the $%.2f ceiling: %s",
            len(breaches),
            len(results),
            ceiling,
            ", ".join(breaches),
        )

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
