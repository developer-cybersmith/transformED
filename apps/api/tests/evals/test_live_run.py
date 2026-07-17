"""
Story 2-14 AC-8: the real 5-PDF eval harness run.

EXCLUDED FROM DEFAULT TEST RUNS (marker `live_eval`, registered in
pyproject.toml with `--strict-markers`). Hits live OpenAI/Sarvam/Azure/
Supabase, costs real API money, and can take up to ~15 minutes per lesson
per the PRD SLA — 5 lessons run sequentially. Run explicitly:

    pytest tests/evals/test_live_run.py -v -m live_eval

Requires live credentials in .env (OPENAI_API_KEY, SARVAM_API_KEY,
AZURE_TTS_KEY, SUPABASE_*, REDIS_URL) and the 5 fixture PDFs already
generated at tests/fixtures/eval_pdfs/ (run
`python -m tests.fixtures.generate_eval_pdfs` first if missing).
"""

from __future__ import annotations

import pytest

from tests.evals.runner import run_all_evals


@pytest.mark.live_eval
@pytest.mark.asyncio
async def test_eval_all_pdfs() -> None:
    """docs/dev1-tracker.md S2-14 AC: all 5 PDFs produce a valid
    LessonPackage; no pipeline crash; per-lesson scores visible in
    Langfuse (recorded by run_eval() itself, not asserted here — Langfuse
    is an external system this test doesn't read back from)."""
    results = await run_all_evals()
    for result in results:
        assert result.package_valid, f"{result.pdf_key}: {result.error}"
