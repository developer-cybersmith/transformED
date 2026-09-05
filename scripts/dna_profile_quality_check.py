"""
Learner DNA profile quality checker (Story 4-33).

Reads all learner_dna rows from Supabase and evaluates each profile_text
against 5 quality criteria mandated by CLAUDE.md and Epic 3.

Usage:
    SUPABASE_URL=https://... SUPABASE_SERVICE_KEY=... python scripts/dna_profile_quality_check.py

Exit code 0 = all PASS. Exit code 1 = at least one FAIL.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from supabase import create_client, Client  # type: ignore[import]

# Import the real disclaimer text rather than duplicating it — a hardcoded copy here
# drifted from app.modules.assessment.prompts.DPDP_DISCLAIMER and would have made this
# check FAIL on every real, compliant profile (checked substring never actually appears).
from app.modules.assessment.prompts import DPDP_DISCLAIMER

# ---------------------------------------------------------------------------
# Criteria definitions
# ---------------------------------------------------------------------------

BANNED_TERMS = [
    "iq", "eq", "sq",
    "intelligence quotient",
    "emotional quotient",
    "self-direction quotient",
    "clinical",
    "diagnostic",
    "disorder",
    "deficit",
    "intelligence test",
]

SCORE_PATTERN = re.compile(r"\b\d{2,3}(\.\d+)?(/100)?\b")
BADGE_SCORE_PATTERN = re.compile(r"[A-Z]{2,}:\s*\d")

DISCLAIMER_MIN_LEN = 50
DISCLAIMER_MAX_LEN = 800


def check_profile(row: dict) -> list[dict]:
    """Return list of {criterion, status, detail} for a single profile row."""
    results = []
    profile_text = row.get("profile_text") or ""
    badge_labels = row.get("badge_labels") or []

    # --- Criterion 1: DPDP disclaimer -----------------------------------------
    dpdp_ok = DPDP_DISCLAIMER.lower() in profile_text.lower()
    results.append(
        {
            "criterion": "DPDP disclaimer",
            "status": "PASS" if dpdp_ok else "FAIL",
            "detail": "" if dpdp_ok else "Missing DPDP disclaimer at end of profile_text",
        }
    )

    # --- Criterion 2: No banned terms -----------------------------------------
    text_lower = profile_text.lower()
    found_banned = [t for t in BANNED_TERMS if t in text_lower]
    # Also check badge_labels
    for bl in badge_labels:
        for t in BANNED_TERMS:
            if t in bl.lower() and t not in found_banned:
                found_banned.append(f"{t} (in badge_label: {bl!r})")

    results.append(
        {
            "criterion": "No banned terms",
            "status": "PASS" if not found_banned else "FAIL",
            "detail": f"Banned terms found: {found_banned}" if found_banned else "",
        }
    )

    # --- Criterion 3: No raw scores -------------------------------------------
    score_matches = SCORE_PATTERN.findall(profile_text)
    # Filter false positives: years (2026), version numbers
    suspicious = [
        m for m in score_matches
        if not re.match(r"202\d", m[0] if m else "")
    ]
    results.append(
        {
            "criterion": "No raw scores",
            "status": "WARN" if score_matches else "PASS",
            "detail": f"Possible raw score patterns: {score_matches[:5]}" if score_matches else "",
        }
    )

    # --- Criterion 4: Length check --------------------------------------------
    length = len(profile_text)
    if length < DISCLAIMER_MIN_LEN:
        length_status, length_detail = "WARN", f"Too short: {length} chars (min {DISCLAIMER_MIN_LEN})"
    elif length > DISCLAIMER_MAX_LEN:
        length_status, length_detail = "WARN", f"Too long: {length} chars (max {DISCLAIMER_MAX_LEN})"
    else:
        length_status, length_detail = "PASS", f"{length} chars"
    results.append(
        {"criterion": "Length (50–800 chars)", "status": length_status, "detail": length_detail}
    )

    # --- Criterion 5: Badge labels plain English ------------------------------
    bad_badges = [bl for bl in badge_labels if BADGE_SCORE_PATTERN.search(bl)]
    results.append(
        {
            "criterion": "Badge labels plain English",
            "status": "PASS" if not bad_badges else "FAIL",
            "detail": f"Non-plain badge labels: {bad_badges}" if bad_badges else "",
        }
    )

    return results


def print_report(profiles: list[dict], all_results: list[list[dict]]) -> bool:
    """Print report and return True if any profile FAILed."""
    total = len(profiles)
    fail_count = warn_count = pass_count = 0

    print("\n" + "=" * 90)
    print("LEARNER DNA PROFILE QUALITY REPORT")
    print("=" * 90)

    any_fail = False

    for i, (row, criteria) in enumerate(zip(profiles, all_results)):
        uid = (row.get("user_id") or "unknown")[:12] + "…"
        row_fails = [c for c in criteria if c["status"] == "FAIL"]
        row_warns = [c for c in criteria if c["status"] == "WARN"]
        row_status = "FAIL" if row_fails else ("WARN" if row_warns else "PASS")

        if row_status == "FAIL":
            fail_count += 1
            any_fail = True
        elif row_status == "WARN":
            warn_count += 1
        else:
            pass_count += 1

        print(f"\n[{i+1:02d}] user_id={uid}  overall={row_status}")
        for c in criteria:
            icon = "✓" if c["status"] == "PASS" else ("⚠" if c["status"] == "WARN" else "✗")
            line = f"     {icon} {c['criterion']:<30} {c['status']}"
            if c["detail"]:
                line += f"  →  {c['detail'][:60]}"
            print(line)

    print("\n" + "=" * 90)
    print(f"Total profiles reviewed: {total}")
    print(f"  PASS: {pass_count}  |  WARN: {warn_count}  |  FAIL: {fail_count}")
    print("=" * 90)

    if any_fail:
        print("\nACTION REQUIRED: Fix failing profiles before real-student launch.")
        print("Common fixes:")
        print("  - Missing DPDP disclaimer: add to profile generation prompt suffix in dna_profile.py")
        print("  - Banned terms: check TEACHBACK_SYSTEM_PROMPT and dna_profile.py generation prompt")
        print("  - Badge labels: ensure dna_fusion.py maps to plain-English labels only")

    return any_fail


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")

    sb = create_client(url, key)
    print("Fetching learner_dna profiles from Supabase…")

    resp = (
        sb.table("learner_dna")
        .select("user_id,profile_text,badge_labels,session_count,last_updated")
        .limit(500)  # BOUNDED: Sprint 4 has 0 real students; 500 adequate ceiling
        .execute()
    )
    profiles = resp.data or []

    if not profiles:
        print("No learner_dna profiles found. Run onboarding flow to generate profiles first.")
        sys.exit(0)

    print(f"Found {len(profiles)} profiles. Running quality checks…")

    all_results = [check_profile(row) for row in profiles]
    any_fail = print_report(profiles, all_results)

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
