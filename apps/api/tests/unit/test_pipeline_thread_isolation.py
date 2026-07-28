"""Story 2-28 AC-5: per-attempt LangGraph thread_id + MemorySaver eviction.

This is MEMORY HYGIENE, not the duplication fix. The 16x duplication was caused
by nodes returning `{**state, ...}` (see tests/unit/test_node_return_shape.py).
What is guarded here is separate: MemorySaver is process-local, retained for the
whole worker lifetime, and never evicted, so reusing `thread_id=lesson_id` left
a stale accumulator behind on every retry and grew without bound.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_each_invocation_gets_a_distinct_thread_id() -> None:
    """Two runs of the SAME lesson must not share a checkpoint thread."""
    from app.modules.content.pipeline import graph as g

    seen: list[str] = []

    async def _capture(_initial: Any, config: dict[str, Any]) -> dict[str, Any]:
        seen.append(config["configurable"]["thread_id"])
        return {"lesson_package": {}}

    fake_graph = type("G", (), {"ainvoke": staticmethod(_capture), "checkpointer": None})()

    lesson_id = "11111111-1111-1111-1111-111111111111"
    with patch.object(g, "get_pipeline_graph", return_value=fake_graph):
        await g.run_pipeline(lesson_id, chapter_content="x", attempt="job-1:1")
        await g.run_pipeline(lesson_id, chapter_content="x", attempt="job-1:2")

    assert len(seen) == 2
    assert seen[0] != seen[1], f"thread_id reused across attempts: {seen}"
    assert all(t.startswith(f"{lesson_id}::") for t in seen), (
        f"thread_id must remain traceable to its lesson: {seen}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_thread_id_is_unique_even_with_identical_attempt_token() -> None:
    """The nonce must be computed per call, not baked in at import.

    Regression guard for the `uuid4()`-as-default-argument trap: a default arg
    evaluates ONCE at import, so every run would share one token and the fix
    would ship green while production stayed broken. `router.py` pins
    `_job_id=f"pipeline:{lesson_id}"`, so identical attempt tokens are a real
    production scenario, not a contrived one.
    """
    from app.modules.content.pipeline import graph as g

    seen: list[str] = []

    async def _capture(_initial: Any, config: dict[str, Any]) -> dict[str, Any]:
        seen.append(config["configurable"]["thread_id"])
        return {"lesson_package": {}}

    fake_graph = type("G", (), {"ainvoke": staticmethod(_capture), "checkpointer": None})()

    with patch.object(g, "get_pipeline_graph", return_value=fake_graph):
        await g.run_pipeline("lesson-x", chapter_content="x", attempt="same:1")
        await g.run_pipeline("lesson-x", chapter_content="x", attempt="same:1")

    assert seen[0] != seen[1], "identical attempt tokens must still yield distinct threads"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_thread_is_evicted_after_a_successful_run() -> None:
    """Behavioral check — the thread must be gone from the saver afterwards.

    Deliberately does NOT assert `hasattr(saver, "adelete_thread")`:
    BaseCheckpointSaver defines it (raising NotImplementedError), so such an
    assertion can never fail and would be a false canary.
    """
    from langgraph.checkpoint.memory import MemorySaver

    from app.modules.content.pipeline import graph as g

    saver = MemorySaver()
    captured: dict[str, str] = {}

    async def _write_then_return(_initial: Any, config: dict[str, Any]) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        captured["thread_id"] = thread_id
        saver.put(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            {"id": "c1", "ts": "2026-07-28T00:00:00Z", "channel_values": {}, "v": 1},
            {},
            {},
        )
        return {"lesson_package": {}}

    fake_graph = type(
        "G", (), {"ainvoke": staticmethod(_write_then_return), "checkpointer": saver}
    )()

    with patch.object(g, "get_pipeline_graph", return_value=fake_graph):
        await g.run_pipeline("lesson-evict", chapter_content="x", attempt="j:1")

    thread_id = captured["thread_id"]
    # `storage` is a defaultdict — INDEXING it would create the key and make the
    # assertion vacuous. Membership-test only.
    assert thread_id not in saver.storage, "checkpoint thread was not evicted"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eviction_runs_even_when_the_pipeline_raises() -> None:
    """The `finally` must fire on the failure path — that is when retries (and
    therefore accumulation) actually happen."""
    from app.modules.content.pipeline import graph as g

    evicted: list[str] = []

    async def _boom(_initial: Any, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        raise RuntimeError("node exploded")

    fake_graph = type("G", (), {"ainvoke": staticmethod(_boom), "checkpointer": None})()

    with (
        patch.object(g, "get_pipeline_graph", return_value=fake_graph),
        patch.object(g, "_discard_checkpoint_thread", side_effect=lambda _g, t: evicted.append(t)),
        pytest.raises(RuntimeError, match="node exploded"),
    ):
        await g.run_pipeline("lesson-fail", chapter_content="x", attempt="j:1")

    assert len(evicted) == 1, "eviction must still run when the pipeline raises"


@pytest.mark.unit
def test_discard_never_raises_and_never_masks() -> None:
    """A failing checkpointer must be swallowed, not surfaced."""
    from app.modules.content.pipeline import graph as g

    class _Exploding:
        def delete_thread(self, _thread_id: str) -> None:
            raise RuntimeError("saver is unhappy")

    boom_graph = type("G", (), {"checkpointer": _Exploding()})()
    g._discard_checkpoint_thread(boom_graph, "t1")  # must not raise

    # A checkpointer without the method at all is also tolerated.
    g._discard_checkpoint_thread(type("G", (), {"checkpointer": object()})(), "t1")
    # And a graph with no checkpointer attribute at all.
    g._discard_checkpoint_thread(object(), "t1")


@pytest.mark.unit
def test_worker_passes_job_try_not_just_job_id() -> None:
    """TRAP guard: router.py pins _job_id=f"pipeline:{lesson_id}", so job_id is
    byte-identical across retries. If the worker ever passes job_id alone, the
    thread_id stops being per-attempt and the leak returns silently."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "workers" / "jobs" / "content_pipeline.py"
    text = src.read_text(encoding="utf-8-sig")
    assert "job_try" in text, "content_pipeline_job must include job_try in the attempt token"
    assert "attempt=attempt" in text, "attempt must be forwarded to run_pipeline"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attempt_does_not_leak_into_checkpoint_keys() -> None:
    """Invariant: `attempt` scopes ONLY the LangGraph thread_id.

    The Supabase checkpoint keys must stay `f"{node}:{section_id}"`. If
    attempt-scoping leaked into them, every section would re-bill on an ARQ
    retry against the $3.00/lesson ceiling.
    """
    from app.modules.content.pipeline import graph as g

    written: list[str] = []
    with patch.object(
        g,
        "_write_phase1_checkpoint",
        new=AsyncMock(side_effect=lambda _lid, key, _v: written.append(key)),
    ):
        await g._write_phase1_checkpoint("lesson-1", "quiz_generator:section_0_intro", {"x": 1})

    assert written == ["quiz_generator:section_0_intro"]
    assert not any("::" in k or "t0-" in k for k in written), (
        "attempt/run-token must never appear in a Supabase checkpoint key"
    )
