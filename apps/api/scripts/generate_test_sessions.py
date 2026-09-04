"""
S4-30: Synthetic session generator for CES calibration.

Drives the full quiz/teachback/complete lifecycle via HTTP against the real API.
No app.* imports — standalone script.

Usage:
    python apps/api/scripts/generate_test_sessions.py \
        --api-url http://localhost:8000 \
        --auth-token <bearer-token> \
        --n-sessions 20 \
        --segments-per-session 3 \
        --quiz-accuracy 0.7 \
        --output ces_synthetic_sessions.csv

Exit codes:
    0 — all sessions created successfully
    1 — partial failure (some sessions failed; CSV still written)
    2 — argument error
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
import uuid
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
    sys.exit(2)

_STUB_TEACHBACK = (
    "The key concept is explained clearly with relevant detail. "
    "The explanation covers both the fundamental idea and its practical application, "
    "demonstrating a solid understanding of the material."
)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate synthetic test sessions for CES calibration."
    )
    p.add_argument("--api-url", required=True, help="Base URL of the API (e.g. http://localhost:8000)")
    p.add_argument("--auth-token", required=True, help="Bearer JWT token for authentication")
    p.add_argument("--n-sessions", type=int, default=20, help="Number of sessions to create (1-200, default 20)")
    p.add_argument("--segments-per-session", type=int, default=3, help="Segments per session (1-20, default 3)")
    p.add_argument("--quiz-accuracy", type=float, default=0.7, help="Target quiz accuracy 0.0-1.0 (default 0.7)")
    p.add_argument("--output", default="ces_synthetic_sessions.csv", help="Output CSV file path")
    p.add_argument("--lesson-id", default=None, help="Lesson UUID to attach sessions to (optional; uses placeholder if absent)")
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducible quiz answers")
    return p


def build_quiz_answers(
    n_questions: int,
    accuracy: float,
    seed: int | None = None,
    *,
    segment_id: str = "seg-0",
) -> list[dict[str, Any]]:
    """Build N quiz answer payloads with the given accuracy rate.

    Raises ValueError if n_questions < 1 or accuracy outside [0.0, 1.0].
    """
    if n_questions < 1:
        raise ValueError(f"n_questions must be >= 1, got {n_questions}")
    if not (0.0 <= accuracy <= 1.0):
        raise ValueError(f"accuracy must be in [0.0, 1.0], got {accuracy}")

    rng = random.Random(seed)  # noqa: S311 — quiz answer randomisation, not crypto
    answers = []
    for i in range(n_questions):
        is_correct = rng.random() < accuracy
        # response_index: 0 = correct answer slot, 1/2/3 = wrong
        response_index = 0 if is_correct else rng.randint(1, 3)
        response_time_ms = max(500, int(rng.gauss(8000, 4000)))  # min floor 500ms (AC 1)
        answers.append({
            "question_id": f"{segment_id}-q{i}",
            "response_index": response_index,
            "response_time_ms": response_time_ms,
            "is_correct": is_correct,  # informational only — not sent to API
        })
    return answers


def build_teachback_payload(segment_id: str, *, skip: bool = False) -> dict[str, Any]:
    """Build a teachback submission payload."""
    return {
        "segment_id": segment_id,
        "response_text": "" if skip else _STUB_TEACHBACK,
        "is_skip": skip,
    }


def write_summary_csv(rows: list[dict[str, Any]], dest: str | Any) -> None:  # noqa: ANN401
    """Write session summary rows to dest (file-like or path string)."""
    fieldnames = [
        "session_id",
        "quiz_accuracy_pct",
        "teachback_avg_score",
        "ces_final",
        "n_quiz_attempts",
        "n_teachback_attempts",
    ]
    opener = open(dest, "w", newline="", encoding="utf-8") if isinstance(dest, str) else None
    fd = opener if opener else dest
    try:
        writer = csv.DictWriter(fd, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if opener:
            opener.close()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _run_session(
    client: httpx.Client,
    api_url: str,
    token: str,
    lesson_id: str,
    n_segments: int,
    quiz_accuracy: float,
    seed: int | None,
    session_idx: int,
) -> dict[str, Any]:
    """Run one synthetic session. Returns a summary row dict."""
    hdrs = _headers(token)
    base = api_url.rstrip("/")

    # 1. Create session
    resp = client.post(
        f"{base}/api/assessment/sessions",
        json={"lesson_id": lesson_id},
        headers=hdrs,
        timeout=15.0,
    )
    resp.raise_for_status()
    session_id = resp.json()["id"]

    quiz_correct = 0
    quiz_total = 0
    teachback_scores: list[int] = []

    # 2. Per-segment: quiz + teachback
    for seg_i in range(n_segments):
        segment_id = f"seg-{seg_i}"
        seg_seed = None if seed is None else seed * 1000 + session_idx * 100 + seg_i

        # Quiz
        answers = build_quiz_answers(
            n_questions=2, accuracy=quiz_accuracy, seed=seg_seed, segment_id=segment_id
        )
        api_answers = [
            {k: v for k, v in a.items() if k != "is_correct"}
            for a in answers
        ]
        quiz_resp = client.post(
            f"{base}/api/assessment/quiz",
            json={"session_id": session_id, "segment_id": segment_id, "answers": api_answers},
            headers=hdrs,
            timeout=15.0,
        )
        if quiz_resp.status_code == 200:
            quiz_correct += sum(1 for a in answers if a["is_correct"])
            quiz_total += len(answers)

        # Teachback
        tb_payload = build_teachback_payload(segment_id)
        tb_resp = client.post(
            f"{base}/api/assessment/teachback",
            json={"session_id": session_id, **tb_payload},
            headers=hdrs,
            timeout=30.0,
        )
        if tb_resp.status_code == 200:
            score = tb_resp.json().get("score")
            if score is not None:
                teachback_scores.append(score)

        time.sleep(0.1)  # gentle pacing

    # 3. Complete session
    complete_resp = client.post(
        f"{base}/api/assessment/sessions/{session_id}/complete",
        json={},
        headers=hdrs,
        timeout=15.0,
    )

    # 4. Fetch ces_final from completed session (may be NULL if WS signals not received)
    ces_final = None
    if complete_resp.status_code == 200:
        ces_final = complete_resp.json().get("ces_final")

    return {
        "session_id": session_id,
        "quiz_accuracy_pct": round((quiz_correct / quiz_total * 100) if quiz_total else 0.0, 2),
        "teachback_avg_score": round(sum(teachback_scores) / len(teachback_scores), 2) if teachback_scores else None,
        "ces_final": ces_final,
        "n_quiz_attempts": quiz_total,
        "n_teachback_attempts": len(teachback_scores),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not (1 <= args.n_sessions <= 200):
        print(f"ERROR: --n-sessions must be 1–200, got {args.n_sessions}", file=sys.stderr)
        return 2
    if not (1 <= args.segments_per_session <= 20):
        print(f"ERROR: --segments-per-session must be 1–20, got {args.segments_per_session}", file=sys.stderr)
        return 2
    if not (0.0 <= args.quiz_accuracy <= 1.0):
        print(f"ERROR: --quiz-accuracy must be 0.0–1.0, got {args.quiz_accuracy}", file=sys.stderr)
        return 2

    lesson_id = args.lesson_id or str(uuid.uuid4())
    print(f"Generating {args.n_sessions} sessions (lesson={lesson_id}, segments={args.segments_per_session})")

    rows: list[dict[str, Any]] = []
    failed = 0

    with httpx.Client() as client:
        for i in range(args.n_sessions):
            try:
                row = _run_session(
                    client=client,
                    api_url=args.api_url,
                    token=args.auth_token,
                    lesson_id=lesson_id,
                    n_segments=args.segments_per_session,
                    quiz_accuracy=args.quiz_accuracy,
                    seed=args.seed,
                    session_idx=i,
                )
                rows.append(row)
                print(f"  [{i+1}/{args.n_sessions}] session={row['session_id'][:8]}... "
                      f"quiz={row['quiz_accuracy_pct']}% ces_final={row['ces_final']}")
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i+1}/{args.n_sessions}] FAILED: {exc}", file=sys.stderr)
                failed += 1

    write_summary_csv(rows, args.output)
    print(f"\nDone. {len(rows)} sessions written to {args.output}. {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
