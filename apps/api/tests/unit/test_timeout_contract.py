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
    env = {**os.environ, "ARQ_JOB_TIMEOUT_S": "1234"}
    code = (
        "import sys; from app.workers.main import WorkerSettings; "
        "sys.exit(0 if WorkerSettings.job_timeout == 1234 else 1)"
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
        f"WorkerSettings.job_timeout did not track ARQ_JOB_TIMEOUT_S=1234\n{proc.stderr}"
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
