"""
Unit tests for Story 2-2 (Learner Mode infra): tier contract + migration.

Tasks 3 (POST /lessons endpoint) and 4 (pipeline plumbing) were reverted from
this branch per the 2026-07-14 code review decision — AC-1 requires 4-developer
sign-off on the frozen-contract change before those tasks proceed. Only Tasks 1
(contract) and 2 (migration) remain implemented; their tests stay here.

Static-only migration check (no live Postgres) — mirrors the pattern
established by test_bucket_manifest.py's manifest crosscheck: read the raw
SQL file text and assert the constraints textually rather than executing SQL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


# ---------------------------------------------------------------------------
# Task 2 — lessons.tier migration (AC-2)
# ---------------------------------------------------------------------------


def _find_tier_migration() -> Path:
    candidates = sorted(_MIGRATIONS_DIR.glob("*_add_lesson_tier.sql"))
    assert candidates, (
        f"expected a migration file matching *_add_lesson_tier.sql under {_MIGRATIONS_DIR}"
    )
    return candidates[0]


@pytest.mark.unit
def test_tier_migration_file_timestamp_is_after_latest_applied() -> None:
    """Story 2-2 AC-2: the new migration's timestamp prefix must sort after
    every other already-applied migration — never backdated, never edited
    into an existing file."""
    all_migrations = sorted(p.name for p in _MIGRATIONS_DIR.glob("*.sql"))
    tier_migration = _find_tier_migration().name
    assert all_migrations[-1] == tier_migration, (
        f"tier migration must be the newest by filename sort; got order {all_migrations}"
    )


@pytest.mark.unit
def test_tier_migration_adds_check_constrained_column_with_t2_default() -> None:
    """Story 2-2 AC-2: lessons.tier is NOT NULL DEFAULT 'T2', CHECK IN (T1,T2,T3)."""
    sql = _find_tier_migration().read_text(encoding="utf-8")
    assert re.search(r"ALTER\s+TABLE\s+public\.lessons", sql, re.IGNORECASE)
    assert re.search(r"ADD\s+COLUMN\s+tier\s+text", sql, re.IGNORECASE)
    assert re.search(r"NOT\s+NULL", sql, re.IGNORECASE)
    assert re.search(r"DEFAULT\s+'T2'", sql, re.IGNORECASE)
    assert re.search(r"CHECK\s*\(\s*tier\s+IN\s*\(\s*'T1'\s*,\s*'T2'\s*,\s*'T3'\s*\)\s*\)", sql, re.IGNORECASE)


@pytest.mark.unit
def test_no_existing_applied_migration_was_modified() -> None:
    """Story 2-2 AC-2: none of the 7 previously-applied migrations are touched."""
    previously_applied = {
        "20260611000000_initial_schema.sql",
        "20260625000000_chunks_inline_embedding.sql",
        "20260630000000_unique_attempt_constraints.sql",
        "20260702000000_dpdp_user_consents.sql",
        "20260703000000_onboarding_unique_constraint.sql",
        "20260703010000_add_analytics_consent.sql",
        "20260710000000_storage_buckets.sql",
        "20260713020000_lesson_job_node_output_merge_fn.sql",
    }
    existing_names = {p.name for p in _MIGRATIONS_DIR.glob("*.sql")}
    assert previously_applied.issubset(existing_names), "an already-applied migration is missing/renamed"

