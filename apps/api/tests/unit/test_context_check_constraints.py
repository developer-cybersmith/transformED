"""Guard: source-scan of migration 20260928000000 — 5 CHECK constraints (D178 + D190)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_MIGRATION_FILE = (
    Path(__file__).resolve().parents[4]
    / "supabase"
    / "migrations"
    / "20260928000000_text_field_check_constraints.sql"
)

_LOAD_ERROR: str | None = None
try:
    _MIGRATION_SRC: str = _MIGRATION_FILE.read_text(encoding="utf-8")
except FileNotFoundError as _exc:
    _MIGRATION_SRC = ""
    _LOAD_ERROR = str(_exc)


@pytest.fixture(autouse=True)
def _require_migration_file() -> None:
    if _LOAD_ERROR is not None:
        pytest.fail(f"S5-15 guard: migration file not found — {_LOAD_ERROR}")


def _has_constraint(constraint_name: str, column: str, limit: int = 500) -> bool:
    pattern = (
        rf"CONSTRAINT\s+{re.escape(constraint_name)}"
        rf".*?CHECK\s*\(\s*char_length\s*\(\s*{re.escape(column)}\s*\)\s*<=\s*{limit}\s*\)"
    )
    return bool(re.search(pattern, _MIGRATION_SRC, re.DOTALL | re.IGNORECASE))


@pytest.mark.unit
def test_book_context_motivation_len_constraint() -> None:
    """D178: migration must define CHECK (char_length(motivation) <= 500) — AC1/AC4."""
    assert _has_constraint("book_context_motivation_len", "motivation")


@pytest.mark.unit
def test_book_context_end_goal_len_constraint() -> None:
    """D178: migration must define CHECK (char_length(end_goal) <= 500) — AC1/AC4."""
    assert _has_constraint("book_context_end_goal_len", "end_goal")


@pytest.mark.unit
def test_book_context_feared_section_len_constraint() -> None:
    """D178: migration must define CHECK (char_length(feared_section) <= 500) — AC1/AC4."""
    assert _has_constraint("book_context_feared_section_len", "feared_section")


@pytest.mark.unit
def test_chapter_context_specific_doubt_len_constraint() -> None:
    """D190: migration must define CHECK (char_length(specific_doubt) <= 500) — AC1/AC4."""
    assert _has_constraint("chapter_context_specific_doubt_len", "specific_doubt")


@pytest.mark.unit
def test_chapter_context_goal_and_skip_len_constraint() -> None:
    """D190: migration must define CHECK (char_length(goal_and_skip) <= 500) — AC1/AC4."""
    assert _has_constraint("chapter_context_goal_and_skip_len", "goal_and_skip")


@pytest.mark.unit
def test_migration_covers_all_five_columns() -> None:
    """Migration must reference all five constrained columns — catches partial migration (AC1)."""
    expected_columns = [
        "motivation",
        "end_goal",
        "feared_section",
        "specific_doubt",
        "goal_and_skip",
    ]
    missing = [c for c in expected_columns if c not in _MIGRATION_SRC]
    assert not missing, f"Migration missing column references: {missing}"
