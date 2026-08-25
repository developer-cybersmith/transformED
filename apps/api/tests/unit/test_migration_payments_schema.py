"""
Schema verification tests for the payments tables (Story 5-3/S4-3, Task 5.5).

Reads the migration SQL as text — pure unit tests, no DB connection
required. Verifies: table existence + columns/constraints, RLS enabled on
both tables, lesson_access has exactly one policy (SELECT-own, no
INSERT/UPDATE/DELETE — AC7), and all three RPC functions are revoked from
anon/authenticated and granted only to service_role.

Migration file: supabase/migrations/20260825000000_stripe_payments_lesson_access.sql
"""

from __future__ import annotations

import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
MIGRATION_PATH = (
    _REPO_ROOT / "supabase" / "migrations" / "20260825000000_stripe_payments_lesson_access.sql"
)
MIGRATION = MIGRATION_PATH.read_text(encoding="utf-8")


def _extract_block(marker: str, window: int = 2500) -> str:
    idx = MIGRATION.find(marker)
    if idx == -1:
        return ""
    return MIGRATION[idx : idx + window]


# ============================================================
# lesson_access
# ============================================================


@pytest.mark.unit
def test_lesson_access_table_exists() -> None:
    assert "CREATE TABLE public.lesson_access" in MIGRATION


@pytest.mark.unit
def test_lesson_access_user_id_is_primary_key_fk() -> None:
    block = _extract_block("CREATE TABLE public.lesson_access")
    assert "user_id" in block
    assert "PRIMARY KEY" in block
    assert "REFERENCES public.users(id)" in block
    assert "ON DELETE CASCADE" in block


@pytest.mark.unit
def test_lesson_access_credits_defaults_zero_and_cannot_go_negative() -> None:
    block = _extract_block("CREATE TABLE public.lesson_access")
    assert "lesson_credits" in block
    assert "DEFAULT 0" in block
    assert "CHECK (lesson_credits >= 0)" in block


@pytest.mark.unit
def test_lesson_access_has_rls_enabled() -> None:
    pattern = re.compile(
        r"ALTER TABLE public\.lesson_access\s+ENABLE ROW LEVEL SECURITY", re.IGNORECASE
    )
    assert pattern.search(MIGRATION)


@pytest.mark.unit
def test_lesson_access_has_exactly_one_select_own_policy_no_write_policy() -> None:
    """AC7: the ONLY policy is SELECT-own. Every write happens server-side
    via the service-role client, which bypasses RLS — a student must never
    be able to grant themselves credits by writing their own row."""
    policies = re.findall(r'CREATE POLICY\s+"([^"]+)"\s+ON public\.lesson_access', MIGRATION)
    assert len(policies) == 1, f"expected exactly 1 policy on lesson_access, found {policies}"
    block = _extract_block(f'CREATE POLICY "{policies[0]}"', window=200)
    assert "FOR SELECT" in block
    assert "auth.uid()" in block
    # No INSERT/UPDATE/DELETE policy anywhere in the file for this table.
    for verb in ("FOR INSERT", "FOR UPDATE", "FOR DELETE"):
        assert not re.search(
            rf'CREATE POLICY\s+"[^"]+"\s+ON public\.lesson_access[^;]*{verb}',
            MIGRATION,
            re.DOTALL,
        ), f"unexpected {verb} policy on lesson_access"


# ============================================================
# stripe_events
# ============================================================


@pytest.mark.unit
def test_stripe_events_table_exists() -> None:
    assert "CREATE TABLE public.stripe_events" in MIGRATION


@pytest.mark.unit
def test_stripe_event_id_is_the_primary_key() -> None:
    """AC5's actual enforcement mechanism — the PRIMARY KEY itself, not an
    application-level cache or a SELECT-then-INSERT check."""
    block = _extract_block("CREATE TABLE public.stripe_events")
    assert "stripe_event_id" in block
    assert "PRIMARY KEY" in block.split("stripe_event_id")[1][:30]


@pytest.mark.unit
def test_stripe_events_has_rls_enabled_with_zero_policies() -> None:
    """Internal webhook ledger — never read by a user-facing route."""
    pattern = re.compile(
        r"ALTER TABLE public\.stripe_events\s+ENABLE ROW LEVEL SECURITY", re.IGNORECASE
    )
    assert pattern.search(MIGRATION)
    assert not re.search(r'CREATE POLICY\s+"[^"]+"\s+ON public\.stripe_events', MIGRATION)


# ============================================================
# RPC functions — grant/revoke shape
# ============================================================


@pytest.mark.parametrize(
    ("fn_name", "sig"),
    [
        ("grant_lesson_credits", "uuid, integer"),
        ("decrement_lesson_credit", "uuid"),
        ("record_stripe_event_if_new", "text, text, text"),
        ("record_stripe_event_and_grant_credits", "text, text, text, uuid, integer"),
    ],
)
@pytest.mark.unit
def test_rpc_function_defined_and_locked_to_service_role(fn_name: str, sig: str) -> None:
    assert f"CREATE OR REPLACE FUNCTION public.{fn_name}(" in MIGRATION
    assert f"REVOKE EXECUTE ON FUNCTION public.{fn_name}({sig}) FROM public" in MIGRATION
    assert f"REVOKE EXECUTE ON FUNCTION public.{fn_name}({sig}) FROM anon" in MIGRATION
    assert f"REVOKE EXECUTE ON FUNCTION public.{fn_name}({sig}) FROM authenticated" in MIGRATION
    assert f"GRANT  EXECUTE ON FUNCTION public.{fn_name}({sig}) TO service_role" in MIGRATION


@pytest.mark.unit
def test_decrement_lesson_credit_is_a_single_conditional_update_not_select_then_write() -> None:
    """D45's own register entry names exactly this shape as a defect: a read
    followed by a write with no lock between them. This function must be
    ONE UPDATE statement with the guard in its WHERE clause, not a SELECT
    followed by a conditional UPDATE."""
    block = _extract_block("CREATE OR REPLACE FUNCTION public.decrement_lesson_credit")
    body = block.split("AS $$")[1].split("$$;")[0]
    assert "SELECT" not in body.upper()
    assert "UPDATE public.lesson_access" in body
    assert "lesson_credits > 0" in body
    assert "RETURN FOUND" in body


@pytest.mark.unit
def test_grant_lesson_credits_is_an_atomic_upsert() -> None:
    block = _extract_block("CREATE OR REPLACE FUNCTION public.grant_lesson_credits")
    body = block.split("AS $$")[1].split("$$;")[0]
    assert "ON CONFLICT (user_id) DO UPDATE" in body
    assert "lesson_access.lesson_credits + excluded.lesson_credits" in body


@pytest.mark.unit
def test_record_stripe_event_if_new_is_insert_on_conflict_do_nothing() -> None:
    block = _extract_block("CREATE OR REPLACE FUNCTION public.record_stripe_event_if_new")
    body = block.split("AS $$")[1].split("$$;")[0]
    assert "INSERT INTO public.stripe_events" in body
    assert "ON CONFLICT (stripe_event_id) DO NOTHING" in body
    assert "RETURN FOUND" in body


@pytest.mark.unit
def test_record_stripe_event_and_grant_credits_is_one_atomic_function_body() -> None:
    """D136 (docs/DEFECT-REGISTER.md) — the whole point of this RPC over
    two separate calls is that BOTH the idempotency insert and the credit
    grant live inside ONE plpgsql function body (one implicit transaction),
    so a failure anywhere inside it rolls back the idempotency insert too.
    Asserts there is exactly one CREATE FUNCTION statement containing both
    operations, not two separate function definitions."""
    block = _extract_block(
        "CREATE OR REPLACE FUNCTION public.record_stripe_event_and_grant_credits"
    )
    body = block.split("AS $$")[1].split("$$;")[0]
    assert "INSERT INTO public.stripe_events" in body
    assert "ON CONFLICT (stripe_event_id) DO NOTHING" in body
    assert "IF NOT FOUND THEN" in body
    assert "RETURN false" in body
    assert "INSERT INTO public.lesson_access" in body
    assert "ON CONFLICT (user_id) DO UPDATE" in body
    assert "RETURN true" in body
    # Both INSERTs are inside the SAME "AS $$ ... $$" body (not two separate
    # CREATE FUNCTION statements) — confirmed by _extract_block finding both
    # markers within a single block starting at the one CREATE FUNCTION line.
    assert body.index("INSERT INTO public.stripe_events") < body.index(
        "INSERT INTO public.lesson_access"
    ), "expected the idempotency insert to run before the credit grant, in the same function"
