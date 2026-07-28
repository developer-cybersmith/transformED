"""Story 2-28 AC-3: the Send() fan-out payload must carry every key Phase-1 needs.

Why this file exists
--------------------
`_fan_out_phase1_economy_nodes` builds each dispatch's payload from
`_FAN_OUT_STATE_KEYS`. A `Send()` payload **replaces** state for the dispatched
node — it is not merged — so any key absent from that tuple silently resolves
to its `.get()` default inside all six Phase-1 nodes.

`"tier"` was missing. Every Phase-1 node therefore read `_DEFAULT_TIER` ("T2")
regardless of the lesson's real tier, silently disabling the S2-LM3/LM4/LM5
tier bands for every T1 and T3 lesson. It was found by eyeball, not by a test.

Crucially, the existing tier suites do NOT catch this: they call the nodes
directly with `_state(tier="T1")`, injecting the very key the fan-out was
failing to deliver. That is the false-confidence pattern that let the bug ship
in the first place — so the guard has to be at the fan-out boundary.

Verified during the Story 2-28 review: deleting `"tier"` from the tuple left
the entire suite green (641 passed) before these tests existed.
"""

from __future__ import annotations

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


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
async def test_fan_out_payload_carries_tier(tier: str) -> None:
    """Every Send() payload must carry the lesson's real tier."""
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state(tier))  # type: ignore[arg-type]

    assert sends, "fan-out produced no dispatches — test would be vacuous"
    for send in sends:
        assert send.arg["tier"] == tier, (
            f"Send() payload for {send.node} carries tier={send.arg.get('tier')!r}, "
            f"expected {tier!r}. Send REPLACES state, so a missing key silently "
            "becomes the node's .get() default (Story 2-28 AC-3)."
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fan_out_payload_carries_every_declared_key() -> None:
    """Guard the tuple itself, not just `tier`.

    The next load-bearing key to be forgotten should fail here rather than
    degrade silently in production.
    """
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state("T1"))  # type: ignore[arg-type]

    for send in sends:
        missing = [k for k in g._FAN_OUT_STATE_KEYS if k not in send.arg]
        assert not missing, f"{send.node} payload missing declared keys: {missing}"
        # Per-dispatch keys the nodes also rely on.
        for k in ("_section", "_section_index", "_total_sections"):
            assert k in send.arg, f"{send.node} payload missing {k}"


@pytest.mark.unit
def test_tier_is_declared_in_fan_out_state_keys() -> None:
    """Pin the regression directly: `tier` must stay in the allowlist."""
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS

    assert "tier" in _FAN_OUT_STATE_KEYS, (
        "tier dropped from _FAN_OUT_STATE_KEYS — every T1/T3 lesson silently "
        "reverts to the T2 band (Story 2-28 AC-3)"
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(("tier", "lo", "hi"), [("T1", 3, 5), ("T2", 2, 3), ("T3", 1, 2)])
async def test_tier_reaches_quiz_generator_through_the_fan_out(tier: str, lo: int, hi: int) -> None:
    """End-to-end for AC-3's own promise: 'A T1 lesson must produce a T1
    quiz-count band.'

    Drives the REAL fan-out, then feeds a real Send payload into the REAL
    quiz_generator_node, and asserts the band it requests matches the tier.
    Existing tier tests bypass the fan-out entirely, so only this path proves
    the plumbing.
    """
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state(tier))  # type: ignore[arg-type]

    quiz_send = next(s for s in sends if s.node == "quiz_generator")

    sb = MagicMock()
    _chain = sb.table.return_value.select.return_value.eq.return_value
    _chain.single.return_value.execute.return_value.data = {"node_outputs": {}}

    captured_prompt: list[str] = []

    async def _capture(messages: list[dict[str, str]], _model: str, _fmt: type) -> Any:
        captured_prompt.append(" ".join(m["content"] for m in messages))
        return g._QuizBatchLLM(
            questions=[
                g._QuizQuestionLLM(
                    question=f"Q{n}?",
                    options=[f"a{n}", f"b{n}", f"c{n}", f"d{n}"],
                    correct_index=0,
                    explanation="because",
                    difficulty="medium",
                )
                for n in range(lo)
            ]
        )

    provider = MagicMock()
    provider.complete_structured = AsyncMock(side_effect=_capture)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(g, "_write_phase1_checkpoint", new=AsyncMock(return_value=None)),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.quiz_generator_node(quiz_send.arg)  # type: ignore[arg-type]

    assert captured_prompt, "quiz_generator never called the LLM — test vacuous"
    assert f"{lo} to {hi}" in captured_prompt[0], (
        f"tier {tier} should request the {lo}-{hi} band; prompt was: {captured_prompt[0][:400]}"
    )
    assert lo <= len(result["quiz_questions"]) <= hi


# ── Story 2-31 AC-3: cached Phase-1 work must match the lesson's tier ────────


def _cached_quiz_batch(section_id: str, n: int) -> dict[str, Any]:
    """A checkpoint batch of *n* structurally-valid questions."""
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


def _sb_with_checkpoint(key: str, cached: dict[str, Any]) -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    payload = {"node_outputs": {key: cached}}
    chain.maybe_single.return_value.execute.return_value.data = payload
    chain.single.return_value.execute.return_value.data = payload
    return sb


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oversized_cache_from_a_higher_band_is_rejected() -> None:
    """Story 2-28 made `tier` actually reach this node, making a latent hazard
    reachable: a lesson whose Phase 1 ran BEFORE that deploy holds a checkpoint
    sized to a different band, and an ARQ retry would return it verbatim —
    shipping wrong-tier content while the logs show the tier fix working.

    Guarded on n_max ONLY. `count > n_max` is unambiguous: the write path
    truncates to n_max, so a bigger batch can only be from a higher band.
    `count < n_min` is NOT guarded — the write path deliberately keeps a short
    batch when the LLM underproduces, so rejecting it would re-bill that
    section on every retry. See the comment at the guard for the residual gap.
    """
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state("T3"))  # type: ignore[arg-type]
    quiz_send = next(s for s in sends if s.node == "quiz_generator")
    section_id = g._derive_section_id(quiz_send.arg["_section"], quiz_send.arg["_section_index"])

    # 5 questions == a T1-sized batch; T3's band is 1-2, so this is impossible
    # to have been written for a T3 lesson.
    sb = _sb_with_checkpoint(f"quiz_generator:{section_id}", _cached_quiz_batch(section_id, 5))

    provider = MagicMock()
    provider.complete_structured = AsyncMock(
        return_value=g._QuizBatchLLM(
            questions=[
                g._QuizQuestionLLM(
                    question=f"fresh {n}",
                    options=[f"a{n}", f"b{n}", f"c{n}", f"d{n}"],
                    correct_index=0,
                    explanation="because",
                    difficulty="medium",
                )
                for n in range(2)
            ]
        )
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(g, "_write_phase1_checkpoint", new=AsyncMock(return_value=None)),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.quiz_generator_node(quiz_send.arg)  # type: ignore[arg-type]

    assert provider.complete_structured.await_count == 1, (
        "an oversized (higher-band) cache must be a MISS and regenerate"
    )
    assert len(result["quiz_questions"]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_cache_is_still_reused_no_respend() -> None:
    """The n_min side must NOT be guarded: the write path keeps a short batch
    when the LLM underproduces, so rejecting it would re-bill on every retry."""
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state("T1"))  # type: ignore[arg-type]
    quiz_send = next(s for s in sends if s.node == "quiz_generator")
    section_id = g._derive_section_id(quiz_send.arg["_section"], quiz_send.arg["_section_index"])

    # 2 questions is BELOW T1's floor of 3 — a legitimate underproduction.
    sb = _sb_with_checkpoint(f"quiz_generator:{section_id}", _cached_quiz_batch(section_id, 2))
    provider = MagicMock()
    provider.complete_structured = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.quiz_generator_node(quiz_send.arg)  # type: ignore[arg-type]

    provider.complete_structured.assert_not_awaited()
    assert len(result["quiz_questions"]) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_in_band_cache_is_still_reused_no_respend() -> None:
    """The guard must not defeat the checkpoint's whole purpose: a cache that
    DOES match the tier band must still be reused, with zero LLM spend."""
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_phase1_economy_nodes(_state("T1"))  # type: ignore[arg-type]
    quiz_send = next(s for s in sends if s.node == "quiz_generator")
    section_id = g._derive_section_id(quiz_send.arg["_section"], quiz_send.arg["_section_index"])

    # 4 questions is inside T1's 3-5 band.
    sb = _sb_with_checkpoint(f"quiz_generator:{section_id}", _cached_quiz_batch(section_id, 4))
    provider = MagicMock()
    provider.complete_structured = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch.object(g, "_increment_phase1_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.quiz_generator_node(quiz_send.arg)  # type: ignore[arg-type]

    provider.complete_structured.assert_not_awaited()
    assert len(result["quiz_questions"]) == 4
