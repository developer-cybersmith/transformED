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

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings


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


def _requested_count(prompt: str) -> int:
    """Parse the question count out of quiz_generator's rendered prompt."""
    m = re.search(r"Write (\d+) to (\d+) multiple-choice questions", prompt)
    assert m, f"could not find the count instruction in prompt: {prompt[:200]}"
    assert m.group(1) == m.group(2), "S5-4 requests an exact count, not a band"
    return int(m.group(1))


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
@pytest.mark.parametrize(("tier", "lesson_total"), [("T1", 16), ("T2", 10), ("T3", 5)])
async def test_tier_reaches_quiz_generator_through_the_fan_out(
    tier: str, lesson_total: int
) -> None:
    """End-to-end for AC-3's own promise: 'A T1 lesson must produce a T1
    quiz-count band.'

    Drives the REAL fan-out, then feeds a real Send payload into the REAL
    quiz_generator_node, and asserts the count it requests came from the tier.
    Existing tier tests bypass the fan-out entirely, so only this path proves
    the plumbing.

    Story S5-4 rewrote the expectation (AC22): the per-segment band (T1 3-5,
    T2 2-3, T3 1-2) is gone, because a per-segment count multiplies by segment
    count — 15 sections x T1's band was 45-75 questions in a lesson advertised
    as 45 minutes TOTAL. The budget is now lesson-level and allocated across
    sections by the fan-out, so the invariant worth pinning is the LESSON
    total, not a per-section band. The plumbing property this file exists to
    guard is unchanged and still asserted: the tier must survive the fan-out.
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
                for n in range(_requested_count(captured_prompt[-1]))
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
    requested = _requested_count(captured_prompt[0])

    # This section's allocated share, recomputed from the real allocator over
    # the same two sections the fan-out saw — not a hardcoded number that would
    # drift from the budget table.
    expected_per_section = g._quiz_budget_per_segment(
        tier,
        [float(len(s["body"])) for s in _state(tier)["sections"]],
        get_settings().quiz_seconds_per_question,
    )
    assert sum(expected_per_section) == lesson_total, (
        f"tier {tier} should budget {lesson_total} questions for the whole lesson"
    )
    assert requested == expected_per_section[0], (
        f"tier {tier} section 0 should request {expected_per_section[0]} questions; "
        f"prompt was: {captured_prompt[0][:400]}"
    )
    assert len(result["quiz_questions"]) == requested


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


# ── Issue #236: the post-planner narration fan-out needs the same guard ─────


def _state_with_plan(tier: str) -> dict[str, Any]:
    sections = [
        {"title": "Intro", "body": "Body one."},
        {"title": "Next", "body": "Body two."},
    ]
    from app.modules.content.pipeline import graph as g

    plan_segments = [
        {
            "segment_id": g._derive_section_id(s, i),
            "title": s["title"],
            "summary": "s",
            "duration_min": 5.0,
            "slide_budget": {"min": 1, "max": 3},
            "continuity_notes": "" if i == 0 else "reiterate the intro",
        }
        for i, s in enumerate(sections)
    ]
    return {
        "lesson_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "u1",
        "book_id": "b1",
        "tier": tier,
        "sections": sections,
        "lesson_plan": {"segments": plan_segments},
    }


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["T1", "T2", "T3"])
async def test_narration_fan_out_payload_carries_tier(tier: str) -> None:
    """Same D2-class trap the issue names by number: a new Send() payload
    must not silently drop a load-bearing key."""
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_narration_after_planning(_state_with_plan(tier))  # type: ignore[arg-type]

    assert sends, "post-planner fan-out produced no dispatches — test would be vacuous"
    for send in sends:
        assert send.arg["tier"] == tier


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_payload_carries_every_declared_key_plus_plan_segment() -> None:
    """Guards _FAN_OUT_STATE_KEYS plus the new per-dispatch keys
    (_section/_section_index/_plan_segment) this router adds."""
    from app.modules.content.pipeline import graph as g

    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_narration_after_planning(_state_with_plan("T1"))  # type: ignore[arg-type]

    for send in sends:
        assert send.node == "narration_generator"
        missing = [k for k in g._FAN_OUT_STATE_KEYS if k not in send.arg]
        assert not missing, f"{send.node} payload missing declared keys: {missing}"
        for k in ("_section", "_section_index", "_total_sections", "_plan_segment"):
            assert k in send.arg, f"{send.node} payload missing {k}"
        plan_segment = send.arg["_plan_segment"]
        # S5-4 (AC9) adds duration_min: this segment's share of the lesson's
    # narration budget, which narration_generator_node turns into an explicit
    # word target. It rides _plan_segment rather than _FAN_OUT_STATE_KEYS
    # precisely so no new fan-out key is introduced.
    assert set(plan_segment) == {"segment_id", "title", "continuity_notes", "duration_min"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_reconstructs_correct_section_per_segment() -> None:
    """Each dispatch's _section/_section_index must match the segment_id it
    was built for, reconstructed via _derive_section_id — not assumed to line
    up positionally (see _fan_out_narration_after_planning's own docstring on
    why state["sections"] can't just be zipped against lesson_plan.segments)."""
    from app.modules.content.pipeline import graph as g

    state = _state_with_plan("T2")
    with patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)):
        sends = await g._fan_out_narration_after_planning(state)  # type: ignore[arg-type]

    for send in sends:
        expected_id = g._derive_section_id(send.arg["_section"], send.arg["_section_index"])
        assert expected_id == send.arg["_plan_segment"]["segment_id"]


# ── Test Coverage review finding (2026-09-21): _fan_out_narration_after_planning
# had zero coverage of its guard paths, unlike TestAC7CostCeiling's thorough
# coverage of the same guard shapes on _fan_out_phase1_economy_nodes. ─────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_empty_plan_segments_raises() -> None:
    from app.modules.content.pipeline import graph as g

    state = _state_with_plan("T1")
    state["lesson_plan"] = {"segments": []}
    with pytest.raises(RuntimeError, match="zero segments"):
        await g._fan_out_narration_after_planning(state)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_missing_lesson_id_raises() -> None:
    from app.modules.content.pipeline import graph as g

    state = _state_with_plan("T1")
    del state["lesson_id"]
    with pytest.raises(RuntimeError, match="missing lesson_id"):
        await g._fan_out_narration_after_planning(state)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_does_not_check_ceiling_at_all() -> None:
    """Review finding (2026-09-21, PR #237, CONFIRMED HIGH): this router used
    to full-abort the WHOLE lesson (RuntimeError) on a cost-ceiling breach —
    but by this point lesson_planner + slide_generator (both premium GPT-4o)
    have already spent real money, so aborting here discarded already-paid-
    for work, violating CLAUDE.md's "downshift... complete lesson" cost-
    ceiling policy. Fixed by removing the router-level gate entirely (mirrors
    tts_node/image_generator_node, neither of which has one either) — the
    per-dispatch check moved into narration_generator_node itself (see
    TestAC6NarrationGenerator's cost-ceiling test in test_phase1_economy_nodes.py).
    This test proves the router dispatches unconditionally regardless of
    check_ceiling's mocked return value — including when check_ceiling itself
    raises, which must not propagate either, since it's never even called."""
    from app.modules.content.pipeline import graph as g

    check_ceiling_mock = AsyncMock(side_effect=AssertionError("router must not call check_ceiling"))
    with patch("app.core.cost_tracker.check_ceiling", new=check_ceiling_mock):
        sends = await g._fan_out_narration_after_planning(_state_with_plan("T1"))  # type: ignore[arg-type]

    assert sends, "must dispatch unconditionally — no router-level cost-ceiling gate"
    check_ceiling_mock.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narration_fan_out_unmatched_segment_id_raises() -> None:
    """Defensive/unreachable-in-practice branch (lesson_planner_node's own
    AC-6 guard already rejects an unknown segment_id before lesson_plan is
    ever written) — still must fail loudly, not dispatch narration with no
    section body to work from, if ever reached."""
    from app.modules.content.pipeline import graph as g

    state = _state_with_plan("T1")
    state["lesson_plan"]["segments"][0]["segment_id"] = "does_not_exist_in_sections"
    with pytest.raises(RuntimeError, match="has no matching entry"):
        await g._fan_out_narration_after_planning(state)  # type: ignore[arg-type]
