"""D127 (docs/DEFECT-REGISTER.md) — the real-world PDF eval tier.

EXCLUDED FROM DEFAULT TEST RUNS, same mechanism as `test_live_run.py`
(marker `live_eval`, gated behind `--run-live-eval` by `conftest.py`).

Two of the four fixtures reach the real, paid pipeline (real OCR recovery
-> real LLM/TTS/image spend, ~$1-1.30/lesson) — the other two are expected
to fail for free, before any provider call. Run explicitly:

    pytest tests/evals/test_live_run_real_world.py -v --run-live-eval

Requires live credentials in .env (same as `test_live_run.py`) and the 4
real-world fixture PDFs already generated at
tests/fixtures/real_pdfs/ (run
`python -m tests.fixtures.generate_real_world_pdfs` first if missing — this
itself requires `d2l.pdf` at the repo root, already tracked in git).
"""

from __future__ import annotations

import pytest

from tests.evals.real_world_runner import (
    REAL_WORLD_EXPECT_INVALID,
    REAL_WORLD_EXPECT_VALID,
    run_all_real_world_evals,
)


@pytest.mark.live_eval
@pytest.mark.asyncio
async def test_real_world_pdfs_behave_as_expected() -> None:
    """D127: the scan-like fixtures must produce a valid LessonPackage via
    real OCR recovery through the full paid pipeline — the harness's own
    proof that OCR-fallback content, not just clean synthetic text, can
    reach a shippable lesson. The corrupted/encrypted fixtures must fail,
    and fail for a reason traceable to the real cause (not silently
    produce something that looks valid)."""
    results = {r.pdf_key: r for r in await run_all_real_world_evals()}

    for key in REAL_WORLD_EXPECT_VALID:
        result = results[key]
        assert result.package_valid, f"{key}: expected a valid package, got error={result.error}"

    for key in REAL_WORLD_EXPECT_INVALID:
        result = results[key]
        assert not result.package_valid, f"{key}: expected this to fail, but it produced a package"
        assert result.error, f"{key}: failed with no error message recorded"
