"""D116 fix tests — complete_session → dispatch_event("lesson_complete") → ces_final written.

Story 4-6. All tests are @pytest.mark.unit — no DB, no network, no Redis.

Coverage:
- AC4: lesson_complete routes to session_end from ALL FSM states (IDLE, TEACHING,
       INTERVENING, CHECKING_IN, QUIZZING, TEACH_BACK)
- AC3: dispatch_event called exactly once on first complete_session; zero times on retry
       (ended_at already set → early return before dispatch)
- AC5: _finalize_session update payload contains ces_final, NOT ended_at
- AC6: dispatch_event failure inside complete_session does not propagate as HTTP error
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── AC4: route_entry universal lesson_complete guard ───────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_state_value",
    [
        "IDLE",
        "TEACHING",
        "INTERVENING",
        "CHECKING_IN",
        "QUIZZING",
        "TEACH_BACK",
    ],
)
async def test_lesson_complete_routes_to_session_end_from_any_state(
    initial_state_value: str,
) -> None:
    """AC4: lesson_complete ALWAYS routes to session_end regardless of current state."""
    from app.modules.tutor.state_machine.graph import route_entry

    state = {
        "session_id": "test-session",
        "event": "lesson_complete",
        "current_state": initial_state_value,
    }
    result = await route_entry(state)  # type: ignore[arg-type]
    assert result == "session_end", (
        f"lesson_complete from state={initial_state_value!r} routed to {result!r}, "
        "expected 'session_end'. Fix: add universal lesson_complete guard in route_entry."
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_lesson_complete_events_still_use_state_routing() -> None:
    """Sanity: the universal guard only intercepts lesson_complete — other events unchanged."""
    from app.modules.tutor.state_machine.graph import route_entry

    # IDLE + session_start → teaching (original routing preserved)
    state_idle = {"session_id": "s1", "event": "session_start", "current_state": "IDLE"}
    assert await route_entry(state_idle) == "teaching"  # type: ignore[arg-type]

    # TEACHING + distraction_detected → intervening (original routing preserved)
    state_teaching = {
        "session_id": "s2",
        "event": "distraction_detected",
        "current_state": "TEACHING",
    }
    assert await route_entry(state_teaching) == "intervening"  # type: ignore[arg-type]


# ── AC5: _finalize_session update payload must NOT include ended_at ─────────


@pytest.mark.unit
def test_finalize_session_update_payload_has_no_ended_at() -> None:
    """AC5: _finalize_session only writes ces_final, not ended_at.

    Source-level guard: scan _finalize_session for the string 'ended_at' inside
    the .update() call. If found → the double-write bug is still present.
    """
    import ast
    import inspect

    from app.modules.tutor.state_machine import graph as graph_module

    source = inspect.getsource(graph_module._finalize_session)
    tree = ast.parse(source)

    # Walk the AST looking for dict literals or keyword args passed to .update()
    # that contain "ended_at".
    found_in_update = False
    for node in ast.walk(tree):
        # Look for Attribute access '.update' followed by a Call
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "update":
                # Inspect the argument (should be a dict constant)
                for arg in node.args:
                    src_slice = ast.get_source_segment(source, arg) or ""
                    if "ended_at" in src_slice:
                        found_in_update = True

    assert not found_in_update, (
        "_finalize_session still writes 'ended_at' inside .update(). "
        "Remove it — complete_session owns ended_at (D116 fix)."
    )


# ── Helpers for complete_session tests ────────────────────────────────────────


def _make_mock_supabase(ended_at_value: str | None, user_id: str = "uid-1") -> MagicMock:
    """Build a mock supabase client for assessment service tests.

    SELECT with .maybe_single() returns a single dict in .data (not a list).
    UPDATE result is not consumed by complete_session — any MagicMock works.
    """
    mock_supabase = MagicMock()

    select_resp = MagicMock()
    # .maybe_single().execute() → .data is a dict or None, never a list
    select_resp.data = {"session_id": "sid-x", "user_id": user_id, "ended_at": ended_at_value}

    (
        mock_supabase.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute
    ).return_value = select_resp

    # UPDATE result is not consumed — default MagicMock is fine
    return mock_supabase


async def _noop_to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Stand-in for asyncio.to_thread that calls fn() synchronously in tests."""
    return fn()


# ── AC3: complete_session dispatches exactly once (idempotency) ───────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_session_dispatches_lesson_complete_once() -> None:
    """AC3 (first call): complete_session dispatches lesson_complete exactly once."""
    from app.modules.assessment.service import complete_session

    mock_dispatch = AsyncMock(return_value={"current_state": "SESSION_END"})

    with (
        patch("app.modules.assessment.service.asyncio.to_thread", _noop_to_thread),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            mock_dispatch,
        ),
    ):
        result = await complete_session(
            session_id="sid-1",
            user_id="uid-1",
            supabase=_make_mock_supabase(ended_at_value=None, user_id="uid-1"),
        )

    assert "ended_at" in result
    mock_dispatch.assert_called_once_with("sid-1", "lesson_complete")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_session_does_not_dispatch_on_duplicate_call() -> None:
    """AC3 (retry): second call with ended_at already set → early return → no dispatch."""
    from app.modules.assessment.service import complete_session

    mock_dispatch = AsyncMock()

    with (
        patch("app.modules.assessment.service.asyncio.to_thread", _noop_to_thread),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            mock_dispatch,
        ),
    ):
        result = await complete_session(
            session_id="sid-2",
            user_id="uid-2",
            supabase=_make_mock_supabase(
                ended_at_value="2026-08-29T09:00:00+00:00", user_id="uid-2"
            ),
        )

    assert result["ended_at"] == "2026-08-29T09:00:00+00:00"
    mock_dispatch.assert_not_called()


# ── AC6: dispatch failure does not propagate as HTTP error ────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_session_dispatch_failure_does_not_raise_http_error() -> None:
    """AC6: if dispatch_event raises, complete_session still returns 200 (ended_at written)."""
    from fastapi import HTTPException

    from app.modules.assessment.service import complete_session

    failing_dispatch = AsyncMock(side_effect=RuntimeError("Redis connection refused"))

    with (
        patch("app.modules.assessment.service.asyncio.to_thread", _noop_to_thread),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            failing_dispatch,
        ),
    ):
        try:
            result = await complete_session(
                session_id="sid-3",
                user_id="uid-3",
                supabase=_make_mock_supabase(ended_at_value=None, user_id="uid-3"),
            )
            assert "ended_at" in result
        except HTTPException as exc:
            pytest.fail(
                f"complete_session raised HTTPException (status={exc.status_code}) "
                "when dispatch_event failed — AC6 requires graceful degradation."
            )
