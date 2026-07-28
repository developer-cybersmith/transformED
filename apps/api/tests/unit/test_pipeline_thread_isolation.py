"""Story 2-28 AC-5: per-attempt LangGraph thread_id + MemorySaver eviction.

This is MEMORY HYGIENE, not the duplication fix. The 16x duplication was caused
by nodes returning `{**state, ...}` (see tests/unit/test_node_return_shape.py).
What is guarded here is separate: MemorySaver is process-local, retained for the
whole worker lifetime, and never evicted, so reusing `thread_id=lesson_id` left
a stale accumulator behind on every retry and grew without bound.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Matches the run-token shape run_pipeline builds: "t<attempt>-<8 hex>".
_RUN_TOKEN_RE = re.compile(r"t.*-[0-9a-f]{8}")


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
@pytest.mark.asyncio
async def test_worker_passes_a_distinct_attempt_per_arq_try() -> None:
    """TRAP guard, BEHAVIORAL: router.py pins _job_id=f"pipeline:{lesson_id}",
    so job_id is byte-identical across retries — only job_try varies.

    The previous version of this test grepped the source for the string
    "job_try", which the comment block above the code also contains, so it
    passed even with the implementation reverted (proven by mutation during
    the Story 2-28 review). Assert on the forwarded value instead.
    """
    from app.workers.jobs import content_pipeline as cp

    captured: list[str] = []

    async def _spy(**kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs.get("attempt", "<missing>"))
        return {}

    # Same pinned job_id both times — exactly what ARQ does on a retry.
    ctx_try1 = {"job_id": "pipeline:lesson-1", "job_try": 1}
    ctx_try2 = {"job_id": "pipeline:lesson-1", "job_try": 2}

    # content_pipeline_job imports its dependencies lazily inside the function
    # body, so they are not module attributes — patch them at their source.
    sb = MagicMock()
    row = {
        "lesson_id": "lesson-1",
        "source_pdf_path": "p.pdf",
        "lessons": {"user_id": "u1", "book_id": "b1", "tier": "T2"},
    }
    _chain = sb.table.return_value.select.return_value.eq.return_value
    _chain.maybe_single.return_value.execute.return_value.data = row
    _chain.single.return_value.execute.return_value.data = row

    with (
        patch("app.modules.content.pipeline.graph.run_pipeline", new=_spy),
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.core.cost_tracker.clear_lesson_cost", new=AsyncMock(return_value=None)),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
    ):
        for ctx in (ctx_try1, ctx_try2):
            try:
                await cp.content_pipeline_job(ctx, "lesson-1")
            except Exception:  # noqa: BLE001, S110 — only the attempt kwarg matters here
                pass

    assert len(captured) == 2, f"run_pipeline not reached on both tries: {captured}"
    assert captured[0] != captured[1], (
        f"attempt must differ across ARQ tries, got {captured} — job_id alone is "
        "pinned by router.py and cannot uniquify"
    )
    assert all("<missing>" != c for c in captured), "attempt kwarg was not forwarded at all"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attempt_does_not_leak_into_checkpoint_keys() -> None:
    """Invariant: `attempt` scopes ONLY the LangGraph thread_id.

    The Supabase checkpoint keys must stay `f"{node}:{section_id}"`. If
    attempt-scoping leaked into them, every section would re-bill on an ARQ
    retry against the $3.00/lesson ceiling — the trap AC-5 calls out.

    The previous version of this test patched `_write_phase1_checkpoint` and
    then CALLED THE MOCK, asserting the mock recorded what it was handed. No
    production code ran (proven circular during the Story 2-28 review). This
    version drives a REAL Phase-1 node and asserts on the key it actually
    constructs.
    """
    from app.modules.content.pipeline import graph as g

    observed: list[str] = []

    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}

    provider = MagicMock()
    provider.complete_structured = AsyncMock(
        return_value=g._SegmentSummaryLLM(summary="a summary of this section")
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(
            g,
            "_write_phase1_checkpoint",
            new=AsyncMock(side_effect=lambda _lid, key, _v: observed.append(key)),
        ),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        await g.summarise_segment_node(  # type: ignore[arg-type]
            {
                "lesson_id": "lesson-1",
                "_section": {"title": "Intro", "body": "Some body text for the section."},
                "_section_index": 0,
                "tier": "T1",
            }
        )

    assert observed, "the real node never wrote a checkpoint — test would be vacuous"
    for key in observed:
        assert key.startswith("summarise_segment:"), f"unexpected checkpoint key shape: {key}"
        assert "::" not in key, f"thread-id separator leaked into checkpoint key: {key}"
        assert not _RUN_TOKEN_RE.search(key), f"run token leaked into checkpoint key: {key}"
