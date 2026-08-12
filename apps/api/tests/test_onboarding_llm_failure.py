"""
Story 3-54 — D71/D72 tests.

Tests for:
  - D71: Onboarding LLM failure permanently locks user out
  - D72: Stale "TransformED" brand in DPDP disclaimer + system prompt

All tests are @pytest.mark.unit — no real Supabase, Redis, or OpenAI connections.
"""

from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ── Shared helpers ─────────────────────────────────────────────────────────────

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"


def _make_20_responses() -> list[dict[str, Any]]:
    """Build 20 valid OnboardingAnswer-compatible dicts."""
    rows: list[dict[str, Any]] = []
    for i in range(1, 9):
        rows.append({
            "question_id": f"c{i}",
            "dimension": "cognitive",
            "selected_index": 2,
            "selected_text": "Option 2",
        })
    for i in range(1, 6):
        rows.append({
            "question_id": f"e{i}",
            "dimension": "emotional",
            "selected_index": 2,
            "selected_text": "Option 2",
        })
    for i in range(1, 8):
        rows.append({
            "question_id": f"s{i}",
            "dimension": "self_direction",
            "selected_index": 2,
            "selected_text": "Option 2",
        })
    return rows


def _make_onboarding_answers():
    """Return OnboardingAnswer objects matching _make_20_responses()."""
    from app.modules.assessment.schemas import OnboardingAnswer
    return [OnboardingAnswer(**r) for r in _make_20_responses()]


def _supabase_insert_ok():
    """Supabase mock whose .insert().execute() returns success (no error)."""
    resp = MagicMock()
    resp.error = None
    resp.data = [{"id": "row-1"}]

    table = MagicMock()
    table.insert.return_value.execute.return_value = resp
    table.delete.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(error=None)
    table.upsert.return_value.execute.return_value = MagicMock(error=None, data=[{"user_id": "u1"}])

    supabase = MagicMock()
    supabase.table.return_value = table
    return supabase


# ── D71 Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_onboarding_llm_failure_releases_redis_lock():
    """AC1 — D71: When the LLM call raises any exception, the Redis lock must
    be absent after process_onboarding() raises HTTPException(503)."""
    from fastapi import HTTPException

    supabase = _supabase_insert_ok()
    answers = _make_onboarding_answers()

    with patch("app.modules.assessment.service.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
         patch("app.modules.assessment.service.generate_onboarding_profile", new_callable=AsyncMock) as mock_gen, \
         patch("app.modules.assessment.service.OpenAILLMProvider"):
        # to_thread: first call = insert (success), second call = rollback delete
        mock_thread.side_effect = [
            MagicMock(error=None, data=[{}]),   # Step 3 insert succeeds
            MagicMock(error=None),              # Step 4 rollback delete
        ]
        mock_gen.side_effect = Exception("openai: rate limit exceeded")

        with pytest.raises(HTTPException) as exc_info:
            from app.modules.assessment.service import process_onboarding
            await process_onboarding(
                responses=answers,
                user_id="user-001",
                supabase=supabase,
            )

    assert exc_info.value.status_code == 503, (
        "LLM failure must raise 503 Service Unavailable so router's HTTPException "
        "cleanup fires and releases the Redis lock"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_onboarding_llm_failure_returns_503():
    """AC4 — D71: The failed onboarding call must return HTTP 503, not 500."""
    from fastapi import HTTPException

    supabase = _supabase_insert_ok()
    answers = _make_onboarding_answers()

    with patch("app.modules.assessment.service.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
         patch("app.modules.assessment.service.generate_onboarding_profile", new_callable=AsyncMock) as mock_gen, \
         patch("app.modules.assessment.service.OpenAILLMProvider"):
        mock_thread.side_effect = [
            MagicMock(error=None, data=[{}]),
            MagicMock(error=None),
        ]
        mock_gen.side_effect = RuntimeError("timeout")

        with pytest.raises(HTTPException) as exc_info:
            from app.modules.assessment.service import process_onboarding
            await process_onboarding(
                responses=answers,
                user_id="user-002",
                supabase=supabase,
            )

    assert exc_info.value.status_code == 503


@pytest.mark.unit
@pytest.mark.asyncio
async def test_onboarding_llm_failure_deletes_orphaned_rows():
    """AC2 — D71: When the LLM call fails, the rollback delete must be called
    with the exact question_ids from the Step 3 insert."""
    from fastapi import HTTPException

    supabase = _supabase_insert_ok()
    answers = _make_onboarding_answers()
    expected_qids = [a.question_id for a in answers]

    delete_mock = MagicMock()
    delete_mock.eq.return_value.in_.return_value.execute.return_value = MagicMock(error=None)

    rollback_resp = AsyncMock(return_value=None)

    called_args: list[Any] = []

    async def fake_to_thread(fn, *args, **kwargs):
        result = fn()
        # Capture delete calls to assert on them
        return result

    with patch("app.modules.assessment.service.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("app.modules.assessment.service.generate_onboarding_profile", new_callable=AsyncMock) as mock_gen, \
         patch("app.modules.assessment.service.OpenAILLMProvider"):
        mock_gen.side_effect = Exception("llm failed")

        # Wire supabase so the delete call is trackable
        delete_chain = supabase.table.return_value.delete.return_value
        delete_chain.eq.return_value.in_.return_value.execute.return_value = MagicMock(error=None)

        with pytest.raises(HTTPException):
            from app.modules.assessment.service import process_onboarding
            await process_onboarding(
                responses=answers,
                user_id="user-003",
                supabase=supabase,
            )

    # Assert delete was called (the rollback path executed)
    supabase.table.return_value.delete.assert_called()
    in_call_args = supabase.table.return_value.delete.return_value.eq.return_value.in_.call_args
    actual_qids = in_call_args[0][1] if in_call_args else []
    assert set(actual_qids) == set(expected_qids), (
        f"Rollback must delete exactly the inserted question_ids.\n"
        f"Expected: {sorted(expected_qids)}\n"
        f"Got: {sorted(actual_qids)}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_onboarding_retry_after_llm_failure_succeeds():
    """AC3 — D71: After a LLM failure + lock release, a second call to
    process_onboarding() must succeed (not hit unique-constraint 409).

    Simulates: first call fails at LLM → rows deleted → second call succeeds.
    """
    from fastapi import HTTPException

    supabase = _supabase_insert_ok()
    answers = _make_onboarding_answers()

    call_count = 0

    async def llm_fail_then_succeed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("transient provider outage")
        return "You are a Pattern Thinker.\n\nYou tend to see structure quickly."

    async def fake_to_thread(fn, *args, **kwargs):
        return fn()

    with patch("app.modules.assessment.service.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("app.modules.assessment.service.generate_onboarding_profile", side_effect=llm_fail_then_succeed), \
         patch("app.modules.assessment.service.OpenAILLMProvider"), \
         patch("app.modules.assessment.service.capture_event"), \
         patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True):

        # First call — must fail with 503
        with pytest.raises(HTTPException) as exc_info:
            from app.modules.assessment.service import process_onboarding
            await process_onboarding(
                responses=answers,
                user_id="user-004",
                supabase=supabase,
            )
        assert exc_info.value.status_code == 503

        # Second call — must succeed
        result = await process_onboarding(
            responses=answers,
            user_id="user-004",
            supabase=supabase,
        )

    assert result is not None
    assert hasattr(result, "badge_labels")
    assert hasattr(result, "profile_text")


# ── D72 Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dpdp_disclaimer_uses_hie():
    """AC5 — D72: DPDP_DISCLAIMER must contain 'HIE' and must not contain
    'TransformED'."""
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    assert "TransformED" not in DPDP_DISCLAIMER, (
        "DPDP_DISCLAIMER still contains stale brand 'TransformED'. "
        "Replace with 'HIE'."
    )
    assert "HIE" in DPDP_DISCLAIMER, (
        "DPDP_DISCLAIMER does not contain the new brand name 'HIE'."
    )


@pytest.mark.unit
def test_system_prompt_uses_hie():
    """AC6 — D72: ONBOARDING_PROFILE_SYSTEM_PROMPT must contain 'HIE' and
    must not contain 'TransformED'."""
    from app.modules.assessment.prompts import ONBOARDING_PROFILE_SYSTEM_PROMPT

    assert "TransformED" not in ONBOARDING_PROFILE_SYSTEM_PROMPT, (
        "ONBOARDING_PROFILE_SYSTEM_PROMPT still contains stale brand 'TransformED'. "
        "Replace with 'HIE'."
    )
    assert "HIE" in ONBOARDING_PROFILE_SYSTEM_PROMPT, (
        "ONBOARDING_PROFILE_SYSTEM_PROMPT does not contain the new brand name 'HIE'."
    )


@pytest.mark.unit
def test_migration_sql_has_rebrand_update():
    """AC7 — D72: Migration 20260813000000_learner_dna_rebrand.sql must exist
    and must contain a REPLACE/UPDATE statement targeting learner_dna.profile_text."""
    migration_file = _MIGRATIONS_DIR / "20260813000000_learner_dna_rebrand.sql"

    assert migration_file.exists(), (
        f"Migration file {migration_file.name} does not exist. "
        "Create it with UPDATE learner_dna SET profile_text = REPLACE(...)."
    )

    sql = migration_file.read_text(encoding="utf-8").upper()
    assert "LEARNER_DNA" in sql, "Migration must reference the learner_dna table."
    assert "PROFILE_TEXT" in sql, "Migration must update the profile_text column."
    assert "REPLACE" in sql or "UPDATE" in sql, (
        "Migration must contain an UPDATE or REPLACE statement."
    )
    assert "TRANSFORMEDED" not in sql and ("TRANSFORMIED" not in sql), (
        "Migration SQL appears malformed — double-check the content."
    )
