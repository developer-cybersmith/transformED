"""
CES correlation analysis (Story 4-30).

Reads sessions + quiz_attempts + teachback_attempts from Supabase,
computes Pearson r between each CES component and final quiz score (ground truth),
and prints calibration recommendations for S4-31.

Usage:
    SUPABASE_URL=https://... SUPABASE_SERVICE_KEY=... python scripts/ces_correlation_analysis.py

Requires: pip install scipy
"""

import os
import sys
from statistics import mean

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from supabase import create_client, Client  # type: ignore[import]

try:
    from scipy.stats import pearsonr  # type: ignore[import]
except ImportError:
    sys.exit("Error: scipy required — run: pip install scipy")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_sessions(sb: Client) -> list[dict]:
    """Load completed sessions with ces_final."""
    resp = (
        sb.table("sessions")
        .select("id,user_id,lesson_id,ces_final,ended_at")
        .not_.is_("ended_at", "null")
        .not_.is_("ces_final", "null")
        .limit(200)
        .execute()
    )
    return resp.data or []


def load_quiz_accuracy(sb: Client, session_ids: list[str]) -> dict[str, float]:
    """Return {session_id: accuracy} for each session."""
    if not session_ids:
        return {}
    resp = (
        sb.table("quiz_attempts")
        .select("session_id,is_correct")
        .in_("session_id", session_ids)
        .limit(5000)
        .execute()
    )
    by_session: dict[str, list[bool]] = {}
    for row in (resp.data or []):
        by_session.setdefault(row["session_id"], []).append(row["is_correct"])

    return {
        sid: sum(answers) / len(answers)
        for sid, answers in by_session.items()
        if answers
    }


def load_teachback_scores(sb: Client, session_ids: list[str]) -> dict[str, float]:
    """Return {session_id: avg_score_normalised} for sessions with teachback."""
    if not session_ids:
        return {}
    resp = (
        sb.table("teachback_attempts")
        .select("session_id,overall_score")
        .in_("session_id", session_ids)
        .limit(1000)
        .execute()
    )
    by_session: dict[str, list[float]] = {}
    for row in (resp.data or []):
        if row["overall_score"] is not None:
            by_session.setdefault(row["session_id"], []).append(float(row["overall_score"]))

    return {
        sid: mean(scores) / 100.0   # normalise 0–100 → 0–1
        for sid, scores in by_session.items()
        if scores
    }


def load_intervention_counts(sb: Client, session_ids: list[str]) -> dict[str, int]:
    """Return {session_id: intervention_count}."""
    if not session_ids:
        return {}
    resp = (
        sb.table("session_events")
        .select("session_id")
        .eq("event_type", "intervention_triggered")
        .in_("session_id", session_ids)
        .limit(10000)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in (resp.data or []):
        counts[row["session_id"]] = counts.get(row["session_id"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(sessions: list[dict], quiz_acc: dict, tb_scores: dict, intv: dict) -> None:
    """Print Pearson r for each component vs quiz accuracy (ground truth)."""
    records = []
    for s in sessions:
        sid = s["id"]
        q_acc = quiz_acc.get(sid)
        ces = s["ces_final"]
        if q_acc is None or ces is None:
            continue

        tb = tb_scores.get(sid, None)
        interventions = intv.get(sid, 0)
        behavioral = 1.0 - (interventions / 3.0)

        records.append(
            {
                "session_id": sid,
                "ground_truth": q_acc,       # final quiz score = ground truth
                "ces_final": float(ces),
                "quiz_component": q_acc * 0.35 * 100,
                "tb_component": (tb * 0.25 * 100) if tb else 0.0,
                "behavioral_component": behavioral * 0.20 * 100,
            }
        )

    if len(records) < 5:
        print(f"WARNING: only {len(records)} usable sessions — results unreliable.")
        if not records:
            return

    gt = [r["ground_truth"] for r in records]
    components = {
        "ces_final (overall)": [r["ces_final"] / 100.0 for r in records],
        "quiz_component (×0.35)": [r["quiz_component"] / 100.0 for r in records],
        "teachback_component (×0.25)": [r["tb_component"] / 100.0 for r in records],
        "behavioral_component (×0.20)": [r["behavioral_component"] / 100.0 for r in records],
    }

    print("\n" + "=" * 70)
    print("CES CORRELATION ANALYSIS — Pearson r vs. Final Quiz Score (ground truth)")
    print("=" * 70)
    print(f"{'Component':<35} {'Pearson r':>10} {'Verdict':>25}")
    print("-" * 70)

    for label, values in components.items():
        try:
            r, p = pearsonr(gt, values)
        except Exception:
            r, p = 0.0, 1.0

        if r > 0.7:
            verdict = "STRONG ✓ — consider raising weight"
        elif r > 0.4:
            verdict = "MODERATE — keep weight"
        else:
            verdict = "WEAK ✗ — consider reducing weight"

        print(f"{label:<35} {r:>10.3f} {verdict:>25}")

    print("-" * 70)
    print(f"\nSessions analysed: {len(records)}")
    print(f"Quiz accuracy range: {min(gt):.1%} – {max(gt):.1%}")

    # CES threshold check
    ces_vals = [r["ces_final"] for r in records]
    below_50 = sum(1 for c in ces_vals if c < 50)
    print(f"\nCES threshold=50 check:")
    print(f"  Sessions below 50: {below_50}/{len(ces_vals)} "
          f"({'over-triggering — threshold may be too high' if below_50 > len(ces_vals) * 0.5 else 'OK'})")

    print("\nRecommendations for S4-31 (CES weight tuning):")
    for label, values in components.items():
        if label == "ces_final (overall)":
            continue
        try:
            r, _ = pearsonr(gt, values)
        except Exception:
            r = 0.0
        if r < 0.4:
            print(f"  • {label}: r={r:.3f} — reduce weight by 20–30%")
        elif r > 0.7:
            print(f"  • {label}: r={r:.3f} — increase weight by 10–20%")
    print("=" * 70)


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

    sb = create_client(url, key)
    print("Loading session data from Supabase…")

    sessions = load_sessions(sb)
    if not sessions:
        sys.exit("No completed sessions with ces_final found. Run generate_synthetic_sessions.py first.")

    session_ids = [s["id"] for s in sessions]
    print(f"Found {len(session_ids)} completed sessions with ces_final.")

    quiz_acc = load_quiz_accuracy(sb, session_ids)
    tb_scores = load_teachback_scores(sb, session_ids)
    intv = load_intervention_counts(sb, session_ids)

    analyse(sessions, quiz_acc, tb_scores, intv)


if __name__ == "__main__":
    main()
