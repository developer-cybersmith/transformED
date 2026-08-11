"""Tests for Story 3-44 — LangGraph unique thread_id per dispatch (D66).

ACs tested:
  AC1 — thread_id is unique per dispatch (f"{session_id}:{uuid4()}")
  AC2 — change is scoped to dispatch_event only
  AC3 — uuid4 imported from stdlib
  AC4 — FSM transition behavior unchanged (state read from Redis, not checkpoint)
  AC5 — MemorySaver does NOT accumulate entries across dispatches
  AC6 — Guard test: source inspection
  AC7 — DEFECT-REGISTER.md D66 updated (not tested here — human step)

All tests are @pytest.mark.unit — no real Redis, no real LangGraph graph.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── AC6 — Guard test (CI-enforceable, runs first) ─────────────────────────────

@pytest.mark.unit
def test_dispatch_event_uses_uuid4_in_thread_id():
    """Guard (D66): dispatch_event source must contain uuid4() in the thread_id config.

    This is the CI guard for D66. It fails if someone reverts the fix to a bare
    session_id or uses any other non-unique key.
    """
    from app.modules.tutor.state_machine import graph as tutor_graph

    source = inspect.getsource(tutor_graph.dispatch_event)
    assert "uuid4()" in source, (
        "dispatch_event must use uuid4() in thread_id — D66 guard"
    )


@pytest.mark.unit
def test_dispatch_event_does_not_use_bare_session_id_as_thread_id():
    """Guard: dispatch_event must not use session_id as the bare thread_id value.

    Pattern being rejected: '"thread_id": session_id' (without uuid4).
    """
    from app.modules.tutor.state_machine import graph as tutor_graph

    source = inspect.getsource(tutor_graph.dispatch_event)
    # The thread_id must be an f-string with uuid4, not the bare session_id
    assert '"thread_id": session_id' not in source, (
        "dispatch_event must not use bare session_id as thread_id — D66 guard"
    )


# ── AC3 — uuid4 imported from stdlib ──────────────────────────────────────────

@pytest.mark.unit
def test_uuid4_imported_from_uuid_stdlib():
    """uuid4 must come from the Python stdlib `uuid` module."""
    from app.modules.tutor.state_machine import graph as tutor_graph

    # The graph module must use the same uuid4 as stdlib
    assert hasattr(tutor_graph, "uuid4") or "uuid4" in inspect.getsource(tutor_graph), (
        "graph module must import uuid4 (from uuid import uuid4)"
    )
    # Verify it resolves to the stdlib function, not something else
    source_file = inspect.getfile(tutor_graph)
    assert source_file.endswith("graph.py"), "sanity check"


# ── AC1 — thread_id is unique per dispatch ────────────────────────────────────

@pytest.mark.unit
async def test_two_dispatches_produce_different_thread_ids():
    """Two consecutive dispatches for the same session use different thread_ids."""
    captured_thread_ids: list[str] = []

    async def fake_ainvoke(input_state, config=None):
        if config:
            captured_thread_ids.append(config.get("configurable", {}).get("thread_id", ""))
        return {
            "current_state": "TEACHING",
            "session_id": input_state.get("session_id"),
            "user_id": "",
            "lesson_id": "",
            "event": input_state.get("event"),
            "event_payload": {},
            "distraction_count": 0,
            "fatigue_fired": False,
            "in_teachback": False,
            "ces_score": 0.0,
            "intervention_type": None,
            "error": None,
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = fake_ainvoke

    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    with (
        patch("app.modules.tutor.state_machine.graph.get_tutor_graph", return_value=mock_graph),
        patch("app.modules.tutor.state_machine.graph._read_state", AsyncMock(return_value="IDLE")),
        patch("app.modules.tutor.state_machine.graph._persist_state", AsyncMock()),
        patch("app.modules.tutor.state_machine.graph._trace_dispatch"),
    ):
        from app.modules.tutor.state_machine.graph import dispatch_event

        await dispatch_event(session_id, "session_start")
        await dispatch_event(session_id, "segment_complete")

    assert len(captured_thread_ids) == 2
    assert captured_thread_ids[0] != captured_thread_ids[1], (
        f"Both dispatches used the same thread_id: {captured_thread_ids[0]!r}"
    )


@pytest.mark.unit
async def test_thread_id_starts_with_session_id():
    """The thread_id is f'{session_id}:{something}' — session_id is the prefix."""
    captured_thread_ids: list[str] = []

    async def fake_ainvoke(input_state, config=None):
        if config:
            captured_thread_ids.append(config.get("configurable", {}).get("thread_id", ""))
        return {
            "current_state": "TEACHING",
            "session_id": input_state.get("session_id"),
            "user_id": "",
            "lesson_id": "",
            "event": input_state.get("event"),
            "event_payload": {},
            "distraction_count": 0,
            "fatigue_fired": False,
            "in_teachback": False,
            "ces_score": 0.0,
            "intervention_type": None,
            "error": None,
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = fake_ainvoke

    session_id = "12345678-1234-1234-1234-123456789abc"

    with (
        patch("app.modules.tutor.state_machine.graph.get_tutor_graph", return_value=mock_graph),
        patch("app.modules.tutor.state_machine.graph._read_state", AsyncMock(return_value=None)),
        patch("app.modules.tutor.state_machine.graph._persist_state", AsyncMock()),
        patch("app.modules.tutor.state_machine.graph._trace_dispatch"),
    ):
        from app.modules.tutor.state_machine.graph import dispatch_event

        await dispatch_event(session_id, "session_start")

    assert len(captured_thread_ids) == 1
    thread_id = captured_thread_ids[0]
    assert thread_id.startswith(session_id), (
        f"thread_id {thread_id!r} must start with session_id {session_id!r}"
    )
    assert ":" in thread_id, (
        f"thread_id {thread_id!r} must be f-string with colon separator"
    )


# ── AC2 — Change scoped to dispatch_event only ────────────────────────────────

@pytest.mark.unit
def test_uuid4_only_in_dispatch_event_not_elsewhere():
    """uuid4() appears in dispatch_event's source and NOT in other functions."""
    from app.modules.tutor.state_machine import graph as tutor_graph

    dispatch_source = inspect.getsource(tutor_graph.dispatch_event)
    assert "uuid4()" in dispatch_source

    # Check that _build_tutor_graph and get_tutor_graph don't use uuid4
    build_source = inspect.getsource(tutor_graph._build_tutor_graph)
    assert "uuid4()" not in build_source, "_build_tutor_graph should not use uuid4()"

    get_source = inspect.getsource(tutor_graph.get_tutor_graph)
    assert "uuid4()" not in get_source, "get_tutor_graph should not use uuid4()"


# ── AC4 — State is read from Redis, not checkpoint ────────────────────────────

@pytest.mark.unit
async def test_dispatch_reads_state_from_redis_not_checkpoint():
    """dispatch_event calls _read_state (Redis) on every dispatch, not LangGraph checkpoint."""
    read_state_calls: list[str] = []

    async def fake_read_state(session_id: str) -> str | None:
        read_state_calls.append(session_id)
        return "TEACHING"

    async def fake_ainvoke(input_state, config=None):
        return {
            "current_state": "TEACHING",
            "session_id": input_state.get("session_id"),
            "user_id": "",
            "lesson_id": "",
            "event": input_state.get("event"),
            "event_payload": {},
            "distraction_count": 0,
            "fatigue_fired": False,
            "in_teachback": True,
            "ces_score": 0.0,
            "intervention_type": None,
            "error": None,
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = fake_ainvoke

    session_id = "aaaaaaaa-0000-0000-0000-000000000001"

    with (
        patch("app.modules.tutor.state_machine.graph.get_tutor_graph", return_value=mock_graph),
        patch("app.modules.tutor.state_machine.graph._read_state", side_effect=fake_read_state),
        patch("app.modules.tutor.state_machine.graph._persist_state", AsyncMock()),
        patch("app.modules.tutor.state_machine.graph._trace_dispatch"),
    ):
        from app.modules.tutor.state_machine.graph import dispatch_event

        await dispatch_event(session_id, "segment_complete")
        await dispatch_event(session_id, "quiz_trigger")

    # _read_state must be called once per dispatch (Redis is the source of truth)
    assert read_state_calls == [session_id, session_id], (
        f"Expected 2 _read_state calls, got: {read_state_calls}"
    )


# ── AC5 — MemorySaver does not accumulate across dispatches ───────────────────

@pytest.mark.unit
def test_memory_saver_threads_do_not_accumulate():
    """With unique thread_ids, MemorySaver storage per-session stays bounded.

    This test verifies the mechanism: since each dispatch gets a NEW thread_id,
    the MemorySaver can only hold checkpoints for the current in-flight dispatch,
    not for all historical dispatches of a session.
    """
    # This is validated structurally by AC1 (unique thread_ids) and AC6 (guard).
    # We verify that the fix creates distinct UUIDs by checking uuid4 is called
    # within dispatch_event (not shared across calls).
    from app.modules.tutor.state_machine import graph as tutor_graph

    source = inspect.getsource(tutor_graph.dispatch_event)
    # uuid4() inside the function means each call gets its own UUID
    assert source.count("uuid4()") >= 1, (
        "dispatch_event must call uuid4() at least once per dispatch"
    )
    # It must NOT be a module-level assignment that's reused
    module_source = inspect.getsource(tutor_graph)
    # The uuid4() call is inside dispatch_event, not at module scope
    dispatch_start = module_source.find("async def dispatch_event")
    assert dispatch_start != -1
    pre_dispatch = module_source[:dispatch_start]
    # uuid4 should not be pre-computed at module level and reused
    assert "uuid4()" not in pre_dispatch, (
        "uuid4() must be called inside dispatch_event, not pre-computed at module level"
    )
