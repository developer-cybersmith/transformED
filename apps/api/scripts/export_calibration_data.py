"""
S4-30: CES calibration data export script.

Reads from Supabase directly (service-role key — admin access) and exports
a structured CSV for the CES weight grid search (Story 4-31).

No app.* imports — standalone script.

Usage:
    export SUPABASE_URL=https://xxx.supabase.co
    export SUPABASE_SERVICE_ROLE_KEY=eyJ...
    python apps/api/scripts/export_calibration_data.py \
        --output ces_calibration_export.csv \
        [--limit 10000]

Environment:
    SUPABASE_URL              — Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY — service-role key (never the anon key)

Output columns (one row per completed session with ces_final IS NOT NULL):
    session_id, user_id, started_at, ended_at, ces_final,
    quiz_accuracy_pct, quiz_attempts,
    teachback_avg, teachback_attempts,
    interventions, tab_switches
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Any

_DEFAULT_LIMIT = 10_000


def build_export_row(
    *,
    session: dict[str, Any],
    quiz_accuracy_pct: float,
    quiz_attempts: int,
    teachback_avg: float | None,
    teachback_attempts: int,
    interventions: int,
    tab_switches: int,
) -> dict[str, Any]:
    """Build one export row from a session dict and aggregated sub-table data."""
    return {
        "session_id": session.get("id", ""),
        "user_id": session.get("user_id", ""),
        "started_at": session.get("started_at", ""),
        "ended_at": session.get("ended_at", ""),
        "ces_final": session.get("ces_final"),
        "quiz_accuracy_pct": quiz_accuracy_pct,
        "quiz_attempts": quiz_attempts,
        "teachback_avg": teachback_avg,
        "teachback_attempts": teachback_attempts,
        "interventions": interventions,
        "tab_switches": tab_switches,
    }


def maybe_warn_signals_capped(*, signals_capped: bool, table: str, limit: int) -> None:
    """Print a warning when a query hit its .limit() boundary (SCALE-CONTRACT §2)."""
    if signals_capped:
        print(
            f"WARN: signals_capped=True for table '{table}' — "
            f"query returned exactly {limit} rows (the limit). "
            "There may be more rows not included in this export. "
            "Re-run with a smaller date range or increase --limit.",
            flush=True,
        )


def _aggregate_quiz(rows: list[dict[str, Any]]) -> tuple[float, int]:
    """Return (accuracy_pct, n_attempts) for a list of quiz_attempts rows."""
    if not rows:
        return 0.0, 0
    n_correct = sum(1 for r in rows if r.get("is_correct"))
    return round(n_correct / len(rows) * 100, 2), len(rows)


def _aggregate_teachback(rows: list[dict[str, Any]]) -> tuple[float | None, int]:
    """Return (avg_score, n_attempts) for a list of teachback_attempts rows."""
    scores = [r["score"] for r in rows if r.get("score") is not None]
    if not scores:
        return None, len(rows)
    return round(sum(scores) / len(scores), 2), len(rows)


def _count_events(rows: list[dict[str, Any]], event_type: str) -> int:
    return sum(1 for r in rows if r.get("event_type") == event_type)


def run_export(supabase_url: str, service_role_key: str, limit: int, output: str) -> int:
    """Main export logic. Returns exit code (0=ok, 1=error)."""
    try:
        from supabase import create_client  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: supabase SDK not installed. Run: pip install supabase", file=sys.stderr)
        return 1

    client = create_client(supabase_url, service_role_key)

    # 1. Fetch completed sessions with ces_final
    sessions_resp = (
        client.table("sessions")
        .select("id, user_id, started_at, ended_at, ces_final")
        .not_.is_("ended_at", "null")
        .not_.is_("ces_final", "null")
        .limit(limit)
        .execute()
    )
    sessions = sessions_resp.data or []
    maybe_warn_signals_capped(signals_capped=len(sessions) == limit, table="sessions", limit=limit)

    if not sessions:
        print("No completed sessions with ces_final found. Check your Supabase project and D116 fix.")
        return 0

    print(f"Exporting {len(sessions)} completed sessions...")

    rows: list[dict[str, Any]] = []

    for sess in sessions:
        sid = sess["id"]

        # 2. Quiz attempts for session
        quiz_resp = (
            client.table("quiz_attempts")
            .select("is_correct")
            .eq("session_id", sid)
            .limit(limit)
            .execute()
        )
        quiz_rows = quiz_resp.data or []
        maybe_warn_signals_capped(
            signals_capped=len(quiz_rows) == limit, table="quiz_attempts", limit=limit
        )
        quiz_accuracy_pct, n_quiz = _aggregate_quiz(quiz_rows)

        # 3. Teachback attempts for session
        tb_resp = (
            client.table("teachback_attempts")
            .select("score")
            .eq("session_id", sid)
            .limit(limit)
            .execute()
        )
        tb_rows = tb_resp.data or []
        maybe_warn_signals_capped(
            signals_capped=len(tb_rows) == limit, table="teachback_attempts", limit=limit
        )
        teachback_avg, n_teachback = _aggregate_teachback(tb_rows)

        # 4. Session events for intervention + tab counts
        ev_resp = (
            client.table("session_events")
            .select("event_type")
            .eq("session_id", sid)
            .limit(limit)
            .execute()
        )
        ev_rows = ev_resp.data or []
        maybe_warn_signals_capped(
            signals_capped=len(ev_rows) == limit, table="session_events", limit=limit
        )
        n_interventions = _count_events(ev_rows, "intervention_triggered")
        n_tab_switches = _count_events(ev_rows, "tab_switch")

        rows.append(
            build_export_row(
                session=sess,
                quiz_accuracy_pct=quiz_accuracy_pct,
                quiz_attempts=n_quiz,
                teachback_avg=teachback_avg,
                teachback_attempts=n_teachback,
                interventions=n_interventions,
                tab_switches=n_tab_switches,
            )
        )

    # 5. Write CSV
    fieldnames = [
        "session_id", "user_id", "started_at", "ended_at", "ces_final",
        "quiz_accuracy_pct", "quiz_attempts",
        "teachback_avg", "teachback_attempts",
        "interventions", "tab_switches",
    ]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} rows to {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export CES calibration data from Supabase.")
    parser.add_argument("--output", default="ces_calibration_export.csv")
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"Max rows per query (default {_DEFAULT_LIMIT}). signals_capped warning printed if hit.",
    )
    args = parser.parse_args(argv)

    supabase_url = os.environ.get("SUPABASE_URL", "")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        print(
            "ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables.",
            file=sys.stderr,
        )
        return 2

    return run_export(supabase_url, service_role_key, args.limit, args.output)


if __name__ == "__main__":
    sys.exit(main())
