"""
AC-5 (Story 2-0) — timeout topology + cancellation handling.

Contract: ARQ's job_timeout must leave the extract node's subprocess-cleanup
window reachable (job_timeout >= extract_timeout_cap + 300s), and a cancelled
content_pipeline_job must record lesson_jobs.status='failed' before the
cancellation propagates — no lesson row may sit in "running" forever.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings
from app.workers.main import WorkerSettings


def test_job_timeout_leaves_room_for_extract_cleanup() -> None:
    """Invariant that keeps the extract subprocess cleanup reachable:
    ARQ must not cancel the job until at least 300s after the extract
    timeout cap — otherwise the child-process reap never runs."""
    settings = get_settings()
    assert settings.arq_job_timeout_s >= settings.extract_timeout_cap_s + 300


def test_worker_job_timeout_is_settings_driven() -> None:
    """WorkerSettings.job_timeout must track ARQ_JOB_TIMEOUT_S.

    A hardcoded ``job_timeout = 1800`` literal would still equal the settings
    default, so an in-process equality check cannot detect a revert. Instead,
    spawn a fresh interpreter with a NON-default override and assert the class
    attribute picks it up.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2]  # .../apps/api
    # 7777 is non-default AND satisfies the Settings invariant
    # arq_job_timeout_s >= extract_timeout_cap_s + 300 enforced at model level.
    env = {**os.environ, "ARQ_JOB_TIMEOUT_S": "7777"}
    code = (
        "import sys; from app.workers.main import WorkerSettings; "
        "sys.exit(0 if WorkerSettings.job_timeout == 7777 else 1)"
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        env=env,
        cwd=api_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"WorkerSettings.job_timeout did not track ARQ_JOB_TIMEOUT_S=7777\n{proc.stderr}"
    )

    # In-process sanity: current class value matches current settings.
    assert WorkerSettings.job_timeout == get_settings().arq_job_timeout_s


async def test_cancelled_job_marks_lesson_failed_and_reraises() -> None:
    """ARQ timeout / worker shutdown delivers CancelledError: the job must
    write status='failed' (under asyncio.shield) and re-raise."""
    from app.workers.jobs import content_pipeline as job_mod

    supabase = MagicMock()
    status_mock = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        patch.object(job_mod, "_update_lesson_status", status_mock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await job_mod.content_pipeline_job({}, "lesson-cancelled")

    failed_calls = [
        c for c in status_mock.await_args_list if c.args[2:3] == ("failed",)
    ]
    assert failed_calls, (
        "cancelled job must record lesson_jobs.status='failed' "
        f"(calls seen: {status_mock.await_args_list})"
    )
    assert "cancelled" in failed_calls[0].kwargs.get("error", "")


async def test_second_cancellation_inside_shield_still_reraises_original() -> None:
    """A re-delivered cancellation while the shielded status write runs is a
    BaseException — it must be caught (not escape as an unhandled crash) and
    the ORIGINAL CancelledError must still propagate to ARQ."""
    from app.workers.jobs import content_pipeline as job_mod

    supabase = MagicMock()

    async def status_side_effect(
        sb: MagicMock, lesson_id: str, status: str, error: str | None = None
    ) -> None:
        if status == "failed":
            # Second cancel delivered mid-shield (worker hard-shutdown).
            raise asyncio.CancelledError

    status_mock = AsyncMock(side_effect=status_side_effect)

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        patch.object(job_mod, "_update_lesson_status", status_mock),
    ):
        with pytest.raises(asyncio.CancelledError):
            await job_mod.content_pipeline_job({}, "lesson-double-cancel")

    # The shielded 'failed' write was attempted before the re-raise.
    assert any(
        c.args[2:3] == ("failed",) for c in status_mock.await_args_list
    ), f"shielded status write never attempted (calls: {status_mock.await_args_list})"


# Columns that exist on lesson_jobs in the frozen initial schema; its status
# CHECK allows only pending/running/completed/failed.
_LESSON_JOBS_COLUMNS = {
    "job_id", "lesson_id", "status", "last_node", "node_outputs",
    "error", "attempt", "cost_usd", "started_at", "completed_at", "created_at",
}
_LESSON_JOBS_STATUSES = {"pending", "running", "completed", "failed"}


async def test_successful_job_completion_write_is_schema_valid() -> None:
    """Regression (live E2E 2026-07-10): the completion write used to send
    status='ready' + lesson_package/progress_pct — none valid for lesson_jobs —
    so every otherwise-successful run failed at the finish line (PGRST204)."""
    from app.workers.jobs import content_pipeline as job_mod

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"user_id": "u1", "source_file_path": "p", "book_id": "b1"}
    )

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(return_value={}),
        ),
        patch("app.core.redis.get_redis", return_value=MagicMock(publish=AsyncMock())),
        patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock()),
    ):
        result = await job_mod.content_pipeline_job({}, "lesson-ok")

    assert result["lesson_id"] == "lesson-ok"
    update_payloads = [
        c.args[0] for c in supabase.table.return_value.update.call_args_list
    ]
    completion = [p for p in update_payloads if p.get("status") == "completed"]
    assert completion, f"no status='completed' write (payloads: {update_payloads})"
    for payload in update_payloads:
        illegal = set(payload) - _LESSON_JOBS_COLUMNS
        assert not illegal, f"write uses nonexistent lesson_jobs columns: {illegal}"
        if "status" in payload:
            assert payload["status"] in _LESSON_JOBS_STATUSES, payload["status"]
    assert "completed_at" in completion[0]


@pytest.mark.parametrize(
    ("exc", "reraises", "error_prefix"),
    [
        pytest.param(
            RuntimeError("Lesson x exceeded cost ceiling at $3.1000 — pipeline aborted"),
            False,
            "cost_ceiling_exceeded:",
            id="cost-ceiling",
        ),
        pytest.param(RuntimeError("node exploded"), True, None, id="runtime-error"),
        pytest.param(ValueError("generic failure"), True, None, id="generic-exception"),
    ],
)
async def test_failure_paths_write_schema_valid_status(
    exc: Exception, reraises: bool, error_prefix: str | None
) -> None:
    """Every _update_lesson_status call site must use a status the lesson_jobs
    CHECK accepts. Regression: the cost-ceiling path used to write the illegal
    'cost_limit_exceeded' — silently rejected, row stuck at 'running' forever.
    Full downshift-and-complete ceiling behavior is S2-13; until then the path
    records 'failed' with a distinguishing error prefix and does NOT retry."""
    from app.workers.jobs import content_pipeline as job_mod

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"user_id": "u1", "source_file_path": "p", "book_id": "b1"}
    )

    with (
        patch("app.core.db.get_supabase", return_value=supabase),
        patch(
            "app.modules.content.pipeline.graph.run_pipeline",
            new=AsyncMock(side_effect=exc),
        ),
    ):
        if reraises:
            with pytest.raises(type(exc)):  # ARQ retry path
                await job_mod.content_pipeline_job({}, "lesson-fail")
        else:
            # Cost ceiling: early return, no ARQ retry.
            result = await job_mod.content_pipeline_job({}, "lesson-fail")
            assert result["status"] == "failed"
            assert result["error"].startswith(error_prefix)

    update_payloads = [
        c.args[0] for c in supabase.table.return_value.update.call_args_list
    ]
    failed = [p for p in update_payloads if p.get("status") == "failed"]
    assert failed, f"no status='failed' write (payloads: {update_payloads})"
    for payload in update_payloads:
        illegal = set(payload) - _LESSON_JOBS_COLUMNS
        assert not illegal, f"write uses nonexistent lesson_jobs columns: {illegal}"
        if "status" in payload:
            assert payload["status"] in _LESSON_JOBS_STATUSES, payload["status"]
    if error_prefix is not None:
        assert failed[0]["error"].startswith(error_prefix), failed[0]["error"]
