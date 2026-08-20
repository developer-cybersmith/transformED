"""Real-world eval tier — D127 (docs/DEFECT-REGISTER.md).

The S2-14/S3-1 eval harness (`runner.py`, 20 `fpdf`-generated PDFs) is
deliberately synthetic — cheap, frequent, structural regression-catching,
never intended as real-world coverage (see `docs/dev1-tracker.md`'s S3-1
entry). This module is the harness's own admission of what that leaves
uncovered: a scanned page with no text layer, a rotated scan, a truncated
file, a password-locked one — none of which a programmatic PDF writer can
produce (`tests/fixtures/generate_real_world_pdfs.py`'s module docstring
has the full rationale).

Reuses `run_eval()` from `runner.py` unmodified — it is already generic
over `(pdf_path, pdf_key, lesson_id, user_id)` — rather than touching the
drift-guarded `_EVAL_PDF_KEYS`/`run_all_evals` 20-PDF contract at all.

Two of the four fixtures are expected to SUCCEED (the scan-like ones,
which recover real text via OCR and proceed through the full paid
pipeline — real LLM/TTS/image spend, ~$1-1.30/lesson per
`docs/DEFECT-REGISTER.md`'s D78/D87 measurements). Two are expected to
FAIL at `book_ingest_job` — before any provider is ever called, so they
cost nothing (same "zero LLM/TTS/image calls" property `run_eval`'s own
D124 comment already documents for book ingestion). This is why the
result-checking test asserts DIFFERENT outcomes per key rather than a
single "all must be valid" assertion like `test_live_run.py`'s.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tests.evals.runner import EvalResult, run_eval

logger = logging.getLogger(__name__)

_REAL_PDFS_DIR = Path(__file__).parent.parent / "fixtures" / "real_pdfs"
_RESULTS_DIR = Path(__file__).parent / "results"

# Same real auth user `runner.py` creates for the 20-PDF harness (see that
# module's own comment) — duplicated rather than imported across modules
# to avoid reaching across a private (`_`-prefixed) name; the two harnesses
# reuse the DB/Storage rows for the same reason `run_eval`'s own cleanup
# already isolates each run by a fresh `lesson_id`.
_EVAL_HARNESS_USER_ID = "517b7c57-97d9-4656-b98c-7be3525eb592"

# Keys expected to reach a valid LessonPackage (real OCR recovery, real spend).
REAL_WORLD_EXPECT_VALID: tuple[str, ...] = (
    "real_scan_like",
    "real_scan_like_rotated",
)
# Keys expected to fail at ingestion, before any provider call (zero spend).
REAL_WORLD_EXPECT_INVALID: tuple[str, ...] = (
    "real_corrupted_truncated",
    "real_encrypted_locked",
)
REAL_WORLD_PDF_KEYS: tuple[str, ...] = REAL_WORLD_EXPECT_VALID + REAL_WORLD_EXPECT_INVALID


async def run_all_real_world_evals(
    fixtures_dir: Path = _REAL_PDFS_DIR,
    results_dir: Path = _RESULTS_DIR,
    user_id: str = _EVAL_HARNESS_USER_ID,
) -> list[EvalResult]:
    """Run all 4 real-world fixtures through the real pipeline via
    `run_eval()`. Mirrors `run_all_evals`'s Redis lifecycle handling (the
    same gap D124 found: nothing else calls `init_redis()` when
    `run_pipeline` is invoked directly, outside the FastAPI lifespan) —
    duplicated rather than shared, so this module never has to import
    `run_all_evals`'s 20-PDF-specific summary shape.
    """
    from app.config import get_settings as _get_settings
    from app.core.redis import close_redis, init_redis

    await init_redis(_get_settings().redis_url)
    try:
        results: list[EvalResult] = []
        for pdf_key in REAL_WORLD_PDF_KEYS:
            pdf_path = fixtures_dir / f"{pdf_key}.pdf"
            lesson_id = str(uuid.uuid4())
            try:
                result = await run_eval(pdf_path, pdf_key, lesson_id, user_id)
            except Exception as exc:  # noqa: BLE001 — isolate one PDF's crash from the rest
                logger.warning(
                    "real-world-eval:%s — run_eval raised unexpectedly, isolating as a failure",
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

    summary: dict[str, Any] = {
        "pdfs_run": len(results),
        "expected_valid": list(REAL_WORLD_EXPECT_VALID),
        "expected_invalid": list(REAL_WORLD_EXPECT_INVALID),
        "actually_valid": [r.pdf_key for r in results if r.package_valid],
        "actually_invalid": [r.pdf_key for r in results if not r.package_valid],
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    output_path = results_dir / f"real-world-{timestamp}-{uuid.uuid4().hex[:6]}.json"
    output_path.write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2)
    )
    logger.info("Real-world eval run complete: %s", output_path)

    return results
