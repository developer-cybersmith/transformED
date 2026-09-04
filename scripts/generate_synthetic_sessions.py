"""
Synthetic session generator for CES calibration (Story 4-30).

Generates 25 synthetic sessions (5 low / 10 mid / 10 high performers) in Supabase
with realistic quiz_attempts, teachback_attempts, session_events and ces_final.

Usage:
    SUPABASE_URL=https://... SUPABASE_SERVICE_KEY=... python scripts/generate_synthetic_sessions.py

Idempotent: re-running skips sessions whose synthetic lesson_id already exists.
"""

import os
import sys
import random
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Bootstrap path so we can import the real compute_ces
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from supabase import create_client, Client  # type: ignore[import]
from app.modules.assessment.ces import compute_ces
from app.config import get_settings

# ---------------------------------------------------------------------------
# Fixed test identifiers (idempotency anchors)
# ---------------------------------------------------------------------------
SYNTHETIC_USER_ID = "00000000-0000-0000-0000-000000000099"

# 25 deterministic lesson UUIDs — one per synthetic session
SYNTHETIC_LESSON_IDS = [
    f"00000000-0000-0000-0000-{str(i).zfill(12)}"
    for i in range(1, 26)
]

# ---------------------------------------------------------------------------
# Performance tier definitions
# ---------------------------------------------------------------------------
TIERS = [
    # (tier_name, count, quiz_acc_range, teachback_range_or_None, intervention_range)
    ("low",  5,  (0.30, 0.50), None,           (2, 3)),
    ("mid",  10, (0.55, 0.75), (55.0, 75.0),   (0, 2)),
    ("high", 10, (0.80, 0.95), (75.0, 95.0),   (0, 1)),
]

QUESTIONS_PER_SESSION = (4, 12)   # min, max
SESSION_DURATION_MINUTES = (8, 45)

random.seed(42)  # reproducible synthetic data


def _rng_float(lo: float, hi: float) -> float:
    return round(random.uniform(lo, hi), 4)


def _rng_int(lo: int, hi: int) -> int:
    return random.randint(lo, hi)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_session_rows() -> list[dict]:
    """Return list of session dicts across all tiers."""
    rows = []
    lesson_iter = iter(SYNTHETIC_LESSON_IDS)
    settings = get_settings()

    for tier_name, count, quiz_range, tb_range, intv_range in TIERS:
        for _ in range(count):
            lesson_id = next(lesson_iter)
            quiz_acc = _rng_float(*quiz_range)
            n_questions = _rng_int(*QUESTIONS_PER_SESSION)

            # teachback: mid/high only, ~60% of sessions attempt it
            tb_score: float | None = None
            if tb_range is not None and random.random() < 0.6:
                tb_score = round(_rng_float(*tb_range), 2)
            # Normalise teachback to [0, 1] for CES formula
            tb_normalised = (tb_score / 100.0) if tb_score is not None else None

            interventions = _rng_int(*intv_range)
            behavioral = round(1.0 - (interventions / 3.0), 4)

            ces_final = round(
                compute_ces(
                    quiz_accuracy=quiz_acc,
                    teachback_score=tb_normalised,
                    behavioral=behavioral,
                    head_pose=0.5,   # assumed partial consent
                    blink=0.5,
                    settings=settings,
                )
                * 100,  # compute_ces returns 0–1; CES is stored as 0–100
                2,
            )

            started_at = _now_utc() - timedelta(days=_rng_int(1, 30))
            ended_at = started_at + timedelta(minutes=_rng_float(*SESSION_DURATION_MINUTES))

            rows.append(
                {
                    "tier": tier_name,
                    "lesson_id": lesson_id,
                    "quiz_acc": quiz_acc,
                    "n_questions": n_questions,
                    "tb_score": tb_score,
                    "tb_normalised": tb_normalised,
                    "interventions": interventions,
                    "behavioral": behavioral,
                    "ces_final": ces_final,
                    "started_at": started_at.isoformat(),
                    "ended_at": ended_at.isoformat(),
                }
            )
    return rows


def insert_sessions(sb: Client, rows: list[dict]) -> list[dict]:
    """Insert session rows (idempotent — skip existing lesson_ids)."""
    existing_resp = (
        sb.table("sessions")
        .select("lesson_id")
        .eq("user_id", SYNTHETIC_USER_ID)
        .limit(50)
        .execute()
    )
    existing_lessons = {r["lesson_id"] for r in (existing_resp.data or [])}

    created = []
    for row in rows:
        if row["lesson_id"] in existing_lessons:
            print(f"  [SKIP] lesson {row['lesson_id'][:16]}… already exists")
            continue

        resp = (
            sb.table("sessions")
            .insert(
                {
                    "user_id": SYNTHETIC_USER_ID,
                    "lesson_id": row["lesson_id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "ces_final": row["ces_final"],
                }
            )
            .execute()
        )
        if resp.data:
            session_id = resp.data[0]["id"]
            row["session_id"] = session_id
            created.append(row)
            print(f"  [OK] {row['tier']:4s} session {session_id[:8]}… ces={row['ces_final']}")

    return created


def insert_quiz_attempts(sb: Client, rows: list[dict]) -> None:
    """Insert quiz_attempts for each new session."""
    for row in rows:
        sid = row["session_id"]
        n = row["n_questions"]
        correct_count = round(row["quiz_acc"] * n)
        answers = [True] * correct_count + [False] * (n - correct_count)
        random.shuffle(answers)

        batch = [
            {
                "session_id": sid,
                "segment_id": f"seg-{i // 3 + 1}",
                "question_id": f"q-{i + 1}",
                "selected_option": "A" if answers[i] else "B",
                "correct_option": "A",
                "is_correct": answers[i],
                "attempt_number": 1,
                "response_time_ms": _rng_int(1500, 25000),
            }
            for i in range(n)
        ]
        sb.table("quiz_attempts").insert(batch).execute()
        print(f"    quiz_attempts: {n} rows for session {sid[:8]}…")


def insert_teachback_attempts(sb: Client, rows: list[dict]) -> None:
    """Insert teachback_attempts where tb_score is set."""
    for row in rows:
        if row["tb_score"] is None:
            continue
        sid = row["session_id"]
        sb.table("teachback_attempts").insert(
            {
                "session_id": sid,
                "segment_id": "seg-1",
                "response_text": "Synthetic student explanation for calibration.",
                "overall_score": row["tb_score"],
                "score_source": "synthetic",
                "attempt_number": 1,
            }
        ).execute()
        print(f"    teachback_attempt: score={row['tb_score']} for session {sid[:8]}…")


def insert_session_events(sb: Client, rows: list[dict]) -> None:
    """Insert intervention session_events."""
    for row in rows:
        if row["interventions"] == 0:
            continue
        sid = row["session_id"]
        events = [
            {
                "session_id": sid,
                "event_type": "intervention_triggered",
                "payload": {"intervention_number": i + 1, "source": "synthetic"},
            }
            for i in range(row["interventions"])
        ]
        sb.table("session_events").insert(events).execute()
        print(f"    session_events: {row['interventions']} intervention rows for {sid[:8]}…")


def print_summary(rows: list[dict]) -> None:
    print("\n" + "=" * 80)
    print(f"{'session_id':<12} {'tier':<6} {'quiz_acc':>10} {'tb_score':>10} {'ces_final':>10}")
    print("-" * 80)
    for row in rows:
        sid = row.get("session_id", "SKIPPED")[:8] + "…"
        tb = f"{row['tb_score']:.1f}" if row["tb_score"] else "—"
        print(
            f"{sid:<12} {row['tier']:<6} {row['quiz_acc']:>10.3f} {tb:>10} {row['ces_final']:>10.1f}"
        )
    print("=" * 80)
    print(f"Total sessions created: {len(rows)}")


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

    sb = create_client(url, key)
    print("Connected to Supabase. Generating 25 synthetic sessions…\n")

    all_rows = build_session_rows()
    created = insert_sessions(sb, all_rows)

    if created:
        insert_quiz_attempts(sb, created)
        insert_teachback_attempts(sb, created)
        insert_session_events(sb, created)

    print_summary(created)


if __name__ == "__main__":
    main()
