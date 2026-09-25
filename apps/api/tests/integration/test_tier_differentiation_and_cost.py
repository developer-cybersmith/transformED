"""Learner Mode proof + corrected cost model — through the REAL graph.

Why this file exists
--------------------
Two open questions at the end of Sprint 2, both of which the unit tests cannot
answer:

1. **Does Learner Mode actually differentiate?** S2-LM1–LM5 were all marked
   complete, but Story 2-28 found `_FAN_OUT_STATE_KEYS` was missing `"tier"` —
   a `Send()` payload REPLACES state, so every Phase-1 node read the
   `_DEFAULT_TIER` ("T2") regardless of the lesson's real tier. Every T1 and T3
   lesson silently shipped T2 content. The existing tier tests call the nodes
   directly with `_state(tier=...)`, injecting the very key the fan-out was
   failing to deliver — which is exactly why they stayed green through the bug.
   This file runs the WHOLE pipeline per tier and compares the delivered
   packages, so the fan-out is in the path.

2. **What does a lesson actually cost now?** Every existing baseline was
   measured while the Story 2-28 duplication bug was live. Four nodes ran after
   the Phase-1 fan-in and each re-appended all six `operator.add` channels, so
   `narration_scripts` — and therefore paid TTS synthesis — was inflated 2^4 =
   16x on the channel and ~4x on real spend. Those numbers are unusable.

Providers are faked, so this measures **call counts and content shape**, not
vendor invoices. That is deliberate: call counts x published unit prices is a
model we can recompute for free whenever prices change, and it is what actually
moved when the duplication bug was fixed. A live-money run is still required to
calibrate the model — see `tests/evals/test_live_run.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.integration.test_howto_pipeline_e2e import (
    _QUIZ_FAKE_BATCH_SIZE,
    HOWTO_TEXT,
    _run_howto_tier,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# Published unit prices, mirrored from the provider modules so this file fails
# loudly if they drift rather than silently costing a stale model.
def _unit_prices() -> dict[str, float]:
    from app.providers.embeddings.openai import _EMBED_COST_PER_1K_USD
    from app.providers.llm.openai import _COST_PER_1K

    return {
        "mini_in": _COST_PER_1K["gpt-4o-mini"]["input"],
        "mini_out": _COST_PER_1K["gpt-4o-mini"]["output"],
        "premium_in": _COST_PER_1K["gpt-4o"]["input"],
        "premium_out": _COST_PER_1K["gpt-4o"]["output"],
        "embed_1k": _EMBED_COST_PER_1K_USD,
    }


def _package_shape(pkg: dict[str, Any]) -> dict[str, Any]:
    segments = pkg["segments"]
    quiz_counts = [len(s["quiz"]) for s in segments]
    slide_counts = [len(s["slides"]) for s in segments]
    narration_chars = sum(len(s["narration"]["script"] or "") for s in segments)
    return {
        "segments": len(segments),
        "quiz_total": sum(quiz_counts),
        "quiz_per_segment": quiz_counts,
        "slides_total": sum(slide_counts),
        "slides_per_segment": slide_counts,
        "narration_chars": narration_chars,
    }


async def test_tier_changes_the_delivered_package() -> None:
    """Learner Mode, proven END TO END rather than per-node.

    Runs the real graph three times — T1, T2, T3 — on identical input and
    asserts the delivered packages differ in the way the tier bands prescribe.
    If `_FAN_OUT_STATE_KEYS` ever loses `"tier"` again, every tier collapses to
    T2 here and this test fails; the per-node tier tests would not.
    """
    from app.config import get_settings
    from app.schemas.lesson import quiz_budget_seconds

    def _lesson_budget(tier: str) -> int:
        """The tier's TOTAL question count — S5-4's replacement for the deleted
        per-segment `_TIER_QUIZ_COUNT_BAND`."""
        return int(quiz_budget_seconds(tier) // max(1, get_settings().quiz_seconds_per_question))

    shapes: dict[str, dict[str, Any]] = {}
    for tier in ("T1", "T2", "T3"):
        pkg = await _run_howto_tier(HOWTO_TEXT, str(uuid.uuid4()), tier=tier)
        shapes[tier] = _package_shape(pkg)

    # Story 233 (piece 1 of 4): topic_selection_node now makes segment count a
    # DELIBERATE function of tier (T3 -> 1 topic, T1/T2 -> 2 topics) — this
    # replaces the pre-233 "segment count must be identical across tiers"
    # premise check, which is no longer true by design. The quiz-total
    # comparison below remains valid across differing segment counts because
    # the S5-4 allocator distributes a fixed LESSON-total budget, not a
    # per-segment one — segment count was never actually load-bearing for it.
    seg_counts = {t: s["segments"] for t, s in shapes.items()}
    assert seg_counts["T3"] == 1, f"T3 must collapse to exactly 1 topic, got {seg_counts}"
    assert seg_counts["T1"] == 2, f"T1 must collapse to exactly 2 topics, got {seg_counts}"
    assert seg_counts["T2"] == 2, f"T2 must collapse to exactly 2 topics, got {seg_counts}"

    # S5-4: the invariant is now the LESSON total, not a per-segment band —
    # a per-segment ceiling was exactly the thing that let quiz volume scale
    # with segment count (15 segments x T1's old 3-5 band = 45-75 questions in
    # a 45-minute lesson). Each tier must deliver its whole budget and no more.
    for tier, shape in shapes.items():
        assert shape["quiz_total"] == _lesson_budget(tier), (
            f"{tier}: delivered {shape['quiz_total']} questions against a lesson "
            f"budget of {_lesson_budget(tier)} — the seat-time budget was not honoured"
        )
        # Premise check: if the fake's per-batch size were the binding constraint,
        # the totals above would be measuring the fake, not the allocator. Bound
        # against the real fixture constant (Story 233: topic-collapse means a
        # single topic can now be allocated far more than an old per-section
        # share ever was — see _QUIZ_FAKE_BATCH_SIZE's own comment).
        assert max(shape["quiz_per_segment"]) <= _QUIZ_FAKE_BATCH_SIZE, (
            f"{tier}: a segment was allocated more than the fake supplies — this "
            "comparison would be measuring the fixture, not the tier"
        )

    # All THREE tiers must differ, strictly. Under S5-4 the readout is the
    # lesson total (16 / 10 / 5) rather than a per-segment ceiling, so the
    # delivered counts remain a direct readout of the tier value each node
    # actually received through the fan-out.
    t1, t2, t3 = (shapes[t]["quiz_total"] for t in ("T1", "T2", "T3"))
    assert t1 > t2 > t3, (
        f"tiers did not differentiate (T1={t1}, T2={t2}, T3={t3}) — `tier` is not "
        "reaching the Phase-1 nodes through the fan-out"
    )

    # Stronger: the exact total pins WHICH tier value arrived, not merely that
    # the three differ. (Per-segment counts are deliberately NOT uniform under
    # S5-4 — the allocator distributes a fixed lesson total proportionally, so
    # zero-allocation segments are expected on a long chapter at T3.)
    for tier, shape in shapes.items():
        assert shape["quiz_total"] == _lesson_budget(tier), (
            f"{tier}: total {shape['quiz_total']} != budget {_lesson_budget(tier)} "
            "— a node used the wrong tier"
        )

    print("\n=== Learner Mode: delivered package by tier ===")
    for tier in ("T1", "T2", "T3"):
        s = shapes[tier]
        print(
            f"  {tier} budget {_lesson_budget(tier)} questions/lesson: {s['segments']} segments, "
            f"{s['quiz_total']:>2} quiz ({s['quiz_per_segment']}), "
            f"{s['slides_total']:>2} slides, {s['narration_chars']:>5} narration chars"
        )
    print()
    print("  PROVEN here: `tier` reaches every Phase-1 node through the real")
    print("  fan-out, and the lesson's quiz volume equals its own seat-time")
    print("  budget. This is the regression guard for the Story 2-28 defect,")
    print("  and for S5-4's lesson-level quiz budget.")
    print("  NOT proven here: slide-budget (S2-LM4) and content-depth (S2-LM5)")
    print("  differentiation. Both act on the PROMPT, and the provider is faked")
    print("  — it returns a fixed slide count and a fixed narration string no")
    print("  matter what it was asked for, so identical slides/narration across")
    print("  tiers above is an artefact of the fake, NOT evidence either way.")
    print("  Those need the live run (tests/evals/test_live_run.py).")


async def test_cost_model_per_tier() -> None:
    """Corrected cost model, derived from real call counts through the real graph.

    Reports paid-call counts per tier so the $3.00/lesson ceiling can be
    re-calibrated against post-duplication-fix numbers. Asserts only the
    invariant that matters — TTS is synthesised once per segment — because that
    is the specific quantity Story 2-28's bug inflated, and the one that
    dominates lesson cost (decision #8: TTS is 67-73% of total).
    """
    prices = _unit_prices()

    print("\n=== Cost model inputs (fake providers — counts are real, dollars are modelled) ===")
    print(f"  unit prices: {prices}")

    for tier in ("T1", "T2", "T3"):
        pkg, spies = await _run_howto_tier(
            HOWTO_TEXT, str(uuid.uuid4()), tier=tier, want_spies=True
        )
        shape = _package_shape(pkg)
        synth = spies["synth"]

        # THE invariant Story 2-28 restored. Before the fix the duplicated
        # narration_scripts channel billed the TTS vendor once per DUPLICATE.
        assert synth.await_count == shape["segments"], (
            f"{tier}: TTS synthesised {synth.await_count}x for {shape['segments']} segments — "
            "this is the exact quantity the duplication bug inflated"
        )

        print(
            f"  {tier}: {shape['segments']} segments | TTS calls {synth.await_count} "
            f"| narration {shape['narration_chars']} chars "
            f"| quiz {shape['quiz_total']} | slides {shape['slides_total']}"
        )

    print(
        "\n  NOTE: dollar figures require a live run — see tests/evals/test_live_run.py.\n"
        "  Pre-fix baselines are unusable: four post-fan-in nodes each re-appended\n"
        "  all six operator.add channels (2^4 = 16x on the channel, ~4x on real TTS spend)."
    )
