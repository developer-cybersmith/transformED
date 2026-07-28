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
