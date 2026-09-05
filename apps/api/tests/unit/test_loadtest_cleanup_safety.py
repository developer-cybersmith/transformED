"""Regression test for D155, found live on load-test run #10 (2026-09-04):
`_run_full`'s cleanup used to fire as soon as `run_phase_b`'s OWN polling
gave up on a lesson -- which can happen EARLY (see
`phase_b_generate._poll_one_lesson`'s 401/403/404 fail-fast branch) if the
disposable user's own bearer token expires mid-poll, even though the real
ARQ pipeline job for that lesson may still be genuinely running. Cleanup
then deleted the owning disposable user while its job was still in flight,
and the job crashed on its now-cascade-deleted `lesson_jobs` row partway
through real, paid generation work.

`_wait_for_lessons_terminal` checks the real `lessons` table directly via
the service-role REST API (never a disposable user's own token, which is
exactly what can expire) before cleanup is allowed to proceed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx


def _make_lessons_response(rows: list[dict[str, str]]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = rows
    return resp


async def test_wait_for_lessons_terminal_returns_once_all_report_ready() -> None:
    from tests.loadtest.run import _wait_for_lessons_terminal

    lesson_ids = ["aaa", "bbb"]
    mock_client = AsyncMock()
    mock_client.get.return_value = _make_lessons_response(
        [{"lesson_id": "aaa", "status": "ready"}, {"lesson_id": "bbb", "status": "failed"}]
    )

    with (
        patch("tests.loadtest.run._require_env", return_value="dummy"),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        result = await _wait_for_lessons_terminal(lesson_ids, poll_interval_s=0.01, max_wait_s=1.0)

    assert result == {"aaa": "ready", "bbb": "failed"}
    # Only needed one real check -- both were already terminal.
    assert mock_client.get.call_count == 1


async def test_wait_for_lessons_terminal_keeps_polling_until_the_straggler_finishes() -> None:
    from tests.loadtest.run import _wait_for_lessons_terminal

    lesson_ids = ["aaa", "bbb"]
    responses = [
        _make_lessons_response(
            [{"lesson_id": "aaa", "status": "ready"}, {"lesson_id": "bbb", "status": "generating"}]
        ),
        _make_lessons_response([{"lesson_id": "bbb", "status": "ready"}]),
    ]
    mock_client = AsyncMock()
    mock_client.get.side_effect = responses

    with (
        patch("tests.loadtest.run._require_env", return_value="dummy"),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        result = await _wait_for_lessons_terminal(lesson_ids, poll_interval_s=0.01, max_wait_s=5.0)

    assert result == {"aaa": "ready", "bbb": "ready"}
    assert mock_client.get.call_count == 2
    # The second check must only re-query the still-outstanding lesson, not
    # re-check one already confirmed terminal.
    second_call_params = mock_client.get.call_args_list[1].kwargs["params"]
    assert "aaa" not in second_call_params["lesson_id"]
    assert "bbb" in second_call_params["lesson_id"]


async def test_wait_for_lessons_terminal_marks_a_genuine_hang_as_timed_out() -> None:
    """A lesson that NEVER reports terminal (a genuine hang, not a token
    expiry artifact) must be reported as 'timed_out' once the hard backstop
    elapses -- proving this function still terminates and surfaces the
    problem rather than blocking cleanup forever."""
    from tests.loadtest.run import _wait_for_lessons_terminal

    mock_client = AsyncMock()
    mock_client.get.return_value = _make_lessons_response(
        [{"lesson_id": "stuck", "status": "generating"}]
    )

    with (
        patch("tests.loadtest.run._require_env", return_value="dummy"),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        result = await _wait_for_lessons_terminal(["stuck"], poll_interval_s=0.01, max_wait_s=0.03)

    assert result == {"stuck": "timed_out"}


async def test_wait_for_lessons_terminal_is_immune_to_a_transient_http_error() -> None:
    """A single dropped/failed poll (network blip, transient 5xx) must not
    crash the wait or falsely mark a lesson terminal -- it just retries."""
    from tests.loadtest.run import _wait_for_lessons_terminal

    mock_client = AsyncMock()
    mock_client.get.side_effect = [
        httpx.ConnectError("boom"),
        _make_lessons_response([{"lesson_id": "aaa", "status": "ready"}]),
    ]

    with (
        patch("tests.loadtest.run._require_env", return_value="dummy"),
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        result = await _wait_for_lessons_terminal(["aaa"], poll_interval_s=0.01, max_wait_s=5.0)

    assert result == {"aaa": "ready"}
    assert mock_client.get.call_count == 2
