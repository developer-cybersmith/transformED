"""
Dev 4 sprint tracker auto-checker.

Scans the codebase for evidence that each task is done, then rewrites
docs/dev4-websocket-tutor-tracker.md with updated [x] / [ ] checkboxes.

Usage:
    python scripts/check_dev4_progress.py          # update tracker + print summary
    python scripts/check_dev4_progress.py --dry-run  # print results, do not write file
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── Repo root (one level above scripts/) ────────────────────────────────────
ROOT = Path(__file__).parent.parent
API = ROOT / "apps" / "api" / "app"
TRACKER = ROOT / "docs" / "dev4-websocket-tutor-tracker.md"


# ── Check helpers ─────────────────────────────────────────────────────────────


def file_exists(*parts: str) -> bool:
    return (ROOT / Path(*parts)).exists()


def file_contains(path_parts: tuple[str, ...], *patterns: str) -> bool:
    """Return True if the file contains ALL of the given patterns."""
    p = ROOT / Path(*path_parts)
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8", errors="ignore")
    return all(pat in text for pat in patterns)


def any_file_contains(glob: str, *patterns: str) -> bool:
    """Return True if ANY file matching glob contains ALL patterns."""
    for f in ROOT.glob(glob):
        text = f.read_text(encoding="utf-8", errors="ignore")
        if all(pat in text for pat in patterns):
            return True
    return False


# ── Task definitions ─────────────────────────────────────────────────────────
# Each entry: (check_tag, human_label, check_fn)
# check_tag matches <!-- CHECK:tag --> in the tracker markdown.

CHECKS: list[tuple[str, str, bool]] = []


def _check(tag: str, label: str) -> bool:
    """Run the check for a given tag and return True if done."""
    checks_map = _build_checks()
    fn = checks_map.get(tag)
    if fn is None:
        return False
    return fn()


def _build_checks() -> dict[str, object]:
    return {
        # ── Sprint 0 ──────────────────────────────────────────────────────────
        "ws_handler_scaffold": lambda: (
            file_contains(
                ("apps", "api", "app", "core", "websocket.py"),
                "class ConnectionManager",
                "ws_router",
                "attention_signal",
            )
            and file_contains(
                ("apps", "api", "app", "main.py"),
                "ws_router",
            )
        ),
        "jwt_middleware": lambda: file_contains(
            ("apps", "api", "app", "dependencies.py"),
            "jwt.decode",
            "supabase_jwt_secret",
            "get_current_user",
            "CurrentUser",
        ),
        "redis_lpush_pattern": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "ces_history",
            "lpush",
        )
        or any_file_contains(
            "apps/api/app/**/*.py",
            "ces_history",
            "LPUSH",
        ),
        "langgraph_scaffold": lambda: file_contains(
            ("apps", "api", "app", "modules", "tutor", "state_machine", "graph.py"),
            "TutorState",
            "IDLE",
            "TEACHING",
            "INTERVENING",
            "CHECKING_IN",
            "QUIZZING",
            "TEACH_BACK",
            "SESSION_END",
            "dispatch_event",
            "MemorySaver",
        ),
        "tutor_stub": lambda: (
            file_contains(
                ("apps", "api", "app", "modules", "tutor", "router.py"),
                "TutorSessionState",
                "InterventionRequest",
                "/session/{session_id}/state",
            )
            and file_contains(
                ("apps", "api", "app", "main.py"),
                "tutor_router",
            )
        ),
        "mock_ws_client": lambda: (
            file_exists("scripts", "mock_ws_client.py")
            or any_file_contains("tests/**/*.py", "websocket", "attention_signal", "ws://")
        ),
        "sentry_wired": lambda: file_contains(
            ("apps", "api", "app", "main.py"),
            "sentry_sdk.init",
            "sentry_dsn",
        ),
        # ── Sprint 1 ──────────────────────────────────────────────────────────
        "jwt_all_routes": lambda: any_file_contains(
            "tests/**/*.py",
            "401",
            "Authorization",
            "CurrentUser",
        ),
        "ws_message_routing": lambda: (
            file_exists("apps", "api", "app", "modules", "tutor", "service.py")
            and file_contains(
                ("apps", "api", "app", "modules", "tutor", "service.py"),
                "process_attention_signal",
            )
        ),
        # Needs Redis pub/sub publish in worker + subscribe in websocket layer
        # content_pipeline_job.py uses manager.send() directly (cross-process bug — won't work in prod)
        "arq_lesson_ready": lambda: any_file_contains(
            "apps/api/app/workers/**/*.py",
            "lesson_ready",
            "publish",
        ) or file_contains(
            ("apps", "api", "app", "core", "websocket.py"),
            "subscribe",
            "lesson_ready",
        ),
        "redis_signal_buffer": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "ces_history",
        ),
        # Requires service.py to call dispatch_event("session_start") AND websocket.py to handle it
        "idle_to_teaching": lambda: (
            file_exists("apps", "api", "app", "modules", "tutor", "service.py")
            and file_contains(
                ("apps", "api", "app", "modules", "tutor", "service.py"),
                "session_start",
                "dispatch_event",
            )
        ),
        # Requires ConnectionManager.connect() or a helper to init Redis keys on WS connect
        "session_state_init": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "init_session_state",
        ) or (
            file_exists("apps", "api", "app", "modules", "tutor", "service.py")
            and file_contains(
                ("apps", "api", "app", "modules", "tutor", "service.py"),
                "tutor_distraction_count:",
                "tutor_cooldown:",
                "delete",
            )
        ),
        "session_redis_persistence": lambda: file_contains(
            ("apps", "api", "app", "modules", "tutor", "state_machine", "graph.py"),
            "_STATE_TTL",
            "ex=_STATE_TTL",
        ),
        # ── Sprint 2 ──────────────────────────────────────────────────────────
        "full_state_machine": lambda: (
            file_contains(
                ("apps", "api", "app", "modules", "tutor", "state_machine", "graph.py"),
                "intervention_messages",
            )
            and file_exists("apps", "api", "app", "modules", "tutor", "service.py")
        ),
        "all_transitions": lambda: any_file_contains(
            "tests/**/*.py",
            "dispatch_event",
            "INTERVENING",
            "TEACH_BACK",
        ),
        # Requires websocket.py to dispatch segment_complete/quiz_failed/teachback_complete message types
        # graph.py has routing logic but websocket.py only handles "attention_signal" and "ping"
        "quizzing_teachback_flow": lambda: file_contains(
            ("apps", "api", "app", "core", "websocket.py"),
            "segment_complete",
            "quiz_failed",
            "teachback_complete",
        ),
        "session_restore": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "state_sync",
        ),
        "intervention_selection": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "intervention_messages",
            "intervention_type",
        ),
        "ws_message_types_final": lambda: file_exists("docs", "ws-message-contract.md"),
        # ── Sprint 3 ──────────────────────────────────────────────────────────
        "attention_ingestion": lambda: (
            file_exists("apps", "api", "app", "modules", "tutor", "service.py")
            and file_contains(
                ("apps", "api", "app", "modules", "tutor", "service.py"),
                "process_attention_signal",
                "ces_history",
            )
        ),
        "ces_redis_buffer": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "ces_window",
            "ltrim",
        ),
        "ces_computation": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "compute_ces",
            "tutor_ces:",
        ),
        "intervention_trigger": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            "distraction_detected",
            "ces_history",
        ),
        "cooldown_enforcement": lambda: file_contains(
            ("apps", "api", "app", "modules", "tutor", "state_machine", "graph.py"),
            "tutor_cooldown:",
            "intervention_cooldown_seconds",
        ),
        "max_distraction_cap": lambda: (
            file_contains(
                ("apps", "api", "app", "modules", "tutor", "state_machine", "graph.py"),
                "max_distraction_per_session",
                "tutor_distraction_count:",
            )
            and any_file_contains(
                "tests/**/*.py",
                "distraction_count",
                "max_distraction",
            )
        ),
        "fatigue_once": lambda: (
            file_contains(
                ("apps", "api", "app", "modules", "tutor", "state_machine", "graph.py"),
                "tutor_fatigue_fired:",
            )
            and any_file_contains(
                "tests/**/*.py",
                "fatigue",
                "fatigue_fired",
            )
        ),
        "intervention_routing": lambda: any_file_contains(
            "apps/api/app/**/*.py",
            '"distraction"',
            '"fatigue"',
            '"encouragement"',
        ),
        # ── Sprint 4 ──────────────────────────────────────────────────────────
        "threshold_tuning": lambda: file_exists("docs", "sprint4-ces-threshold-analysis.md"),
        "intervention_response_review": lambda: file_exists("docs", "sprint4-intervention-review.md"),
        "cooldown_tuning": lambda: file_exists("docs", "sprint4-cooldown-tuning.md"),
        "ws_load_test": lambda: file_exists("docs", "sprint4-ws-load-test.md"),
        "reconnect_test": lambda: any_file_contains(
            "tests/**/*.py",
            "reconnect",
            "state_sync",
        ),
        "intervention_copy_review": lambda: file_exists("docs", "sprint4-intervention-copy-review.md"),
        # ── Week 10 ───────────────────────────────────────────────────────────
        "ws_launch_stability": lambda: file_exists("docs", "week10-ws-launch-sign-off.md"),
        "interventions_production": lambda: file_exists("docs", "week10-intervention-verification.md"),
    }


# ── Tracker updater ───────────────────────────────────────────────────────────


def run_all_checks() -> dict[str, bool]:
    checks_map = _build_checks()
    results: dict[str, bool] = {}
    for tag, fn in checks_map.items():
        try:
            results[tag] = bool(fn())
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] check '{tag}' raised: {exc}", file=sys.stderr)
            results[tag] = False
    return results


def update_tracker(results: dict[str, bool], dry_run: bool = False) -> str:
    """Read tracker, flip checkboxes based on results, return updated content."""
    if not TRACKER.exists():
        print(f"ERROR: tracker not found at {TRACKER}", file=sys.stderr)
        sys.exit(1)

    content = TRACKER.read_text(encoding="utf-8")

    for tag, done in results.items():
        # Find the <!-- CHECK:tag --> marker and the checkbox line immediately after
        pattern = rf"(<!-- CHECK:{re.escape(tag)} -->\n)(- \[[ x]\])"
        replacement = rf"\g<1>- [{'x' if done else ' '}]"
        content = re.sub(pattern, replacement, content)

    if not dry_run:
        TRACKER.write_text(content, encoding="utf-8")

    return content


# ── Summary printer ───────────────────────────────────────────────────────────

SPRINT_TAGS: dict[str, list[str]] = {
    "Sprint 0": [
        "ws_handler_scaffold",
        "jwt_middleware",
        "redis_lpush_pattern",
        "langgraph_scaffold",
        "tutor_stub",
        "mock_ws_client",
        "sentry_wired",
    ],
    "Sprint 1": [
        "jwt_all_routes",
        "ws_message_routing",
        "arq_lesson_ready",
        "redis_signal_buffer",
        "idle_to_teaching",
        "session_state_init",
        "session_redis_persistence",
    ],
    "Sprint 2": [
        "full_state_machine",
        "all_transitions",
        "quizzing_teachback_flow",
        "session_restore",
        "intervention_selection",
        "ws_message_types_final",
    ],
    "Sprint 3": [
        "attention_ingestion",
        "ces_redis_buffer",
        "ces_computation",
        "intervention_trigger",
        "cooldown_enforcement",
        "max_distraction_cap",
        "fatigue_once",
        "intervention_routing",
    ],
    "Sprint 4": [
        "threshold_tuning",
        "intervention_response_review",
        "cooldown_tuning",
        "ws_load_test",
        "reconnect_test",
        "intervention_copy_review",
    ],
    "Week 10": [
        "ws_launch_stability",
        "interventions_production",
    ],
}

TASK_LABELS: dict[str, str] = {
    "ws_handler_scaffold": "FastAPI WebSocket handler scaffold",
    "jwt_middleware": "Local JWT middleware (PyJWT + SUPABASE_JWT_SECRET)",
    "redis_lpush_pattern": "Redis LPUSH/LTRIM/LRANGE CES signal buffer pattern",
    "langgraph_scaffold": "LangGraph StateGraph scaffold (7 state nodes)",
    "tutor_stub": "Tutor module stub in FastAPI",
    "mock_ws_client": "Mock WebSocket client for local testing",
    "sentry_wired": "Sentry wired to FastAPI error handler",
    "jwt_all_routes": "JWT middleware live and tested on all routes",
    "ws_message_routing": "WebSocket connection + message type routing",
    "arq_lesson_ready": "Lesson progress push (ARQ pub/sub → WebSocket)",
    "redis_signal_buffer": "Redis signal buffer operational (LPUSH/LTRIM/LRANGE)",
    "idle_to_teaching": "IDLE → TEACHING state transition live",
    "session_state_init": "Session state init on lesson start",
    "session_redis_persistence": "Session state Redis persistence (24h TTL)",
    "full_state_machine": "Full 7-state LangGraph StateGraph with real logic",
    "all_transitions": "All 14 transitions wired and tested",
    "quizzing_teachback_flow": "CHECKING_IN → QUIZZING → TEACH_BACK → TEACHING flow",
    "session_restore": "Session state restore on reconnect tested",
    "intervention_selection": "Intervention message selection from lesson package",
    "ws_message_types_final": "WebSocket message types finalised and published",
    "attention_ingestion": "Attention signal ingestion from WebSocket live",
    "ces_redis_buffer": "Redis CES buffer (LPUSH/LTRIM/LRANGE) computing every 5s",
    "ces_computation": "CES computation in-process (~3–5ms total)",
    "intervention_trigger": "Intervention trigger: 2 consecutive windows below threshold",
    "cooldown_enforcement": "2-minute cooldown enforcement (Redis TTL key)",
    "max_distraction_cap": "Max 3 distraction interventions per session cap",
    "fatigue_once": "Fatigue intervention: once per session flag",
    "intervention_routing": "Type A/B/C intervention routing to correct message",
    "threshold_tuning": "Intervention threshold tuning (is CES<50 right?)",
    "intervention_response_review": "Review which interventions students responded to vs ignored",
    "cooldown_tuning": "Cooldown period tuning from real session data",
    "ws_load_test": "WebSocket stability testing under 50 concurrent users",
    "reconnect_test": "Session reconnect testing under poor network conditions",
    "intervention_copy_review": "Intervention message copy review (tone + warmth)",
    "ws_launch_stability": "WebSocket stability confirmed at launch load",
    "interventions_production": "Tutor interventions verified firing correctly in production",
}


def print_summary(results: dict[str, bool]) -> None:
    print("\n── Dev 4 Sprint Progress ──────────────────────────────────────────")
    total_done = 0
    total_tasks = 0
    for sprint, tags in SPRINT_TAGS.items():
        done = sum(1 for t in tags if results.get(t))
        total_done += done
        total_tasks += len(tags)
        bar = "█" * done + "░" * (len(tags) - done)
        print(f"\n  {sprint} ({done}/{len(tags)})  [{bar}]")
        for tag in tags:
            status = "✅" if results.get(tag) else "⬜"
            label = TASK_LABELS.get(tag, tag)
            print(f"    {status}  {label}")
    pct = int(100 * total_done / total_tasks) if total_tasks else 0
    print(f"\n  Overall: {total_done}/{total_tasks} tasks done ({pct}%)")
    print("──────────────────────────────────────────────────────────────────\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Force UTF-8 output on Windows so Unicode symbols print correctly
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Auto-check Dev 4 sprint tracker")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing file")
    args = parser.parse_args()

    print("Scanning codebase…")
    results = run_all_checks()
    print_summary(results)

    if args.dry_run:
        print("Dry-run mode — tracker not updated.")
    else:
        update_tracker(results, dry_run=False)
        print(f"✅  Tracker updated: {TRACKER.relative_to(ROOT)}")
