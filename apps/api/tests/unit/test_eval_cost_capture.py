"""Story 2-38: the eval harness must report per-lesson cost.

Why this file exists
--------------------
The repo asserts a **$3.00/lesson ceiling** and enforces it at runtime, while
`tests/evals/runner.py` — the only harness that runs a real lesson end to end —
contained **zero** references to cost, USD or price. So "re-measure the cost
baselines", the standing action from D1's ~4x TTS inflation, was not something
anyone could actually do: there was no instrument.

These tests prove the instrument works **without spending money**. The live eval
is deliberately deferred; proving the meter is correct before running it is the
whole point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

LESSON_ID = "eeeeeeee-0000-0000-0000-000000000001"


def _patches(
    *,
    cost: float | Exception,
    pipeline_raises: Exception | None = None,
) -> list[Any]:
    """Patch everything `run_eval` touches so nothing real is contacted."""
    package = {
        "lesson_id": LESSON_ID,
        "segments": [],
    }

    get_cost = (
        AsyncMock(side_effect=cost) if isinstance(cost, Exception) else AsyncMock(return_value=cost)
    )
    run_pipeline = (
        AsyncMock(side_effect=pipeline_raises)
        if pipeline_raises is not None
        else AsyncMock(return_value=package)
    )

    return [
        patch("app.modules.content.pipeline.graph.run_pipeline", new=run_pipeline),
        patch("app.core.cost_tracker.get_cost", new=get_cost),
        patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock(return_value=None)),
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.langfuse.get_langfuse", return_value=None),
        # LessonPackage is imported lazily inside run_eval, so it must be
        # patched at its source module, not on the runner.
        patch("app.schemas.lesson.LessonPackage", MagicMock()),
        patch(
            "tests.evals.runner.score_slide_quality",
            return_value=MagicMock(value=1.0, issues=[]),
        ),
        patch(
            "tests.evals.runner.score_quiz_relevance",
            return_value=MagicMock(value=1.0, issues=[]),
        ),
    ]


async def _run(tmp_path: Path, **kw: Any) -> Any:  # noqa: ANN401
    """Run `run_eval` against a REAL temp file.

    An earlier version passed `Path("nonexistent.pdf")`. `run_eval` does
    `pdf_path.read_bytes()` during setup, so every call took the *failure* path —
    and because AC-3 captures cost there too, the AC-1 success-path test passed
    without ever exercising the success path. Caught by reading the assertion
    rather than the exit code.
    """
    from tests.evals.runner import run_eval

    pdf = tmp_path / "short.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    ps = _patches(**kw)
    for p in ps:
        p.start()
    try:
        return await run_eval(pdf, "short", LESSON_ID, "user-1")
    finally:
        for p in ps:
            p.stop()


# ── AC-1: the number is captured at all ──────────────────────────────────────


async def test_eval_result_carries_the_lesson_cost() -> None:
    """The whole point: a run reports what it spent."""
    from tests.evals.runner import EvalResult

    assert hasattr(EvalResult, "__dataclass_fields__")
    assert "cost_usd" in EvalResult.__dataclass_fields__, (
        "EvalResult must carry cost_usd — without it the eval cannot produce a baseline"
    )


async def test_cost_is_read_after_the_pipeline_runs(tmp_path: Path) -> None:
    result = await _run(tmp_path, cost=1.2345)

    # Guard first: without this the test passes via the FAILURE path, which also
    # records cost (AC-3), and would prove nothing about a successful run.
    assert result.package_valid is True, f"expected the success path, got error={result.error!r}"
    assert result.cost_usd == pytest.approx(1.2345)


# ── AC-2: capture is best-effort ─────────────────────────────────────────────


async def test_a_redis_failure_reading_cost_does_not_fail_the_eval(tmp_path: Path) -> None:
    """Observability must never displace the result it observes.

    The pipeline has already run and already been billed. Turning a successful,
    paid-for run into a failed eval because the meter could not be read would be
    strictly worse than reporting an unknown cost. Same principle as
    `_safe_trace` and `_safe_record`.
    """
    import redis.exceptions as rex

    result = await _run(tmp_path, cost=rex.ConnectionError("redis down"))

    assert result.package_valid is True, "a cost-read failure must not fail the eval"
    assert result.cost_usd is None, "an unreadable cost must be None, not silently 0.0"


# ── AC-3: the failure path spent money too ───────────────────────────────────


async def test_cost_is_captured_even_when_the_pipeline_fails(tmp_path: Path) -> None:
    """A run that dies partway has still spent money — and that is the most
    interesting number when diagnosing a ceiling breach.
    """
    result = await _run(tmp_path, cost=2.75, pipeline_raises=RuntimeError("node exploded"))

    assert result.package_valid is False
    assert result.error is not None
    assert result.cost_usd == pytest.approx(2.75), (
        "a failed run must still report what it spent before dying"
    )


# ── AC-4: the Redis key is not leaked ────────────────────────────────────────


async def test_the_cost_key_is_cleared_after_each_eval(tmp_path: Path) -> None:
    """`run_eval` calls `run_pipeline` directly, not the ARQ job, so the worker's
    `clear_lesson_cost` never runs. Without this every eval leaks a Redis key.
    """
    from tests.evals import runner

    pdf = tmp_path / "short.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    cleared = AsyncMock(return_value=None)
    ps = _patches(cost=0.5)
    ps.append(patch("app.core.cost_tracker.clear_lesson_cost", new=cleared))
    for p in ps:
        p.start()
    try:
        await runner.run_eval(pdf, "short", LESSON_ID, "user-1")
    finally:
        for p in ps:
            p.stop()

    cleared.assert_awaited_once()
    assert cleared.await_args.args[0] == LESSON_ID


# ── AC-5 / AC-6: the summary aggregates, and names a breach ──────────────────


def _result(pdf_key: str, cost: float | None) -> Any:  # noqa: ANN401
    from tests.evals.runner import EvalResult

    return EvalResult(
        pdf_key=pdf_key,
        lesson_id=f"id-{pdf_key}",
        package_valid=True,
        slide_quality=1.0,
        quiz_relevance=1.0,
        cost_usd=cost,
    )


async def test_summary_reports_total_and_mean_cost(tmp_path: Path) -> None:
    import json

    from tests.evals import runner

    made = [_result("a", 1.0), _result("b", 2.0), _result("c", None)]
    with (
        patch.object(runner, "run_eval", new=AsyncMock(side_effect=made)),
        patch.object(runner, "_EVAL_PDF_KEYS", ("a", "b", "c")),
    ):
        await runner.run_all_evals(fixtures_dir=tmp_path, results_dir=tmp_path)

    written = json.loads(next(tmp_path.glob("*.json")).read_text())
    summary = written["summary"]

    assert summary["total_cost_usd"] == pytest.approx(3.0)
    assert summary["mean_cost_usd"] == pytest.approx(1.5), "None must be excluded, not counted as 0"
    assert written["results"][0]["cost_usd"] == pytest.approx(1.0), (
        "per-lesson figures must be in the JSON so two runs are comparable"
    )


async def test_summary_names_a_lesson_that_breached_the_ceiling(tmp_path: Path) -> None:
    """AC-6. A number in a JSON file that nobody compares against the limit is
    not a guard. The breach has to be stated.
    """
    import json

    from tests.evals import runner

    made = [_result("cheap", 0.5), _result("expensive", 99.0)]
    with (
        patch.object(runner, "run_eval", new=AsyncMock(side_effect=made)),
        patch.object(runner, "_EVAL_PDF_KEYS", ("cheap", "expensive")),
    ):
        await runner.run_all_evals(fixtures_dir=tmp_path, results_dir=tmp_path)

    summary = json.loads(next(tmp_path.glob("*.json")).read_text())["summary"]

    assert summary["cost_ceiling_breaches"] == ["expensive"], (
        f"a lesson over the ceiling must be named, got {summary.get('cost_ceiling_breaches')}"
    )


async def test_no_breach_reported_when_every_lesson_is_under_the_ceiling(tmp_path: Path) -> None:
    """The other half — without this, always-report-a-breach would pass above."""
    import json

    from tests.evals import runner

    made = [_result("a", 0.4), _result("b", 0.6)]
    with (
        patch.object(runner, "run_eval", new=AsyncMock(side_effect=made)),
        patch.object(runner, "_EVAL_PDF_KEYS", ("a", "b")),
    ):
        await runner.run_all_evals(fixtures_dir=tmp_path, results_dir=tmp_path)

    summary = json.loads(next(tmp_path.glob("*.json")).read_text())["summary"]
    assert summary["cost_ceiling_breaches"] == []
