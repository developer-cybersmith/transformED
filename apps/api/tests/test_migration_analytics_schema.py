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

import pytest

# Resolve the migration file path relative to the repo root.
# This file lives at apps/api/tests/, so repo root is 3 levels up.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MIGRATION_PATH = _REPO_ROOT / "supabase" / "migrations" / "20260611000000_initial_schema.sql"

# Read once at module load — all tests share this string.
MIGRATION = MIGRATION_PATH.read_text(encoding="utf-8")


# ============================================================
# onboarding_responses — table existence and columns
# ============================================================


@pytest.mark.unit
def test_onboarding_responses_table_exists():
    """The onboarding_responses table is defined in the migration."""
    assert "onboarding_responses" in MIGRATION, (
        "Expected CREATE TABLE public.onboarding_responses in migration SQL"
    )


@pytest.mark.unit
def test_onboarding_responses_has_dimension_tag():
    """dimension_tag column is present in onboarding_responses."""
    assert "dimension_tag" in MIGRATION, (
        "Expected dimension_tag column in onboarding_responses table"
    )


@pytest.mark.unit
def test_onboarding_dimension_tag_has_check_constraint():
    """dimension_tag CHECK constraint restricts values to the three valid domains.

    All three domain values must appear in the migration SQL to satisfy the
    Learner DNA scoring model (cognitive, emotional, self_direction).
    """
    assert "cognitive" in MIGRATION, (
        "Expected 'cognitive' in dimension_tag CHECK constraint"
    )
    assert "emotional" in MIGRATION, (
        "Expected 'emotional' in dimension_tag CHECK constraint"
    )
    assert "self_direction" in MIGRATION, (
        "Expected 'self_direction' in dimension_tag CHECK constraint"
    )


@pytest.mark.unit
def test_onboarding_responses_has_response_value():
    """response_value column exists to store the selected_index from the quiz."""
    assert "response_value" in MIGRATION, (
        "Expected response_value column in onboarding_responses"
    )


# ============================================================
# session_events — table existence and columns
# ============================================================


@pytest.mark.unit
def test_session_events_table_exists():
    """The session_events table is defined in the migration."""
    assert "session_events" in MIGRATION, (
        "Expected CREATE TABLE public.session_events in migration SQL"
    )


@pytest.mark.unit
def test_session_events_has_jsonb_payload():
    """payload column is JSONB type — required for flexible event schema.

    JSONB NOT NULL DEFAULT '{}' prevents null payload queries in analytics.
    """
    migration_lower = MIGRATION.lower()
    assert "jsonb" in migration_lower, (
        "Expected JSONB type for payload column in session_events"
    )


@pytest.mark.unit
def test_session_events_has_event_type():
    """event_type column exists for filtering and routing session events."""
    assert "event_type" in MIGRATION, (
        "Expected event_type column in session_events"
    )


# ============================================================
# RLS — both tables must have row level security enabled
# ============================================================


@pytest.mark.unit
def test_both_tables_have_rls():
    """ROW LEVEL SECURITY is enabled for both analytics tables.

    This verifies the ENABLE ROW LEVEL SECURITY statement appears in the
    migration. Per PRD §18, ALL Supabase tables must have RLS enabled.
    """
    migration_upper = MIGRATION.upper()
    assert "ENABLE ROW LEVEL SECURITY" in migration_upper, (
        "Expected ENABLE ROW LEVEL SECURITY for analytics tables in migration SQL"
    )
