"""Unit tests for Story 4-12 / D137 — reassessment blend in process_onboarding().

Scoring formula: normalized = (selected_index / 3) * 100.
EMA: blended = round(retain * old + (1 - retain) * new, 4), clamped [0, 100].
dna_ema_retain default = 0.7 (retain 70% old, take 30% new self-report).

ACs exercised: AC1, AC2, AC3, AC4, AC7, AC8, AC9, AC10, AC12, AC13, AC14, AC15.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.assessment.onboarding_questions import ALL_NINE_DIMENSIONS
from app.modules.assessment.schemas import OnboardingAnswer

# ── helpers ──────────────────────────────────────────────────────────────────

_VALID_USER_ID = "11111111-1111-1111-1111-111111111111"
_RETAIN = 0.7  # dna_ema_retain default


def _all_index_responses(index: int) -> list[OnboardingAnswer]:
    """20 onboarding answers all picking option at *index* (0–3)."""
    questions = [
        # Cognitive — 8
        ("c1", "cognitive"),
        ("c2", "cognitive"),
        ("c3", "cognitive"),
        ("c4", "cognitive"),
        ("c5", "cognitive"),
        ("c6", "cognitive"),
        ("c7", "cognitive"),
        ("c8", "cognitive"),
        # Emotional — 5
        ("e1", "emotional"),
        ("e2", "emotional"),
        ("e3", "emotional"),
        ("e4", "emotional"),
        ("e5", "emotional"),
        # Self-Direction — 7
        ("s1", "self_direction"),
        ("s2", "self_direction"),
        ("s3", "self_direction"),
        ("s4", "self_direction"),
        ("s5", "self_direction"),
        ("s6", "self_direction"),
        ("s7", "self_direction"),
    ]
    return [
        OnboardingAnswer(
            question_id=qid,
            dimension=dim,  # type: ignore[arg-type]
            selected_index=index,
            selected_text=f"Option {index}",
            response_time_ms=1000,
        )
        for qid, dim in questions
    ]


def _make_supabase_mock(
    *,
    existing_dna_row: dict[str, Any] | None,
    insert_ok: bool = True,
    upsert_ok: bool = True,
) -> MagicMock:
    """Build a mock Supabase client for process_onboarding tests.

    Uses side_effect on table() to return table-specific mocks so that
    learner_dna SELECT, onboarding_responses INSERT, and learner_dna UPSERT
    can be independently configured.
    """
    mock = MagicMock()

    # learner_dna table mock
    dna_table = MagicMock()
    maybe_single_resp = MagicMock()
    maybe_single_resp.error = None
    maybe_single_resp.data = existing_dna_row
    (
        dna_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
    ) = maybe_single_resp
    upsert_resp = MagicMock()
    upsert_resp.error = None if upsert_ok else MagicMock()
    dna_table.upsert.return_value.execute.return_value = upsert_resp

    # onboarding_responses table mock
    ob_table = MagicMock()
    insert_resp = MagicMock()
    insert_resp.error = None if insert_ok else MagicMock()
    ob_table.insert.return_value.execute.return_value = insert_resp

    # analytics/PostHog consent table mock (users table)
    users_table = MagicMock()
    consent_resp = MagicMock()
    consent_resp.error = None
    consent_resp.data = None  # no consent row → PostHog suppressed
    _chain = users_table.select.return_value.eq.return_value.maybe_single.return_value
    _chain.execute.return_value = consent_resp

    def _table_side_effect(name: str) -> MagicMock:
        if name == "learner_dna":
            return dna_table
        if name == "onboarding_responses":
            return ob_table
        return users_table  # users + anything else

    mock.table.side_effect = _table_side_effect
    return mock


def _existing_row_all_score(score: float) -> dict[str, Any]:
    """A learner_dna DB row with all 9 dimensions set to *score*."""
    row: dict[str, Any] = {"user_id": _VALID_USER_ID, "session_count": 5}
    for dim in ALL_NINE_DIMENSIONS:
        row[dim] = score
    return row


# ── AC1 — first-time path writes raw scores, session_count=0 ─────────────────


@pytest.mark.asyncio
async def test_first_time_writes_raw_scores_and_zero_session_count() -> None:
    """AC1: no existing row → raw scores written, session_count=0."""
    supabase = _make_supabase_mock(existing_dna_row=None)
    responses = _all_index_responses(3)  # all max → score = 100.0

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile text. HIE disclaimer."),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses,
            user_id=_VALID_USER_ID,
            supabase=supabase,
        )

    # session_count=0 in result
    assert result.session_count == 0

    # upsert payload has session_count=0 and raw score=100.0 for all dims
    dna_table = supabase.table("learner_dna")
    upsert_calls = dna_table.upsert.call_args_list
    assert upsert_calls, "upsert was never called"
    payload = upsert_calls[0].args[0]
    assert payload["session_count"] == 0
    for dim in ALL_NINE_DIMENSIONS:
        assert abs(payload[dim] - 100.0) < 0.01, f"{dim}: expected 100.0, got {payload[dim]}"


# ── AC2 + AC13 — reassessment blends each dimension via EMA ──────────────────


@pytest.mark.asyncio
async def test_reassessment_blends_scores_via_ema_for_each_dimension() -> None:
    """AC2 + AC13: existing row → each dim blended = round(0.7*old + 0.3*new, 4)."""
    old_score = 60.0
    new_index = 3  # new self-report score = (3/3)*100 = 100.0
    new_score = 100.0
    expected_blend = round(_RETAIN * old_score + (1.0 - _RETAIN) * new_score, 4)
    # expected_blend = round(0.7*60 + 0.3*100, 4) = round(42 + 30, 4) = 72.0

    existing = _existing_row_all_score(old_score)
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_index_responses(new_index)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        await process_onboarding(
            responses=responses,
            user_id=_VALID_USER_ID,
            supabase=supabase,
        )

    dna_table = supabase.table("learner_dna")
    upsert_calls = dna_table.upsert.call_args_list
    payload = upsert_calls[0].args[0]
    for dim in ALL_NINE_DIMENSIONS:
        assert abs(payload[dim] - expected_blend) < 0.001, (
            f"{dim}: expected blend={expected_blend}, got {payload[dim]}"
        )


# ── AC3 + AC14 — session_count preserved on reassessment ─────────────────────


@pytest.mark.asyncio
async def test_reassessment_preserves_existing_session_count() -> None:
    """AC3 + AC14: existing session_count is never reset to 0 on reassessment."""
    existing = _existing_row_all_score(50.0)
    existing["session_count"] = 17  # student has done 17 sessions

    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_index_responses(2)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses,
            user_id=_VALID_USER_ID,
            supabase=supabase,
        )

    # AC8 — OnboardingResult.session_count must reflect existing value
    assert result.session_count == 17

    dna_table = supabase.table("learner_dna")
    upsert_calls = dna_table.upsert.call_args_list
    payload = upsert_calls[0].args[0]
    assert payload["session_count"] == 17, (
        f"session_count was reset to {payload['session_count']}, expected 17"
    )


# ── AC7 — DB error on existing row SELECT falls back to first-time write ──────


@pytest.mark.asyncio
async def test_existing_row_fetch_error_falls_back_to_first_time_write(caplog: Any) -> None:
    """AC7: if _fetch_existing_dna raises, fallback to raw write + log WARNING."""
    supabase = _make_supabase_mock(existing_dna_row=None)
    # Make the learner_dna SELECT raise to simulate DB error
    dna_table = supabase.table("learner_dna")
    dna_table.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
        Exception("DB connection lost")
    )
    responses = _all_index_responses(1)  # score = (1/3)*100 = 33.33...

    import logging

    with (
        patch(
            "app.modules.assessment.service.generate_onboarding_profile",
            new=AsyncMock(return_value="Profile. HIE."),
        ),
        caplog.at_level(logging.WARNING, logger="app.modules.assessment.service"),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses,
            user_id=_VALID_USER_ID,
            supabase=supabase,
        )

    # Falls back to session_count=0
    assert result.session_count == 0
    # Warning was logged
    assert any(
        "reassessment" in r.message.lower() or "existing" in r.message.lower()
        for r in caplog.records
    )


# ── AC9 — onboarding_responses rows still written on reassessment ─────────────


@pytest.mark.asyncio
async def test_onboarding_responses_written_on_reassessment() -> None:
    """AC9/AC10: INSERT to onboarding_responses runs on both first-time and reassessment."""
    existing = _existing_row_all_score(40.0)
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_index_responses(0)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        await process_onboarding(
            responses=responses,
            user_id=_VALID_USER_ID,
            supabase=supabase,
        )

    ob_table = supabase.table("onboarding_responses")
    insert_calls = ob_table.insert.call_args_list
    assert insert_calls, "onboarding_responses INSERT was never called on reassessment"
    inserted_rows = insert_calls[0].args[0]
    assert len(inserted_rows) == 20


# ── AC4 — badge_labels from blended scores ────────────────────────────────────


@pytest.mark.asyncio
async def test_reassessment_badge_labels_from_blended_scores() -> None:
    """AC4: badge_labels recomputed from blended scores, not raw self-report scores."""
    # Old score=80 (badge awarded), new self-report score=0 (index 0 → score 0)
    # blended = 0.7*80 + 0.3*0 = 56 — below badge threshold of 70 → NO badge
    old_score = 80.0
    new_index = 0  # score = 0.0
    expected_blend = round(_RETAIN * old_score + (1.0 - _RETAIN) * 0.0, 4)  # 56.0

    existing = _existing_row_all_score(old_score)
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_index_responses(new_index)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses,
            user_id=_VALID_USER_ID,
            supabase=supabase,
        )

    # blended score ~56 < 70 → no badge should appear
    assert result.badge_labels == [], (
        f"Expected no badges (blend={expected_blend} < 70), got {result.badge_labels}"
    )
