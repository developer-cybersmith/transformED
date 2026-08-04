"""
Schema verification tests for the three Dev 3 assessment tables.

These tests parse the initial migration SQL file directly — no live DB connection required.
They verify that quiz_attempts, teachback_attempts, and learner_dna exist with the
correct columns, constraints, and RLS policies.

Run with:
    cd apps/api
    python -m pytest tests/test_migration_assessment_schema.py -v -m unit
"""

from __future__ import annotations

import pathlib
import re

import pytest

# Resolve migration path relative to this file's location:
# tests/ -> apps/api/ -> repo root -> supabase/migrations/
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent.parent
MIGRATION_PATH = _REPO_ROOT / "supabase" / "migrations" / "20260611000000_initial_schema.sql"
MIGRATION = MIGRATION_PATH.read_text(encoding="utf-8")

# ── Utility helpers ──────────────────────────────────────────────────────────


def _extract_table_block(table_name: str, migration: str, window: int = 3000) -> str:
    """Return up to `window` characters of the migration starting at the first
    occurrence of `table_name`. Used to scope assertions to a single table."""
    idx = migration.find(table_name)
    if idx == -1:
        return ""
    return migration[idx : idx + window]


# ════════════════════════════════════════════════════════════════════════════
# quiz_attempts
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_quiz_attempts_table_exists() -> None:
    """CREATE TABLE quiz_attempts is present in the migration."""
    assert "quiz_attempts" in MIGRATION


@pytest.mark.unit
def test_quiz_attempts_primary_key() -> None:
    """quiz_attempts has id UUID PRIMARY KEY."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "id" in block
    assert "uuid" in block.lower()
    assert "PRIMARY KEY" in block


@pytest.mark.unit
def test_quiz_attempts_session_id_fk() -> None:
    """quiz_attempts.session_id is NOT NULL with FK to sessions."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "session_id" in block
    assert "NOT NULL" in block
    assert "sessions" in block


@pytest.mark.unit
def test_quiz_attempts_session_id_on_delete_cascade() -> None:
    """quiz_attempts FK on session_id includes ON DELETE CASCADE."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "ON DELETE CASCADE" in block


@pytest.mark.unit
def test_quiz_attempts_has_segment_id() -> None:
    """quiz_attempts has segment_id TEXT NOT NULL."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "segment_id" in block
    assert "text" in block.lower()


@pytest.mark.unit
def test_quiz_attempts_has_question_id() -> None:
    """quiz_attempts has question_id TEXT NOT NULL."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "question_id" in block


@pytest.mark.unit
def test_quiz_attempts_has_response_index() -> None:
    """quiz_attempts has response_index integer (nullable)."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "response_index" in block


@pytest.mark.unit
def test_quiz_attempts_has_is_correct() -> None:
    """quiz_attempts has is_correct boolean."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "is_correct" in block
    assert "boolean" in block.lower()


@pytest.mark.unit
def test_quiz_attempts_has_response_time_ms() -> None:
    """quiz_attempts has response_time_ms integer."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "response_time_ms" in block


@pytest.mark.unit
def test_quiz_attempts_has_attempt_number_with_default() -> None:
    """quiz_attempts has attempt_number integer DEFAULT 1."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "attempt_number" in block
    assert "DEFAULT 1" in block


@pytest.mark.unit
def test_quiz_attempts_created_at_is_timestamptz() -> None:
    """quiz_attempts.created_at is TIMESTAMPTZ (timezone-aware)."""
    block = _extract_table_block("CREATE TABLE public.quiz_attempts", MIGRATION)
    assert "created_at" in block
    assert "timestamptz" in block.lower()


@pytest.mark.unit
def test_quiz_attempts_rls_enabled() -> None:
    """ROW LEVEL SECURITY is enabled on quiz_attempts."""
    assert re.search(
        r"ALTER TABLE public\.quiz_attempts\s+ENABLE ROW LEVEL SECURITY",
        MIGRATION,
        re.IGNORECASE,
    )


@pytest.mark.unit
def test_quiz_attempts_has_rls_policies() -> None:
    """All four CRUD RLS policies exist for quiz_attempts."""
    for operation in ("select", "insert", "update", "delete"):
        assert f"quiz_attempts: {operation} own" in MIGRATION.lower(), (
            f"Missing RLS policy for quiz_attempts {operation}"
        )


# ════════════════════════════════════════════════════════════════════════════
# teachback_attempts
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_teachback_attempts_table_exists() -> None:
    """CREATE TABLE teachback_attempts is present in the migration."""
    assert "teachback_attempts" in MIGRATION


@pytest.mark.unit
def test_teachback_attempts_primary_key() -> None:
    """teachback_attempts has id UUID PRIMARY KEY."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    assert "id" in block
    assert "PRIMARY KEY" in block


@pytest.mark.unit
def test_teachback_attempts_session_id_fk() -> None:
    """teachback_attempts.session_id is NOT NULL with FK to sessions."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    assert "session_id" in block
    assert "NOT NULL" in block
    assert "sessions" in block


@pytest.mark.unit
def test_teachback_attempts_uses_response_text_not_transcript() -> None:
    """teachback_attempts uses response_text — PRD rule: typed input, not STT transcript."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    # Must have response_text
    assert "response_text" in block, "response_text column missing from teachback_attempts"
    # Must NOT have a column named transcript
    assert "transcript" not in block, (
        "teachback_attempts must NOT have a 'transcript' column — "
        "PRD rule: teach-back is always typed text, never STT"
    )


@pytest.mark.unit
def test_teachback_attempts_response_text_is_not_null() -> None:
    """teachback_attempts.response_text is TEXT NOT NULL."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    # response_text line should contain NOT NULL
    lines = block.splitlines()
    for line in lines:
        if "response_text" in line:
            assert "NOT NULL" in line, f"response_text should be NOT NULL, got: {line.strip()}"
            break


@pytest.mark.unit
def test_teachback_attempts_no_duration_seconds() -> None:
    """teachback_attempts must NOT have duration_seconds — PRD rule: no timer."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    assert "duration_seconds" not in block, (
        "teachback_attempts must NOT have duration_seconds — "
        "PRD rule: no teach-back timer (creates test anxiety)"
    )


@pytest.mark.unit
def test_teachback_attempts_score_check_constraint() -> None:
    """teachback_attempts.score has CHECK (score >= 0 AND score <= 100)."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    assert "score" in block
    # The CHECK constraint spans the column definition line
    assert re.search(r"score.*CHECK.*score.*>=.*0.*score.*<=.*100", block, re.DOTALL)


@pytest.mark.unit
def test_teachback_attempts_has_feedback_fields() -> None:
    """teachback_attempts has feedback_praise and feedback_correction."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    assert "feedback_praise" in block
    assert "feedback_correction" in block


@pytest.mark.unit
def test_teachback_attempts_has_concept_arrays() -> None:
    """teachback_attempts has concepts_hit and concepts_missed as TEXT arrays."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    assert "concepts_hit" in block
    assert "concepts_missed" in block
    assert "text[]" in block.lower()


@pytest.mark.unit
def test_teachback_attempts_concept_arrays_default_empty() -> None:
    """concepts_hit and concepts_missed default to empty array '{}'."""
    block = _extract_table_block("CREATE TABLE public.teachback_attempts", MIGRATION)
    # Both arrays have DEFAULT '{}'
    assert block.count("DEFAULT '{}'") >= 2, (
        "concepts_hit and concepts_missed should both DEFAULT '{}'"
    )


@pytest.mark.unit
def test_teachback_attempts_rls_enabled() -> None:
    """ROW LEVEL SECURITY is enabled on teachback_attempts."""
    assert re.search(
        r"ALTER TABLE public\.teachback_attempts\s+ENABLE ROW LEVEL SECURITY",
        MIGRATION,
        re.IGNORECASE,
    )


@pytest.mark.unit
def test_teachback_attempts_has_rls_policies() -> None:
    """All four CRUD RLS policies exist for teachback_attempts."""
    for operation in ("select", "insert", "update", "delete"):
        assert f"teachback_attempts: {operation} own" in MIGRATION.lower(), (
            f"Missing RLS policy for teachback_attempts {operation}"
        )


# ════════════════════════════════════════════════════════════════════════════
# learner_dna
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_learner_dna_table_exists() -> None:
    """CREATE TABLE learner_dna is present in the migration."""
    assert "learner_dna" in MIGRATION


@pytest.mark.unit
def test_learner_dna_primary_key() -> None:
    """learner_dna has id UUID PRIMARY KEY."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "id" in block
    assert "PRIMARY KEY" in block


@pytest.mark.unit
def test_learner_dna_user_id_unique() -> None:
    """learner_dna.user_id has UNIQUE constraint — one row per student."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "user_id" in block
    assert "UNIQUE" in block


@pytest.mark.unit
def test_learner_dna_user_id_fk_to_users() -> None:
    """learner_dna.user_id references public.users with ON DELETE CASCADE."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "public.users" in block
    assert "ON DELETE CASCADE" in block


@pytest.mark.unit
def test_learner_dna_has_all_9_dimensions() -> None:
    """learner_dna has all 9 Learner DNA dimension columns."""
    expected_dimensions = [
        "pattern_recognition",
        "logical_deduction",
        "processing_speed",
        "frustration_tolerance",
        "persistence",
        "help_seeking",
        "goal_orientation",
        "curiosity_index",
        "study_independence",
    ]
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    for dim in expected_dimensions:
        assert dim in block, f"Learner DNA dimension '{dim}' missing from learner_dna table"


@pytest.mark.unit
def test_learner_dna_dimensions_are_numeric_5_2() -> None:
    """learner_dna dimension columns are typed NUMERIC(5,2)."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "numeric(5,2)" in block.lower()


@pytest.mark.unit
def test_learner_dna_dimensions_have_check_constraints() -> None:
    """learner_dna dimension columns have CHECK (col >= 0 AND col <= 100)."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    # Each dimension has its own CHECK constraint
    check_count = len(re.findall(r"CHECK\s*\(", block, re.IGNORECASE))
    assert check_count >= 9, (
        f"Expected at least 9 CHECK constraints (one per dimension), found {check_count}"
    )


@pytest.mark.unit
def test_learner_dna_has_badge_labels() -> None:
    """learner_dna has badge_labels TEXT[] with empty array default."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "badge_labels" in block
    assert "text[]" in block.lower()


@pytest.mark.unit
def test_learner_dna_has_profile_text() -> None:
    """learner_dna has profile_text TEXT (nullable — populated after first session)."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "profile_text" in block


@pytest.mark.unit
def test_learner_dna_has_session_count() -> None:
    """learner_dna has session_count INTEGER DEFAULT 0."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "session_count" in block
    assert "DEFAULT 0" in block


@pytest.mark.unit
def test_learner_dna_has_last_updated_timestamptz() -> None:
    """learner_dna has last_updated TIMESTAMPTZ (timezone-aware)."""
    block = _extract_table_block("CREATE TABLE public.learner_dna", MIGRATION)
    assert "last_updated" in block
    assert "timestamptz" in block.lower()


@pytest.mark.unit
def test_learner_dna_rls_enabled() -> None:
    """ROW LEVEL SECURITY is enabled on learner_dna."""
    assert re.search(
        r"ALTER TABLE public\.learner_dna\s+ENABLE ROW LEVEL SECURITY",
        MIGRATION,
        re.IGNORECASE,
    )


@pytest.mark.unit
def test_learner_dna_has_rls_policies() -> None:
    """All four CRUD RLS policies exist for learner_dna."""
    for operation in ("select", "insert", "update", "delete"):
        assert f"learner_dna: {operation} own" in MIGRATION.lower(), (
            f"Missing RLS policy for learner_dna {operation}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Cross-table structural checks
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_all_three_tables_have_rls_enabled() -> None:
    """All three assessment tables have ENABLE ROW LEVEL SECURITY statements."""
    for table in ("quiz_attempts", "teachback_attempts", "learner_dna"):
        assert re.search(
            rf"ALTER TABLE public\.{table}\s+ENABLE ROW LEVEL SECURITY",
            MIGRATION,
            re.IGNORECASE,
        ), f"ENABLE ROW LEVEL SECURITY missing for {table}"


@pytest.mark.unit
def test_all_three_tables_exist_in_migration() -> None:
    """All three assessment tables appear in the migration file."""
    for table in ("quiz_attempts", "teachback_attempts", "learner_dna"):
        assert table in MIGRATION, f"Table {table} missing from migration"


@pytest.mark.unit
def test_quiz_and_teachback_have_indexes_on_session_id() -> None:
    """quiz_attempts and teachback_attempts have explicit indexes on session_id."""
    assert re.search(
        r"CREATE INDEX ON public\.quiz_attempts\s*\(\s*session_id\s*\)",
        MIGRATION,
        re.IGNORECASE,
    ), "Missing index on quiz_attempts(session_id)"
    assert re.search(
        r"CREATE INDEX ON public\.teachback_attempts\s*\(\s*session_id\s*\)",
        MIGRATION,
        re.IGNORECASE,
    ), "Missing index on teachback_attempts(session_id)"


@pytest.mark.unit
def test_learner_dna_has_index_on_user_id() -> None:
    """learner_dna has an explicit index on user_id."""
    assert re.search(
        r"CREATE INDEX ON public\.learner_dna\s*\(\s*user_id\s*\)",
        MIGRATION,
        re.IGNORECASE,
    ), "Missing index on learner_dna(user_id)"
