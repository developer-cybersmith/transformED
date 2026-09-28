"""Guard: DB CHECK constraints on free-text context fields.

Why this file exists
--------------------
Story 5-15 (2026-09-28) added CHECK (char_length(col) <= 500) constraints on
five columns across two tables — ``book_context`` (D178) and
``chapter_context`` (D190). The constraints mirror the Pydantic
``max_length=500`` validators that already exist at the API boundary.

This guard reads the migration file as text and asserts that each of the
five expected constraints is present with the correct column name and limit.
It runs at source-scan level — no DB connection, no imports of application
code — so it belongs in ``tests/unit/`` (the gating CI bucket).

Registered story: Story 5-15, 2026-09-28.
Fixes: D178 (book_context), D190 (chapter_context).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Migration file path (resolved once at module import time)
# ---------------------------------------------------------------------------

_MIGRATION_FILE = (
    Path(__file__).resolve().parents[4]
    / "supabase"
    / "migrations"
    / "20260928000000_text_field_check_constraints.sql"
)
_MIGRATION_SRC: str = _MIGRATION_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_constraint(constraint_name: str, column: str, limit: int = 500) -> bool:
    """Return True if the migration defines a CHECK constraint with the given
    name, column, and char_length limit."""
    pattern = (
        rf"CONSTRAINT\s+{re.escape(constraint_name)}"
        rf".*?CHECK\s*\(\s*char_length\s*\(\s*{re.escape(column)}\s*\)\s*<=\s*{limit}\s*\)"
    )
    return bool(re.search(pattern, _MIGRATION_SRC, re.DOTALL | re.IGNORECASE))


# ---------------------------------------------------------------------------
# book_context constraints (D178) — AC1, AC4
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_book_context_motivation_len_constraint() -> None:
    """Migration must define CHECK (char_length(motivation) <= 500) on book_context.

    D178: mirrors BookContextRequest.motivation max_length=500 at the DB layer.
    Constraint name 'book_context_motivation_len' is identifiable in Postgres
    error messages without consulting this migration. Story 5-15 AC1/AC4.
    """
    assert _has_constraint("book_context_motivation_len", "motivation"), (
        "Migration 20260928000000 is missing constraint 'book_context_motivation_len'.\n"
        "Expected: ADD CONSTRAINT book_context_motivation_len\n"
        "         CHECK (char_length(motivation) <= 500)\n"
        "D178 / Story 5-15 AC1."
    )


@pytest.mark.unit
def test_book_context_end_goal_len_constraint() -> None:
    """Migration must define CHECK (char_length(end_goal) <= 500) on book_context.

    D178 / Story 5-15 AC1/AC4.
    """
    assert _has_constraint("book_context_end_goal_len", "end_goal"), (
        "Migration 20260928000000 is missing constraint 'book_context_end_goal_len'.\n"
        "D178 / Story 5-15 AC1."
    )


@pytest.mark.unit
def test_book_context_feared_section_len_constraint() -> None:
    """Migration must define CHECK (char_length(feared_section) <= 500) on book_context.

    D178 / Story 5-15 AC1/AC4.
    """
    assert _has_constraint("book_context_feared_section_len", "feared_section"), (
        "Migration 20260928000000 is missing constraint 'book_context_feared_section_len'.\n"
        "D178 / Story 5-15 AC1."
    )


# ---------------------------------------------------------------------------
# chapter_context constraints (D190) — AC1, AC4
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chapter_context_specific_doubt_len_constraint() -> None:
    """Migration must define CHECK (char_length(specific_doubt) <= 500) on chapter_context.

    D190: mirrors ChapterContextRequest.specific_doubt max_length=500.
    Story 5-15 AC1/AC4.
    """
    assert _has_constraint("chapter_context_specific_doubt_len", "specific_doubt"), (
        "Migration 20260928000000 is missing constraint 'chapter_context_specific_doubt_len'.\n"
        "D190 / Story 5-15 AC1."
    )


@pytest.mark.unit
def test_chapter_context_goal_and_skip_len_constraint() -> None:
    """Migration must define CHECK (char_length(goal_and_skip) <= 500) on chapter_context.

    D190: mirrors ChapterContextRequest.goal_and_skip max_length=500.
    Story 5-15 AC1/AC4.
    """
    assert _has_constraint("chapter_context_goal_and_skip_len", "goal_and_skip"), (
        "Migration 20260928000000 is missing constraint 'chapter_context_goal_and_skip_len'.\n"
        "D190 / Story 5-15 AC1."
    )


# ---------------------------------------------------------------------------
# Migration file completeness — all five constraints in one file — AC1
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_covers_all_five_columns() -> None:
    """The migration file must reference all five constrained columns.

    Catches a partial migration where only some columns were added — the kind
    of omission that passes if each column is only tested individually but
    would silently half-fix D178 or D190.
    Story 5-15 AC1.
    """
    expected_columns = [
        "motivation",
        "end_goal",
        "feared_section",
        "specific_doubt",
        "goal_and_skip",
    ]
    missing = [c for c in expected_columns if c not in _MIGRATION_SRC]
    assert not missing, (
        f"Migration 20260928000000 is missing column references: {missing}\n"
        "All five constrained columns must appear in the migration. D178 + D190."
    )
