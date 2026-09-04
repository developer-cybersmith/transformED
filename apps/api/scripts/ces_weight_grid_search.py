"""
S4-31: CES weight grid search.

Reads the calibration CSV produced by export_calibration_data.py (Story 4-30)
and tries 5 CES weight combinations, reporting Pearson r between computed CES
and final quiz accuracy (ground truth proxy).

No app.* imports — standalone script. Uses only stdlib (statistics.correlation,
csv, argparse) plus optional scipy for validation.

Usage:
    python apps/api/scripts/ces_weight_grid_search.py \
        --input ces_calibration_export.csv \
        --output ces_weight_results.csv

Input CSV columns (from export_calibration_data.py):
    session_id, user_id, started_at, ended_at, ces_final,
    quiz_accuracy_pct, quiz_attempts, teachback_avg, teachback_attempts,
    interventions, tab_switches

Exit codes:
    0 — search complete, best weights printed
    1 — insufficient data (<5 usable sessions)
    2 — argument error / missing input file
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Weight combinations to evaluate (each tuple must sum to 1.0)
# Format: (quiz, teachback, behavioral, head_pose, blink)
# ---------------------------------------------------------------------------
WEIGHT_COMBINATIONS: list[tuple[float, float, float, float, float]] = [
    (0.35, 0.25, 0.20, 0.12, 0.08),  # PRD §11 defaults
    (0.40, 0.25, 0.15, 0.13, 0.07),  # boost quiz, reduce behavioral (S4-31 provisional)
    (0.45, 0.20, 0.15, 0.12, 0.08),  # stronger quiz emphasis
    (0.35, 0.30, 0.18, 0.12, 0.05),  # boost teachback
    (0.40, 0.25, 0.18, 0.10, 0.07),  # balanced adjustment
]

assert all(
    abs(sum(c) - 1.0) < 1e-9 for c in WEIGHT_COMBINATIONS
), "All weight combinations must sum to 1.0"

_MIN_USABLE = 5  # minimum sessions needed for a meaningful Pearson r


def pearson_r(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient using stdlib statistics (Python 3.10+)."""
    if len(xs) < 2:
        return 0.0
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return 0.0


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def compute_ces_row(
    row: dict[str, Any],
    weights: tuple[float, float, float, float, float],
) -> float | None:
    """Compute CES for one row using the given weights.

    Returns None if quiz_accuracy is unavailable.
    quiz_accuracy_pct is 0–100; we normalise to 0–1 before weighting.
    head_pose and blink are not in the calibration CSV (they need WS signals);
    we substitute 0.5 (neutral) as a conservative estimate.
    """
    wq, wt, wb, whp, wbl = weights

    try:
        quiz_pct = float(row["quiz_accuracy_pct"])
    except (KeyError, ValueError, TypeError):
        return None  # can't compute without quiz signal

    quiz_norm = _clamp(quiz_pct / 100.0)

    # teachback: normalise 0-100 score to 0-1; None → redistribute weight
    tb_raw = row.get("teachback_avg")
    if tb_raw is None or str(tb_raw).strip() in ("", "None"):
        tb_norm = None
    else:
        try:
            tb_norm = _clamp(float(tb_raw) / 100.0)
        except (ValueError, TypeError):
            tb_norm = None

    # behavioral: derived from intervention count (max 3 per session per CLAUDE.md)
    try:
        n_interventions = int(row.get("interventions") or 0)
    except (ValueError, TypeError):
        n_interventions = 0
    behavioral = _clamp(1.0 - n_interventions / 3.0)

    # head_pose, blink: not in export CSV — use neutral 0.5
    head_pose = 0.5
    blink = 0.5

    if tb_norm is None:
        # Redistribute teachback weight proportionally (CLAUDE.md CES formula)
        total_remaining = 1.0 - wt
        if total_remaining <= 0:
            return 0.0
        scale = 1.0 / total_remaining
        ces = (
            quiz_norm * wq * scale
            + behavioral * wb * scale
            + head_pose * whp * scale
            + blink * wbl * scale
        )
    else:
        ces = (
            quiz_norm * wq
            + tb_norm * wt
            + behavioral * wb
            + head_pose * whp
            + blink * wbl
        )

    return _clamp(ces * 100.0, 0.0, 100.0)


def load_csv(path: str) -> list[dict[str, Any]]:
    """Load calibration CSV rows."""
    try:
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"ERROR: input file '{path}' not found.", file=sys.stderr)
        sys.exit(2)


def write_results_csv(results: list[dict[str, Any]], path: str) -> None:
    """Write grid search results to a CSV file."""
    fieldnames = ["quiz", "teachback", "behavioral", "head_pose", "blink", "pearson_r", "n_sessions"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def run_grid_search(rows: list[dict[str, Any]]) -> tuple[tuple[float, float, float, float, float], float, list[dict[str, Any]]]:
    """Run the grid search. Returns (best_combo, best_r, all_results)."""
    # Use quiz_accuracy_pct as ground truth (proxy for learning outcome)
    ground_truth: list[float] = []
    usable_indices: list[int] = []
    for i, row in enumerate(rows):
        try:
            gt = float(row["quiz_accuracy_pct"])
            usable_indices.append(i)
            ground_truth.append(gt)
        except (ValueError, TypeError):
            pass

    n_usable = len(usable_indices)
    if n_usable < _MIN_USABLE:
        print(
            f"ERROR: only {n_usable} usable sessions (need >= {_MIN_USABLE}). "
            "Run generate_test_sessions.py then export_calibration_data.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Grid search over {n_usable} sessions, {len(WEIGHT_COMBINATIONS)} weight combinations.")
    print()
    print(f"{'quiz':>6} {'tb':>6} {'beh':>6} {'hp':>6} {'blink':>6} | {'Pearson r':>10} | verdict")
    print("-" * 60)

    all_results: list[dict[str, Any]] = []
    best_r = -999.0
    best_combo = WEIGHT_COMBINATIONS[0]

    for combo in WEIGHT_COMBINATIONS:
        predicted: list[float] = []
        for i in usable_indices:
            ces = compute_ces_row(rows[i], combo)
            predicted.append(ces if ces is not None else 0.0)

        r = pearson_r(ground_truth, predicted)
        verdict = "BEST" if r > best_r else ("ok" if r > 0.6 else "below-target")
        if r > best_r:
            best_r = r
            best_combo = combo
            verdict = "BEST"

        q, t, b, hp, bl = combo
        print(f"{q:>6.2f} {t:>6.2f} {b:>6.2f} {hp:>6.2f} {bl:>6.2f} | {r:>10.4f} | {verdict}")
        all_results.append({
            "quiz": q, "teachback": t, "behavioral": b,
            "head_pose": hp, "blink": bl,
            "pearson_r": round(r, 6), "n_sessions": n_usable,
        })

    print("-" * 60)
    q, t, b, hp, bl = best_combo
    print(f"\nBEST: quiz={q} teachback={t} behavioral={b} head_pose={hp} blink={bl}")
    print(f"Pearson r = {best_r:.4f}  {'(meets > 0.6 target)' if best_r > 0.6 else '(below 0.6 target -- more data needed)'}")
    print(f"\nApply to apps/api/app/config.py:")
    print(f"  ces_weight_quiz:       Field(default={q})")
    print(f"  ces_weight_teachback:  Field(default={t})")
    print(f"  ces_weight_behavioral: Field(default={b})")
    print(f"  ces_weight_head_pose:  Field(default={hp})")
    print(f"  ces_weight_blink:      Field(default={bl})")

    return best_combo, best_r, all_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CES weight grid search (Story 4-31).")
    parser.add_argument(
        "--input",
        default="ces_calibration_export.csv",
        help="Input CSV from export_calibration_data.py (default: ces_calibration_export.csv)",
    )
    parser.add_argument(
        "--output",
        default="ces_weight_results.csv",
        help="Output CSV path for grid search results (default: ces_weight_results.csv)",
    )
    args = parser.parse_args(argv)

    rows = load_csv(args.input)
    if not rows:
        print(f"ERROR: input CSV '{args.input}' is empty.", file=sys.stderr)
        return 1

    _best_combo, _best_r, results = run_grid_search(rows)
    write_results_csv(results, args.output)
    print(f"\nResults written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
