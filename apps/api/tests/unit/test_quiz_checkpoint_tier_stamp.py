"""Story 2-31 review round: the quiz checkpoint carries a TIER STAMP.

Why this file exists
--------------------
Story 2-31 AC-3 shipped a count-based heuristic: reject a cached quiz batch when
`count > _TIER_QUIZ_COUNT_BAND[tier][1]`. The Acceptance Auditor showed that
guard cannot see the hazard AC-3 was written for.

Pre-Story-2-28 checkpoints were ALL written under the wrongly-defaulted `T2`
band, i.e. 2-3 questions. The bands are T1 (3,5), T2 (2,3), T3 (1,2). So for a
T1 lesson, `n_max` is 5 and every stale T2 cache passes cleanly — the exact
"T1 lesson silently ships T2 content" case the AC names. The heuristic fired
only for T3 lessons holding a 3-question cache: one tier of three, one of two
possible stale counts.

The fix is to stamp the generating `tier` into the checkpoint VALUE. That is
exact rather than inferential, and it satisfies both prior invariants:
  - the checkpoint KEY stays `f"{node}:{section_id}"` (Story 2-28 AC-5, guarded
    by test_phase1_checkpoint_idempotency.py), so no re-billing on retry;
  - a same-tier retry is still a free cache hit.

Legacy checkpoints have no stamp, so they keep the `n_max` heuristic as a
fallback — see test_legacy_untiered_cache_still_falls_back_to_the_count_heuristic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _state(tier: str) -> dict[str, Any]:
    return {
        "lesson_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "u1",
        "book_id": "b1",
        "tier": tier,
        "sections": [
            {"title": "Intro", "body": "Body one."},
            {"title": "Next", "body": "Body two."},
        ],
    }


def _cached_quiz_batch(section_id: str, n: int) -> dict[str, Any]:
    """A checkpoint batch of *n* structurally-valid questions, with NO tier stamp."""
    return {
        "segment_id": section_id,
        "questions": [
            {
                "segment_id": section_id,
                "data": {
                    "question_id": f"quiz_{section_id}_{i}",
                    "type": "mcq",
                    "question": f"Q{i}?",
                    "options": [f"a{i}", f"b{i}", f"c{i}", f"d{i}"],
                    "correct_index": 0,
                    "explanation": "because",
                    "difficulty": "medium",
                },
            }
            for i in range(n)
        ],
    }


def _stamped(section_id: str, n: int, tier: str) -> dict[str, Any]:
    batch = _cached_quiz_batch(section_id, n)
    batch["tier"] = tier
    return batch


def _sb_with_checkpoint(key: str, cached: dict[str, Any]) -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    payload = {"node_outputs": {key: cached}}
    chain.maybe_single.return_value.execute.return_value.data = payload
    chain.single.return_value.execute.return_value.data = payload
    return sb


def _batch_llm(g: Any, n: int, label: str = "fresh") -> Any:  # noqa: ANN401
    return g._QuizBatchLLM(
        questions=[
            g._QuizQuestionLLM(
                question=f"{label} {i}",
                options=[f"a{i}", f"b{i}", f"c{i}", f"d{i}"],
                correct_index=0,
                explanation="because",
                difficulty="medium",
            )
            for i in range(n)
        ]
    )


async def _run(
    tier: str,
    build_cached: Callable[[str], dict[str, Any]] | None = None,
    *,
    fresh: Any = None,  # noqa: ANN401
) -> tuple[Any, dict[str, Any], MagicMock, AsyncMock]:
    """Dispatch the fan-out, then run quiz_generator_node.

    Going through `_fan_out_phase1_economy_nodes` rather than hand-building the
    node payload is deliberate: calling the node directly with `_state(tier=...)`
    injects the very key the fan-out is responsible for delivering, which is the
    false-confidence pattern documented in test_fan_out_state_keys.py.

    *build_cached* receives the derived `section_id` and returns the checkpoint
    to seed — the batch has to be keyed off the real section_id, which is only
    known after the fan-out. Pass None for a cold cache.

    Returns (graph_module, node_result, provider_mock, write_mock).
    """
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state(tier))  # type: ignore[arg-type]
    quiz_send = next(s for s in sends if s.node == "quiz_generator")
    section_id = g._derive_section_id(quiz_send.arg["_section"], quiz_send.arg["_section_index"])

    if build_cached is None:
        sb = _sb_with_checkpoint("quiz_generator:some-other-section", {})
    else:
        sb = _sb_with_checkpoint(f"quiz_generator:{section_id}", build_cached(section_id))

    provider = MagicMock()
    provider.complete_structured = AsyncMock(return_value=fresh)
    write_mock = AsyncMock(return_value=None)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(g, "_write_phase1_checkpoint", new=write_mock),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.quiz_generator_node(quiz_send.arg)  # type: ignore[arg-type]

    return g, result, provider, write_mock


# ── The hazard AC-3 named, which the count heuristic could not see ───────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_t2_cache_rejected_for_a_t1_lesson() -> None:
    """A 3-question T2-stamped cache sits INSIDE T1's (3,5) band.

    `count > n_max` is therefore False and the old heuristic reused it verbatim —
    the T1 lesson shipping T2 content while the logs showed the tier fix working.
    The stamp rejects it on provenance instead of size.
    """
    from app.modules.content.pipeline import graph as g

    # Pin the premise: if this fixture ever falls outside T1's band, the test
    # would pass via the count heuristic and prove nothing about the stamp.
    n_min, n_max = g._TIER_QUIZ_COUNT_BAND["T1"]
    assert n_min <= 3 <= n_max, "fixture must be in-band for T1, or this test is vacuous"

    _, result, provider, write_mock = await _run(
        "T1",
        lambda sid: _stamped(sid, 3, "T2"),
        fresh=_batch_llm(g, 4),
    )

    assert provider.complete_structured.await_count == 1, "stale-tier cache must regenerate"
    assert [q["data"]["question"] for q in result["quiz_questions"]] == [
        f"fresh {i}" for i in range(4)
    ]
    assert write_mock.await_args.args[2]["tier"] == "T1", "rewrite must stamp THIS lesson's tier"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_matching_tier_stamp_is_a_free_cache_hit() -> None:
    """The stamp must cost nothing on an ordinary same-tier retry — that was the
    whole objection to tier-scoping the checkpoint KEY."""

    _, result, provider, _ = await _run("T1", lambda sid: _stamped(sid, 4, "T1"))

    provider.complete_structured.assert_not_awaited()
    assert len(result["quiz_questions"]) == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fresh_write_stamps_the_generating_tier() -> None:
    """Without the stamp on write, the read-side check can never fire."""
    from app.modules.content.pipeline import graph as g

    _, _, _, write_mock = await _run("T3", None, fresh=_batch_llm(g, 1))

    written = write_mock.await_args.args[2]
    assert written["tier"] == "T3"
    assert written["segment_id"]
    assert written["questions"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_untiered_cache_still_falls_back_to_the_count_heuristic() -> None:
    """Checkpoints predating this story carry no stamp, so provenance is
    unknowable — the n_max heuristic must still reject an over-band batch."""
    from app.modules.content.pipeline import graph as g

    def _legacy(sid: str) -> dict:
        batch = _cached_quiz_batch(sid, 5)  # T3's band is (1,2)
        assert "tier" not in batch
        return batch

    _, result, provider, _ = await _run("T3", _legacy, fresh=_batch_llm(g, 1))

    assert provider.complete_structured.await_count == 1
    assert [q["data"]["question"] for q in result["quiz_questions"]] == ["fresh 0"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_in_band_cache_is_still_reused_no_respend() -> None:
    """The legacy fallback must not reject on `count < n_min`: the write path
    deliberately KEEPS a short batch when the LLM underproduces (Story 3-28
    AC-8 — 'It does NOT discard the passing questions'), so a below-band count is
    ambiguous, and rejecting it would re-bill on every ARQ retry."""

    _, result, provider, _ = await _run("T1", lambda sid: _cached_quiz_batch(sid, 1))

    provider.complete_structured.assert_not_awaited()
    assert len(result["quiz_questions"]) == 1


# ── Salvage: a rejected cache must never become an EMPTY quiz ────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rejected_cache_plus_failed_regeneration_salvages() -> None:
    """Review blocker. A rejected cache plus one transient LLM failure shipped a
    segment with ZERO questions — strictly worse than the wrong-tier content the
    guard exists to prevent — AND left the stale checkpoint in place, because the
    failure paths write no checkpoint. Every subsequent ARQ retry then
    re-rejected and re-billed, with no cost-ceiling gate in this node.
    """
    from app.modules.content.pipeline import graph as g

    # T1-stamped batch on a T3 lesson: rejected on the stamp. LLM then fails.
    _, result, _, write_mock = await _run("T3", lambda sid: _stamped(sid, 5, "T1"), fresh=None)

    assert result["quiz_questions"], "must salvage, not ship an empty quiz"
    assert len(result["quiz_questions"]) <= g._TIER_QUIZ_COUNT_BAND["T3"][1], (
        "salvage must respect this tier's ceiling"
    )
    write_mock.assert_awaited()
    assert write_mock.await_args.args[2]["tier"] == "T3", (
        "salvaged batch must be re-stamped, or the next retry re-rejects and re-bills"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_cache_and_failed_regeneration_still_degrades_to_empty() -> None:
    """Salvage must not invent questions when there is nothing to salvage —
    Story 3-28 AC-7's degrade-never-crash behaviour is preserved."""
    _, result, _, write_mock = await _run("T2", None, fresh=None)

    assert result["quiz_questions"] == []
    write_mock.assert_not_awaited()
