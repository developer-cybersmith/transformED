"""
CES weight grid search (Story 4-31).

Tries 5 weight combinations against the session dataset from Supabase and
reports Pearson r between computed CES and final quiz score (ground truth).

Usage:
    SUPABASE_URL=https://... SUPABASE_SERVICE_KEY=... python scripts/ces_weight_grid_search.py

Depends on: scripts/ces_correlation_analysis.py data-loading helpers
Requires: pip install scipy
"""

import os
import sys
from itertools import product

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

try:
    from scipy.stats import pearsonr  # type: ignore[import]
except ImportError:
    sys.exit("Error: scipy required — run: pip install scipy")

from supabase import create_client, Client  # type: ignore[import]

# Reuse data loaders from correlation analysis
sys.path.insert(0, os.path.dirname(__file__))
from ces_correlation_analysis import (  # type: ignore[import]
    load_sessions,
    load_quiz_accuracy,
    load_teachback_scores,
    load_intervention_counts,
)
from app.modules.assessment.ces import compute_ces
from app.config import get_settings, Settings

# ---------------------------------------------------------------------------
# Weight combinations to try (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_COMBINATIONS = [
    # (quiz, teachback, behavioral, head_pose, blink)  — must sum to 1.0
    (0.35, 0.25, 0.20, 0.12, 0.08),   # current defaults
    (0.40, 0.25, 0.15, 0.13, 0.07),   # boost quiz, reduce behavioral
    (0.45, 0.20, 0.15, 0.12, 0.08),   # stronger quiz signal emphasis
    (0.35, 0.30, 0.18, 0.12, 0.05),   # boost teachback
    (0.40, 0.25, 0.18, 0.10, 0.07),   # balanced adjustment
]

assert all(
    abs(sum(combo) - 1.0) < 1e-9
    for combo in WEIGHT_COMBINATIONS
), "All weight combinations must sum to 1.0"


def mock_settings(q: float, tb: float, beh: float, hp: float, bl: float) -> Settings:
    """Return a Settings object with custom CES weights."""
    import pydantic
    s = get_settings()
    # Return a simple namespace-like object with the CES weight attrs
    class _S:
        ces_weight_quiz = q
        ces_weight_teachback = tb
        ces_weight_behavioral = beh
        ces_weight_head_pose = hp
        ces_weight_blink = bl

    return _S()  # type: ignore[return-value]


def compute_ces_with_weights(
    quiz_acc: float | None,
    tb_score: float | None,
    interventions: int,
    settings,
) -> float:
    behavioral = 1.0 - (interventions / 3.0)
    result = compute_ces(
        quiz_accuracy=quiz_acc,
        teachback_score=tb_score,
        behavioral=behavioral,
        head_pose=0.5,
        blink=0.5,
        settings=settings,
    )
    return result * 100.0  # 0–1 → 0–100


def run_grid_search(
    sessions: list[dict],
    quiz_acc: dict,
    tb_scores: dict,
    intv: dict,
) -> tuple[tuple, float]:
    """Return (best_combo, best_r)."""
    usable = [
        s for s in sessions
        if s["id"] in quiz_acc and s.get("ces_final") is not None
    ]
    if len(usable) < 5:
        sys.exit(f"Only {len(usable)} usable sessions — run generate_synthetic_sessions.py first.")

    ground_truth = [quiz_acc[s["id"]] for s in usable]

    print("\n" + "=" * 80)
    print("CES WEIGHT GRID SEARCH")
    print(f"{'quiz':>6} {'tb':>6} {'beh':>6} {'hp':>6} {'blink':>6} | {'Pearson r':>10} | verdict")
    print("-" * 80)

    best_r = -999.0
    best_combo = WEIGHT_COMBINATIONS[0]

    for combo in WEIGHT_COMBINATIONS:
        q_w, tb_w, beh_w, hp_w, bl_w = combo
        s_obj = mock_settings(q_w, tb_w, beh_w, hp_w, bl_w)

        predicted_ces = [
            compute_ces_with_weights(
                quiz_acc.get(s["id"]),
                tb_scores.get(s["id"]),
                intv.get(s["id"], 0),
                s_obj,
            )
            for s in usable
        ]

        try:
            r, _ = pearsonr(ground_truth, predicted_ces)
        except Exception:
            r = 0.0

        verdict = "✓ BEST" if r == best_r else ("✓" if r > 0.6 else "✗")
        if r > best_r:
            best_r = r
            best_combo = combo

        print(
            f"{q_w:>6.2f} {tb_w:>6.2f} {beh_w:>6.2f} {hp_w:>6.2f} {bl_w:>6.2f} "
            f"| {r:>10.4f} | {verdict}"
        )

    print("=" * 80)
    print(f"\nBEST COMBINATION: quiz={best_combo[0]}, tb={best_combo[1]}, "
          f"beh={best_combo[2]}, hp={best_combo[3]}, blink={best_combo[4]}")
    print(f"Pearson r = {best_r:.4f} {'(target: > 0.6)' if best_r > 0.6 else '(BELOW TARGET)'}")
    print(
        f"\nApply to config.py:\n"
        f"  ces_weight_quiz:       {best_combo[0]}\n"
        f"  ces_weight_teachback:  {best_combo[1]}\n"
        f"  ces_weight_behavioral: {best_combo[2]}\n"
        f"  ces_weight_head_pose:  {best_combo[3]}\n"
        f"  ces_weight_blink:      {best_combo[4]}\n"
    )
    return best_combo, best_r


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

    sb = create_client(url, key)
    sessions = load_sessions(sb)
    if not sessions:
        sys.exit("No completed sessions found. Run generate_synthetic_sessions.py first.")

    session_ids = [s["id"] for s in sessions]
    quiz_acc = load_quiz_accuracy(sb, session_ids)
    tb_scores = load_teachback_scores(sb, session_ids)
    intv = load_intervention_counts(sb, session_ids)

    run_grid_search(sessions, quiz_acc, tb_scores, intv)


if __name__ == "__main__":
    main()
