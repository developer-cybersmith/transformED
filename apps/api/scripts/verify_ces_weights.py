"""
S4-32: CES weight verification script.

Reads CES weight env vars from the running API's config endpoint (or from local
environment) and checks them against the S4-31 tuned targets.

No app.* imports — standalone script.

Usage:
    # Check local env vars directly (no running API needed):
    python apps/api/scripts/verify_ces_weights.py --local

    # Check via running API config endpoint:
    python apps/api/scripts/verify_ces_weights.py \
        --api-url http://localhost:8000 \
        --auth-token <bearer-token>

Exit codes:
    0 — all weights match S4-31 targets
    1 — one or more weights mismatch
    2 — argument error or API unreachable
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

# S4-31 target weights (must sum to 1.0)
TARGETS: dict[str, float] = {
    "ces_weight_quiz": 0.40,
    "ces_weight_teachback": 0.25,
    "ces_weight_behavioral": 0.15,
    "ces_weight_head_pose": 0.13,
    "ces_weight_blink": 0.07,
}

# Env var name mapping (Railway env var → config field)
_ENV_MAP: dict[str, str] = {
    "CES_WEIGHT_QUIZ": "ces_weight_quiz",
    "CES_WEIGHT_TEACHBACK": "ces_weight_teachback",
    "CES_WEIGHT_BEHAVIORAL": "ces_weight_behavioral",
    "CES_WEIGHT_HEAD_POSE": "ces_weight_head_pose",
    "CES_WEIGHT_BLINK": "ces_weight_blink",
}

_TOLERANCE = 1e-6


def read_weights_from_env() -> dict[str, float | None]:
    """Read CES weights from environment variables."""
    result: dict[str, float | None] = {}
    for env_var, field in _ENV_MAP.items():
        raw = os.environ.get(env_var)
        if raw is None:
            result[field] = None
        else:
            try:
                result[field] = float(raw)
            except ValueError:
                result[field] = None
    return result


def read_weights_from_api(api_url: str, token: str) -> dict[str, float | None]:
    """Read CES weights from running API health/config endpoint."""
    try:
        import httpx
    except ImportError:
        print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
        sys.exit(2)

    base = api_url.rstrip("/")
    hdrs = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(f"{base}/api/health/config", headers=hdrs, timeout=10.0)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except Exception as exc:  # noqa: BLE001
        # Fallback: try /api/health (no auth)
        try:
            resp2 = httpx.get(f"{base}/api/health", timeout=10.0)
            resp2.raise_for_status()
            data = resp2.json()
        except Exception:
            print(f"ERROR: cannot reach API at {api_url}: {exc}", file=sys.stderr)
            sys.exit(2)

    result: dict[str, float | None] = {}
    for field in TARGETS:
        val = data.get(field) or data.get("config", {}).get(field)
        result[field] = float(val) if val is not None else None
    return result


def verify_weights(
    actual: dict[str, float | None],
    targets: dict[str, float] = TARGETS,
) -> tuple[bool, list[str]]:
    """Compare actual weights to targets. Returns (all_ok, list_of_issues)."""
    issues: list[str] = []
    for field, target in targets.items():
        got = actual.get(field)
        if got is None:
            issues.append(f"  {field}: NOT SET (expected {target}) — using config.py default")
        elif abs(got - target) > _TOLERANCE:
            issues.append(f"  {field}: got {got}, expected {target}")
    return len(issues) == 0, issues


def print_report(actual: dict[str, float | None], targets: dict[str, float] = TARGETS) -> bool:
    """Print verification report. Returns True if all weights match."""
    print("CES weight verification")
    print("-" * 40)
    all_ok = True
    total = 0.0
    for field, target in targets.items():
        got = actual.get(field)
        if got is None:
            mark = "~"  # using default
            display = f"(default: {target})"
            val_for_sum = target
        elif abs(got - target) <= _TOLERANCE:
            mark = "ok"
            display = str(got)
            val_for_sum = got
        else:
            mark = "MISMATCH"
            display = f"{got} (expected {target})"
            val_for_sum = got
            all_ok = False
        total += val_for_sum
        print(f"  {field:<30} {display:<12} [{mark}]")

    print(f"\n  Sum: {total:.6f}  {'[ok]' if abs(total - 1.0) < 1e-6 else '[MISMATCH — must be 1.0]'}")

    if all_ok:
        print("\nAll weights match S4-31 targets.")
    else:
        print("\nWARN: weight mismatch — see items above. Apply runbook: docs/sprint4-railway-env-update.md")
    return all_ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify CES weights match S4-31 targets.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--local", action="store_true", help="Read weights from local env vars only")
    group.add_argument("--api-url", help="API base URL (e.g. http://localhost:8000)")
    parser.add_argument("--auth-token", help="Bearer JWT token (required with --api-url)")
    args = parser.parse_args(argv)

    if args.api_url and not args.auth_token:
        print("ERROR: --auth-token required when using --api-url", file=sys.stderr)
        return 2

    if args.api_url:
        actual = read_weights_from_api(args.api_url, args.auth_token)
    else:
        # Default: read from local env vars
        actual = read_weights_from_env()

    ok = print_report(actual)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
