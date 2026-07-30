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

from tests.integration.test_howto_pipeline_e2e import HOWTO_TEXT, _run_howto_tier

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
    from app.modules.content.pipeline.graph import _TIER_QUIZ_COUNT_BAND

    shapes: dict[str, dict[str, Any]] = {}
    for tier in ("T1", "T2", "T3"):
        pkg = await _run_howto_tier(HOWTO_TEXT, str(uuid.uuid4()), tier=tier)
        shapes[tier] = _package_shape(pkg)

    # Same input every time — segment count must not move, or we are comparing
    # different lessons and any quiz-count difference is meaningless.
    seg_counts = {t: s["segments"] for t, s in shapes.items()}
    assert len(set(seg_counts.values())) == 1, (
        f"segment count differs across tiers {seg_counts} — the comparison below is invalid"
    )

    # Every segment's quiz count must sit inside ITS OWN tier band.
    for tier, shape in shapes.items():
        lo, hi = _TIER_QUIZ_COUNT_BAND[tier]
        for i, n in enumerate(shape["quiz_per_segment"]):
            assert n <= hi, f"{tier} segment {i}: {n} questions exceeds band max {hi}"

    # All THREE tiers must differ, strictly. The fake returns 5 questions per
    # batch — at or above every band's n_max — so each tier truncates to its own
    # ceiling and the delivered counts become a direct readout of the tier value
    # each node actually received. With the fake's original fixed 3, T1 (n_max=5)
    # and T2 (n_max=3) both kept 3 and were indistinguishable; the comparison
    # looked like it passed while proving nothing about T1 vs T2.
    t1, t2, t3 = (shapes[t]["quiz_total"] for t in ("T1", "T2", "T3"))
    assert t1 > t2 > t3, (
        f"tiers did not differentiate (T1={t1}, T2={t2}, T3={t3}) — `tier` is not "
        "reaching the Phase-1 nodes through the fan-out"
    )

    # Stronger: each tier's per-segment count must equal ITS OWN n_max, which
    # pins WHICH tier value arrived rather than merely that they differ.
    for tier, shape in shapes.items():
        n_max = _TIER_QUIZ_COUNT_BAND[tier][1]
        assert set(shape["quiz_per_segment"]) == {n_max}, (
            f"{tier}: expected every segment at n_max={n_max}, got "
            f"{sorted(set(shape['quiz_per_segment']))} — a node used the wrong tier"
        )

    print("\n=== Learner Mode: delivered package by tier ===")
    for tier in ("T1", "T2", "T3"):
        s = shapes[tier]
        lo, hi = _TIER_QUIZ_COUNT_BAND[tier]
        print(
            f"  {tier} band {lo}-{hi}: {s['segments']} segments, "
            f"{s['quiz_total']:>2} quiz ({s['quiz_per_segment']}), "
            f"{s['slides_total']:>2} slides, {s['narration_chars']:>5} narration chars"
        )
    print()
    print("  PROVEN here: `tier` reaches every Phase-1 node through the real")
    print("  fan-out, and each node truncates to its own band ceiling. This is")
    print("  the regression guard for the Story 2-28 defect.")
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
