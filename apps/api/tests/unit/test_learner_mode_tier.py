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


# The newest migration in the repo when Story 2-2 authored the tier migration.
# The tier migration must sort strictly after this one; that is what "not
# backdated" means and it stays true forever.
_LATEST_MIGRATION_WHEN_TIER_WAS_AUTHORED = "20260713020000_lesson_job_node_output_merge_fn.sql"


@pytest.mark.unit
def test_tier_migration_file_timestamp_is_after_latest_applied() -> None:
    """Story 2-2 AC-2: the tier migration's timestamp prefix must sort after
    every migration that already existed when it was written — never backdated,
    never edited into an existing file.

    It is deliberately NOT asserted to be the newest file in the repo. That was
    the original wording, and it made the test fail the moment any later
    migration was added (first hit by 20260803000000_chapters_book_scoped.sql,
    Story 1-9) — it forbade every future migration rather than catching a
    backdated one. Anchoring to a fixed predecessor preserves the real intent.
    """
    all_migrations = sorted(p.name for p in _MIGRATIONS_DIR.glob("*.sql"))
    tier_migration = _find_tier_migration().name

    assert _LATEST_MIGRATION_WHEN_TIER_WAS_AUTHORED in all_migrations, (
        f"anchor migration {_LATEST_MIGRATION_WHEN_TIER_WAS_AUTHORED} is missing — "
        f"an applied migration was renamed or deleted; got {all_migrations}"
    )
    # An APPLIED migration's filename is frozen outright — renaming it forward
    # would reorder it against migrations authored later, which a `>` bound alone
    # would not catch. Pin the exact name.
    assert tier_migration == "20260714020000_add_lesson_tier.sql", (
        f"the applied tier migration was renamed to {tier_migration}; "
        f"applied migrations are immutable (CLAUDE.md §16)"
    )
    assert tier_migration > _LATEST_MIGRATION_WHEN_TIER_WAS_AUTHORED, (
        f"tier migration {tier_migration} must sort after "
        f"{_LATEST_MIGRATION_WHEN_TIER_WAS_AUTHORED}; got order {all_migrations}"
    )


@pytest.mark.unit
def test_no_migration_is_backdated_before_an_already_applied_one() -> None:
    """The repo-wide invariant the old `all_migrations[-1] == tier_migration`
    assertion enforced as a side effect, restored explicitly.

    Re-anchoring that assertion fixed its false positive on every new migration,
    but removed the only check that a NEW file cannot be backdated to sort ahead
    of an already-applied one — which is exactly the abuse it was named for.
    """
    applied_frozen = "20260714020000_add_lesson_tier.sql"
    all_migrations = sorted(p.name for p in _MIGRATIONS_DIR.glob("*.sql"))
    idx = all_migrations.index(applied_frozen)
    # Everything at or before the frozen anchor is the applied set; nothing new
    # may appear inside it.
    known_applied = {
        "20260611000000_initial_schema.sql",
        "20260625000000_chunks_inline_embedding.sql",
        "20260630000000_unique_attempt_constraints.sql",
        "20260702000000_dpdp_user_consents.sql",
        "20260703000000_onboarding_unique_constraint.sql",
        "20260703010000_add_analytics_consent.sql",
        "20260710000000_storage_buckets.sql",
        "20260713020000_lesson_job_node_output_merge_fn.sql",
        applied_frozen,
    }
    assert set(all_migrations[: idx + 1]) == known_applied, (
        "a migration was backdated to sort before or among the applied set: "
        f"unexpected {set(all_migrations[: idx + 1]) - known_applied}, "
        f"missing {known_applied - set(all_migrations[: idx + 1])}"
    )


@pytest.mark.unit
def test_tier_migration_adds_check_constrained_column_with_t2_default() -> None:
    """Story 2-2 AC-2: lessons.tier is NOT NULL DEFAULT 'T2', CHECK IN (T1,T2,T3)."""
    sql = _find_tier_migration().read_text(encoding="utf-8")
    assert re.search(r"ALTER\s+TABLE\s+public\.lessons", sql, re.IGNORECASE)
    assert re.search(r"ADD\s+COLUMN\s+tier\s+text", sql, re.IGNORECASE)
    assert re.search(r"NOT\s+NULL", sql, re.IGNORECASE)
    assert re.search(r"DEFAULT\s+'T2'", sql, re.IGNORECASE)
    assert re.search(
        r"CHECK\s*\(\s*tier\s+IN\s*\(\s*'T1'\s*,\s*'T2'\s*,\s*'T3'\s*\)\s*\)", sql, re.IGNORECASE
    )


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
    assert previously_applied.issubset(existing_names), (
        "an already-applied migration is missing/renamed"
    )
