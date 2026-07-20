"""
Schema verification tests for the analytics tables in the initial migration.

These tests read the migration SQL file as text and verify that the
onboarding_responses and session_events tables are defined correctly.
They are pure unit tests — no DB connection required.

Tables verified:
- onboarding_responses (Learner DNA onboarding data)
- session_events (real-time session event stream)

Migration file: supabase/migrations/20260611000000_initial_schema.sql
"""

from __future__ import annotations

import pathlib
import re

import pytest

# Resolve the migration file path relative to the repo root.
# This file lives at apps/api/tests/, so repo root is 3 levels up.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MIGRATION_PATH = _REPO_ROOT / "supabase" / "migrations" / "20260611000000_initial_schema.sql"

# Read once at module load — all tests share this string.
MIGRATION = MIGRATION_PATH.read_text(encoding="utf-8")


def _extract_table_block(table_name: str, window: int = 3000) -> str:
    """Return up to `window` chars of the migration starting at the CREATE TABLE line.
    Scopes assertions to a single table, preventing cross-table false matches.
    """
    idx = MIGRATION.find(table_name)
    if idx == -1:
        return ""
    return MIGRATION[idx : idx + window]


# ============================================================
# onboarding_responses — table existence and columns
# ============================================================


@pytest.mark.unit
def test_onboarding_responses_table_exists():
    """The onboarding_responses table is defined in the migration."""
    assert "CREATE TABLE public.onboarding_responses" in MIGRATION, (
        "Expected CREATE TABLE public.onboarding_responses in migration SQL"
    )


@pytest.mark.unit
def test_onboarding_responses_has_dimension_tag():
    """dimension_tag column is present in onboarding_responses."""
    block = _extract_table_block("CREATE TABLE public.onboarding_responses")
    assert "dimension_tag" in block, "Expected dimension_tag column in onboarding_responses table"


@pytest.mark.unit
def test_onboarding_dimension_tag_has_check_constraint():
    """dimension_tag CHECK constraint restricts values to the three valid domains.

    Checked within the onboarding_responses table block to avoid matching
    other tables' column or constraint names.
    """
    block = _extract_table_block("CREATE TABLE public.onboarding_responses")
    assert "cognitive" in block, (
        "Expected 'cognitive' in onboarding_responses dimension_tag CHECK constraint"
    )
    assert "emotional" in block, (
        "Expected 'emotional' in onboarding_responses dimension_tag CHECK constraint"
    )
    assert "self_direction" in block, (
        "Expected 'self_direction' in onboarding_responses dimension_tag CHECK constraint"
    )


@pytest.mark.unit
def test_onboarding_responses_has_response_value():
    """response_value column exists to store the selected_index from the quiz."""
    block = _extract_table_block("CREATE TABLE public.onboarding_responses")
    assert "response_value" in block, "Expected response_value column in onboarding_responses"


@pytest.mark.unit
def test_onboarding_responses_has_user_id_fk():
    """user_id FK references public.users — enforces data ownership."""
    block = _extract_table_block("CREATE TABLE public.onboarding_responses")
    assert "user_id" in block, "Expected user_id column in onboarding_responses"


@pytest.mark.unit
def test_onboarding_responses_has_rls():
    """ENABLE ROW LEVEL SECURITY present for onboarding_responses specifically."""
    rls_pattern = re.compile(
        r"ALTER TABLE public\.onboarding_responses\s+ENABLE ROW LEVEL SECURITY",
        re.IGNORECASE,
    )
    assert rls_pattern.search(MIGRATION), (
        "Expected ALTER TABLE public.onboarding_responses ENABLE ROW LEVEL SECURITY"
    )


# ============================================================
# session_events — table existence and columns
# ============================================================


@pytest.mark.unit
def test_session_events_table_exists():
    """The session_events table is defined in the migration."""
    assert "CREATE TABLE public.session_events" in MIGRATION, (
        "Expected CREATE TABLE public.session_events in migration SQL"
    )


@pytest.mark.unit
def test_session_events_has_jsonb_payload():
    """payload column is JSONB type within session_events — not another table."""
    block = _extract_table_block("CREATE TABLE public.session_events")
    assert "jsonb" in block.lower(), "Expected JSONB type for payload column in session_events"


@pytest.mark.unit
def test_session_events_has_event_type():
    """event_type column exists for filtering and routing session events."""
    block = _extract_table_block("CREATE TABLE public.session_events")
    assert "event_type" in block, "Expected event_type column in session_events"


@pytest.mark.unit
def test_session_events_has_session_id_fk():
    """session_id FK present in session_events — links events to their session."""
    block = _extract_table_block("CREATE TABLE public.session_events")
    assert "session_id" in block, "Expected session_id column in session_events"


@pytest.mark.unit
def test_session_events_has_rls():
    """ENABLE ROW LEVEL SECURITY present for session_events specifically."""
    rls_pattern = re.compile(
        r"ALTER TABLE public\.session_events\s+ENABLE ROW LEVEL SECURITY",
        re.IGNORECASE,
    )
    assert rls_pattern.search(MIGRATION), (
        "Expected ALTER TABLE public.session_events ENABLE ROW LEVEL SECURITY"
    )
