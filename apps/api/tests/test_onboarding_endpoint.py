"""
Unit tests for onboarding assessment (Story 235 — 30-question redesign):
  - POST /api/assessment/onboarding/submit endpoint (HTTP layer)
  - process_onboarding() service function
  - _validate_onboarding_responses() pure helper
  - _compute_penta_scores() / _compute_penta_badge_labels() pure helpers
  - Q_SPEC / MCQ_OPTION_COUNTS / ALL_QUESTION_IDS / PENTA_* completeness
  - DPDP disclaimer enforcement
  - DB migration file existence

All tests are @pytest.mark.unit — no real Supabase, Redis, or LLM connections.
asyncio.to_thread is shimmed via mock_to_thread fixture (same pattern as quiz tests).
"""

from __future__ import annotations

import pathlib
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user, get_settings
from app.modules.assessment.onboarding_questions import ALL_QUESTION_IDS, MCQ_OPTION_COUNTS, Q_SPEC
from app.modules.assessment.router import router

# ── Paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# ── HTTP-layer client ─────────────────────────────────────────────────────────


async def _fake_user() -> dict:
    return {"sub": "user-onb-001", "email": "onboarding@example.com"}


def _fake_settings() -> MagicMock:
    """submit_onboarding_diagnostic depends on ApprovedUser (403 unless the
    JWT email is on the beta-access allowlist) -- approve _fake_user's email."""
    settings = MagicMock()
    settings.approved_emails = ["onboarding@example.com"]
    return settings


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.dependency_overrides[get_settings] = _fake_settings
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

# ── Helpers ───────────────────────────────────────────────────────────────────

# Penta scoring (Q16-Q20) index choices for deterministic high/low test fixtures —
# mirrors PENTA_SCORING in onboarding_questions.py directly (not hardcoded twice;
# imported where used).
_PENTA_TOP_INDEX = {"q16": 1, "q17": 1, "q18": 2, "q19": 2, "q20": 3}
_PENTA_LOW_INDEX = {"q16": 0, "q17": 0, "q18": 0, "q19": 0, "q20": 0}


def _make_30_responses(
    mcq_index: int = 1,
    penta_indices: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Build 30 valid OnboardingAnswer wire-format dicts (q1-q30).

    mcq_index is used for all non-Penta MCQs (clamped to each question's real
    option count). penta_indices overrides Q16-Q20 specifically (for badge tests).
    """
    penta_indices = penta_indices or {}
    responses: list[dict[str, Any]] = []
    for qid, fmt in Q_SPEC.items():
        if fmt == "mcq":
            if qid in penta_indices:
                index = penta_indices[qid]
            else:
                index = min(mcq_index, MCQ_OPTION_COUNTS[qid] - 1)
            responses.append(
                {
                    "question_id": qid,
                    "format": "mcq",
                    "selected_index": index,
                    "response_text": f"Option {index}",
                }
            )
        elif fmt == "one_liner":
            responses.append(
                {
                    "question_id": qid,
                    "format": "one_liner",
                    "response_text": f"Honest answer for {qid}.",
                }
            )
        else:  # true_false
            responses.append(
                {
                    "question_id": qid,
                    "format": "true_false",
                    "response_bool": True,
                }
            )
    return responses


def _make_onboarding_answers(
    mcq_index: int = 1,
    penta_indices: dict[str, int] | None = None,
):
    """Return list of OnboardingAnswer objects (for service-layer tests)."""
    from app.modules.assessment.schemas import OnboardingAnswer

    return [OnboardingAnswer(**r) for r in _make_30_responses(mcq_index, penta_indices)]


@pytest.fixture(autouse=True)
def _mock_analytics_consent(monkeypatch) -> None:
    """Suppress the analytics-consent DB lookup for all onboarding endpoint tests.

    process_onboarding() calls get_analytics_consent() which makes an extra supabase.table("users")
    call. Patching it here keeps the supabase side_effect list (3 entries) clean and isolates
    consent behaviour to test_posthog_events.py where it is tested exhaustively.
    """
    monkeypatch.setattr(
        "app.modules.assessment.service.get_analytics_consent",
        AsyncMock(return_value=False),
    )


@pytest.fixture
def mock_to_thread(monkeypatch):
    """Shim asyncio.to_thread to run synchronously for MagicMock chain compatibility."""

    async def _sync_shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


def _build_onboarding_supabase(
    insert_error=None,
    upsert_error=None,
) -> MagicMock:
    """Build mock Supabase client for process_onboarding call order:
    1st call: learner_dna SELECT (_fetch_existing_dna — session_count only)
    2nd call: onboarding_answers_v2 UPSERT (D173: was INSERT — see service.py Step 5)
    3rd call: learner_dna UPSERT
    """
    mock = MagicMock()

    dna_select_mock = MagicMock()
    dna_select_resp = MagicMock()
    dna_select_resp.data = None  # first-time user — no prior DNA
    dna_select_chain = dna_select_mock.select.return_value.eq.return_value.maybe_single.return_value
    dna_select_chain.execute.return_value = dna_select_resp

    answers_v2_mock = MagicMock()
    answers_v2_resp = MagicMock()
    answers_v2_resp.data = []
    answers_v2_resp.error = insert_error
    answers_v2_mock.upsert.return_value.execute.return_value = answers_v2_resp

    upsert_mock = MagicMock()
    upsert_resp = MagicMock()
    upsert_resp.data = [{"user_id": "user-onb-001"}]
    upsert_resp.error = upsert_error
    upsert_mock.upsert.return_value.execute.return_value = upsert_resp

    mock.table.side_effect = [dna_select_mock, answers_v2_mock, upsert_mock]
    return mock


def _patched_llm(monkeypatch_target: str = "app.modules.assessment.service.OpenAILLMProvider"):
    """Context manager stack helper: patches the LLM provider + both get_settings call
    sites process_onboarding's profile-text generation path touches."""
    return (
        patch(monkeypatch_target),
        patch("app.modules.assessment.service.get_settings"),
        patch("app.modules.assessment.prompts.get_settings"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# TASK 1 — Migration file (onboarding_responses' own UNIQUE constraint — frozen
# table, unchanged by Story 235; onboarding_answers_v2 is a NEW, separate table)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_migration_unique_constraint_file_exists() -> None:
    """Migration 20260703000000_onboarding_unique_constraint.sql must exist."""
    migration_path = (
        _REPO_ROOT / "supabase" / "migrations" / "20260703000000_onboarding_unique_constraint.sql"
    )
    assert migration_path.exists(), (
        "Missing migration file: supabase/migrations/"
        "20260703000000_onboarding_unique_constraint.sql. "
        "Create it to close the Sprint 0 finding: no UNIQUE(user_id, question_id) "
        "on onboarding_responses."
    )


@pytest.mark.unit
def test_migration_unique_constraint_sql_content() -> None:
    """Migration must contain the UNIQUE constraint SQL on the correct table/columns."""
    migration_path = (
        _REPO_ROOT / "supabase" / "migrations" / "20260703000000_onboarding_unique_constraint.sql"
    )
    content = migration_path.read_text(encoding="utf-8").lower()
    assert "onboarding_responses" in content, "Migration must reference onboarding_responses table"
    assert "unique" in content, "Migration must contain UNIQUE keyword"
    assert "user_id" in content, "Unique constraint must include user_id"
    assert "question_id" in content, "Unique constraint must include question_id"


@pytest.mark.unit
def test_migration_onboarding_answers_v2_exists() -> None:
    """Story 235 AC1: onboarding_answers_v2 migration must exist, with RLS enabled."""
    migration_path = (
        _REPO_ROOT / "supabase" / "migrations" / "20260922010000_onboarding_answers_v2.sql"
    )
    assert migration_path.exists(), "Missing onboarding_answers_v2 migration."
    content = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE public.onboarding_answers_v2" in content
    assert "UNIQUE (user_id, question_id)" in content
    assert re.search(
        r"ALTER TABLE public\.onboarding_answers_v2\s+ENABLE ROW LEVEL SECURITY",
        content,
        re.IGNORECASE,
    ), "AC1c: onboarding_answers_v2 must have RLS enabled (CLAUDE.md: RLS on ALL tables)."
    for cmd in ("select", "insert", "update", "delete"):
        assert re.search(
            rf"CREATE POLICY .*onboarding_answers_v2.*\n?\s*"
            rf"ON public\.onboarding_answers_v2 FOR {cmd.upper()}",
            content,
            re.IGNORECASE,
        ), f"AC1c: missing {cmd.upper()} own-row RLS policy on onboarding_answers_v2."


@pytest.mark.unit
def test_migration_learner_dna_penta_columns_exists() -> None:
    """Story 235 AC1b: learner_dna gains 5 nullable penta_* columns via a new migration."""
    migration_path = (
        _REPO_ROOT / "supabase" / "migrations" / "20260922020000_learner_dna_penta_intelligence.sql"
    )
    assert migration_path.exists(), "Missing learner_dna penta_* columns migration."
    content = migration_path.read_text(encoding="utf-8")
    assert "ALTER TABLE public.learner_dna" in content
    for col in ("penta_iq", "penta_eq", "penta_sq", "penta_ctq", "penta_rrq"):
        assert col in content, f"AC1b: penta column '{col}' missing from migration."
        assert f"CHECK ({col}" in content, f"AC1b: '{col}' missing its 0-100 CHECK constraint."


@pytest.mark.unit
def test_frozen_initial_schema_untouched_by_story_235() -> None:
    """Story 235 must not modify the frozen initial_schema.sql's onboarding_responses
    or learner_dna CREATE TABLE statements (CLAUDE.md: never modify applied migrations)."""
    migration_path = _REPO_ROOT / "supabase" / "migrations" / "20260611000000_initial_schema.sql"
    content = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE public.onboarding_responses" in content
    assert "response_value" in content  # original column shape, unaltered
    assert "dimension_tag" in content


# ══════════════════════════════════════════════════════════════════════════════
# TASK 2 — Schema shape (OnboardingAnswer 3-format, Story 235 frozen-contract change)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_onboarding_answer_importable_from_schemas() -> None:
    from app.modules.assessment.schemas import OnboardingAnswer  # noqa: F401

    assert OnboardingAnswer is not None


@pytest.mark.unit
def test_onboarding_submission_importable_from_schemas() -> None:
    from app.modules.assessment.schemas import OnboardingDiagnosticSubmission  # noqa: F401

    assert OnboardingDiagnosticSubmission is not None


@pytest.mark.unit
def test_onboarding_result_importable_from_schemas() -> None:
    from app.modules.assessment.schemas import OnboardingResult  # noqa: F401

    assert OnboardingResult is not None


@pytest.mark.unit
def test_onboarding_answer_mcq_requires_index_and_text() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer

    with pytest.raises(ValidationError):
        OnboardingAnswer(question_id="q1", format="mcq", response_text="Option A")  # no index
    with pytest.raises(ValidationError):
        OnboardingAnswer(question_id="q1", format="mcq", selected_index=1)  # no text


@pytest.mark.unit
def test_onboarding_answer_one_liner_rejects_blank_text() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer

    with pytest.raises(ValidationError):
        OnboardingAnswer(question_id="q21", format="one_liner", response_text="   ")


@pytest.mark.unit
def test_onboarding_answer_one_liner_rejects_over_1000_chars() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer

    with pytest.raises(ValidationError):
        OnboardingAnswer(question_id="q21", format="one_liner", response_text="x" * 1001)


@pytest.mark.unit
def test_onboarding_answer_response_time_ms_rejects_over_one_hour() -> None:
    """PR #239 review: response_time_ms had no upper bound -- a client-reported
    timing value with no ceiling would corrupt any future per-question timing
    analytics. le=3_600_000 (1 hour) is a generous but principled cap."""
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer

    OnboardingAnswer(
        question_id="q1",
        format="mcq",
        selected_index=0,
        response_text="x",
        response_time_ms=3_600_000,
    )  # exactly at the boundary — must be accepted
    with pytest.raises(ValidationError):
        OnboardingAnswer(
            question_id="q1",
            format="mcq",
            selected_index=0,
            response_text="x",
            response_time_ms=3_600_001,
        )


@pytest.mark.unit
def test_onboarding_answer_true_false_requires_response_bool() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer

    with pytest.raises(ValidationError):
        OnboardingAnswer(question_id="q26", format="true_false")


@pytest.mark.unit
def test_onboarding_answer_rejects_negative_index() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer

    with pytest.raises(ValidationError):
        OnboardingAnswer(question_id="q1", format="mcq", selected_index=-1, response_text="A")


@pytest.mark.unit
def test_onboarding_submission_rejects_29_responses() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingDiagnosticSubmission

    responses = _make_onboarding_answers()[:29]
    with pytest.raises(ValidationError):
        OnboardingDiagnosticSubmission(responses=responses)


@pytest.mark.unit
def test_onboarding_submission_rejects_31_responses() -> None:
    from pydantic import ValidationError

    from app.modules.assessment.schemas import OnboardingAnswer, OnboardingDiagnosticSubmission

    responses = [
        *_make_onboarding_answers(),
        OnboardingAnswer(question_id="q1", format="mcq", selected_index=0, response_text="dup"),
    ]
    with pytest.raises(ValidationError):
        OnboardingDiagnosticSubmission(responses=responses)


@pytest.mark.unit
def test_onboarding_result_has_no_raw_dimension_score_fields() -> None:
    """OnboardingResult must NOT have numeric dimension fields (no raw scores to students)."""
    from app.modules.assessment.schemas import OnboardingResult

    result = OnboardingResult(
        badge_labels=["Sharp Reasoner"], profile_text="You reason carefully.", session_count=0
    )
    result_dict = result.model_dump()
    forbidden_fields = [
        "pattern_recognition",
        "logical_deduction",
        "processing_speed",
        "frustration_tolerance",
        "persistence",
        "help_seeking",
        "goal_orientation",
        "curiosity_index",
        "study_independence",
        "penta_iq",
        "penta_eq",
        "penta_sq",
        "penta_ctq",
        "penta_rrq",
    ]
    for field in forbidden_fields:
        assert field not in result_dict, (
            f"OnboardingResult must not expose raw dimension score '{field}' to students. "
            "CLAUDE.md: no clinical scores shown — descriptive only."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TASK 3 — Question spec (AC2): Q_SPEC / MCQ_OPTION_COUNTS / ALL_QUESTION_IDS / PENTA_*
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_q_spec_has_30_entries_in_the_right_formats() -> None:
    from app.modules.assessment.onboarding_questions import Q_SPEC

    assert len(Q_SPEC) == 30
    mcq = {q for q, f in Q_SPEC.items() if f == "mcq"}
    one_liner = {q for q, f in Q_SPEC.items() if f == "one_liner"}
    true_false = {q for q, f in Q_SPEC.items() if f == "true_false"}
    assert mcq == {f"q{i}" for i in range(1, 21)}
    assert one_liner == {f"q{i}" for i in range(21, 26)}
    assert true_false == {f"q{i}" for i in range(26, 31)}


@pytest.mark.unit
def test_mcq_option_counts_q6_q7_are_four_others_five() -> None:
    """Source PDF: all MCQs are 5-option except Q6/Q7 (Bilingual Bridge), which are 4-option."""
    from app.modules.assessment.onboarding_questions import MCQ_OPTION_COUNTS

    assert MCQ_OPTION_COUNTS["q6"] == 4
    assert MCQ_OPTION_COUNTS["q7"] == 4
    for i in range(1, 21):
        if i not in (6, 7):
            assert MCQ_OPTION_COUNTS[f"q{i}"] == 5, f"q{i} should have 5 options"


@pytest.mark.unit
def test_all_question_ids_matches_q_spec_keys() -> None:
    from app.modules.assessment.onboarding_questions import Q_SPEC

    assert ALL_QUESTION_IDS == frozenset(Q_SPEC)


@pytest.mark.unit
def test_penta_scoring_covers_q16_through_q20_with_5_options_each() -> None:
    from app.modules.assessment.onboarding_questions import PENTA_SCORING

    assert set(PENTA_SCORING) == {"q16", "q17", "q18", "q19", "q20"}
    for qid, mapping in PENTA_SCORING.items():
        assert set(mapping) == {0, 1, 2, 3, 4}, f"{qid} must score all 5 option indices"
        for score in mapping.values():
            assert 0.0 <= score <= 100.0


@pytest.mark.unit
def test_penta_question_map_targets_5_distinct_learner_dna_columns() -> None:
    from app.modules.assessment.onboarding_questions import PENTA_DIMENSIONS, PENTA_QUESTION_MAP

    assert set(PENTA_QUESTION_MAP) == {"q16", "q17", "q18", "q19", "q20"}
    assert set(PENTA_QUESTION_MAP.values()) == set(PENTA_DIMENSIONS)
    assert len(set(PENTA_DIMENSIONS)) == 5


@pytest.mark.unit
def test_all_nine_dimensions_constant_complete() -> None:
    """Unchanged by Story 235 — still used by dna_fusion.py's session-driven path."""
    from app.modules.assessment.onboarding_questions import ALL_NINE_DIMENSIONS

    expected = {
        "pattern_recognition",
        "logical_deduction",
        "processing_speed",
        "frustration_tolerance",
        "persistence",
        "help_seeking",
        "goal_orientation",
        "curiosity_index",
        "study_independence",
    }
    assert set(ALL_NINE_DIMENSIONS) == expected


@pytest.mark.unit
def test_badge_thresholds_no_iq_eq_sq() -> None:
    from app.modules.assessment.onboarding_questions import BADGE_THRESHOLDS, PENTA_BADGE_THRESHOLDS

    for source in (BADGE_THRESHOLDS, PENTA_BADGE_THRESHOLDS):
        for subdim, label in source.items():
            label_lower = label.lower()
            for banned in ["iq", "eq", "sq", "intelligence quotient", "emotional quotient"]:
                assert banned not in label_lower, (
                    f"Badge label for '{subdim}' contains banned IQ/EQ/SQ term: "
                    f"'{banned}' in '{label}'. CLAUDE.md: badge_labels must use plain English."
                )


# ══════════════════════════════════════════════════════════════════════════════
# TASK 4 — DPDP disclaimer and profile prompt (unchanged by Story 235)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_dpdp_disclaimer_ends_with_required_phrase() -> None:
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    assert DPDP_DISCLAIMER.endswith("— Pursuant to DPDP Act 2023.")


@pytest.mark.unit
def test_dpdp_disclaimer_no_iq_eq_sq() -> None:
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    disclaimer_lower = DPDP_DISCLAIMER.lower()
    for banned in ["iq", "eq", "sq", "intelligence quotient"]:
        assert banned not in disclaimer_lower


@pytest.mark.unit
async def test_generate_onboarding_profile_appends_dpdp_disclaimer() -> None:
    from app.modules.assessment.prompts import DPDP_DISCLAIMER, generate_onboarding_profile

    mock_provider = MagicMock()
    mock_provider.complete = AsyncMock(return_value="You reason carefully under pressure.")

    with patch("app.modules.assessment.prompts.get_settings") as mock_settings:
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await generate_onboarding_profile(
            badge_labels=["Sharp Reasoner", "Deep Researcher"],
            provider=mock_provider,
        )

    assert result.endswith("— Pursuant to DPDP Act 2023.")
    assert "You reason carefully" in result
    assert DPDP_DISCLAIMER in result


@pytest.mark.unit
async def test_generate_onboarding_profile_uses_llm_mini_not_a_hardcoded_string() -> None:
    """CLAUDE.md: 'Never hardcode model strings — always use settings.llm_* aliases.'
    Asserts provider.complete() is actually called with settings.llm_mini's live
    value, not just that some model string was passed — a hardcoded literal that
    happened to equal the settings value in every other test's mock would still
    pass those tests but violate this rule."""
    from app.modules.assessment.prompts import generate_onboarding_profile

    mock_provider = MagicMock()
    mock_provider.complete = AsyncMock(return_value="You are a careful, patient learner.")

    with patch("app.modules.assessment.prompts.get_settings") as mock_settings:
        mock_settings.return_value.llm_mini = "a-distinctive-sentinel-model-id"
        await generate_onboarding_profile(
            badge_labels=["Deep Researcher"],
            provider=mock_provider,
        )

    mock_provider.complete.assert_awaited_once()
    assert mock_provider.complete.call_args.kwargs["model"] == "a-distinctive-sentinel-model-id"


# ══════════════════════════════════════════════════════════════════════════════
# TASK 5 — process_onboarding service function (Story 235 rewrite)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_validate_onboarding_responses_accepts_valid_30() -> None:
    from app.modules.assessment.service import _validate_onboarding_responses

    _validate_onboarding_responses(_make_onboarding_answers())  # must not raise


@pytest.mark.unit
def test_validate_onboarding_responses_rejects_duplicate_question_id() -> None:
    from fastapi import HTTPException

    from app.modules.assessment.service import _validate_onboarding_responses

    answers = _make_onboarding_answers()
    answers[1] = answers[0]  # duplicate q1
    with pytest.raises(HTTPException) as exc_info:
        _validate_onboarding_responses(answers)
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_validate_onboarding_responses_rejects_missing_question() -> None:
    """29 unique, non-duplicated question_ids (q30 absent, nothing else wrong) must
    still be rejected — isolates the id_set != ALL_QUESTION_IDS branch specifically,
    since _validate_onboarding_responses has no length check of its own that could
    fire first (previously this test padded back to 30 with a duplicate, which meant
    the duplicate-detection branch fired instead and "missing" was never actually
    exercised in isolation)."""
    from fastapi import HTTPException

    from app.modules.assessment.service import _validate_onboarding_responses

    answers = _make_onboarding_answers()[:29]  # missing q30, 29 unique ids, no duplicates
    with pytest.raises(HTTPException) as exc_info:
        _validate_onboarding_responses(answers)
    assert exc_info.value.status_code == 422
    assert "Missing" in exc_info.value.detail
    assert "q30" in exc_info.value.detail


@pytest.mark.unit
def test_validate_onboarding_responses_rejects_unknown_question_id() -> None:
    """30 ids, no duplicates, one of them not in ALL_QUESTION_IDS — isolates the
    "unknown" half of the id_set != ALL_QUESTION_IDS branch specifically (the
    existing before-any-db-call test swaps q1 for an unknown id too, but that
    simultaneously makes q1 "missing" and the unknown id "unknown" at once, and
    that test's actual purpose is proving supabase.table is never called, not
    isolating this detail message)."""
    from fastapi import HTTPException

    from app.modules.assessment.schemas import OnboardingAnswer
    from app.modules.assessment.service import _validate_onboarding_responses

    answers = _make_onboarding_answers()[:29]  # 29 known ids (q1-q29), q30 dropped
    answers.append(
        OnboardingAnswer(question_id="q_bogus", format="mcq", selected_index=0, response_text="x")
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_onboarding_responses(answers)
    assert exc_info.value.status_code == 422
    assert "Unknown" in exc_info.value.detail
    assert "q_bogus" in exc_info.value.detail


@pytest.mark.unit
def test_validate_onboarding_responses_rejects_format_mismatch() -> None:
    """A question answered with the wrong format (e.g. q1 as true_false) is rejected."""
    from fastapi import HTTPException

    from app.modules.assessment.schemas import OnboardingAnswer
    from app.modules.assessment.service import _validate_onboarding_responses

    answers = _make_onboarding_answers()
    answers[0] = OnboardingAnswer(question_id="q1", format="true_false", response_bool=True)
    with pytest.raises(HTTPException) as exc_info:
        _validate_onboarding_responses(answers)
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_validate_onboarding_responses_rejects_mcq_index_out_of_range() -> None:
    """q6 has only 4 options (indices 0-3) — index 4 must be rejected."""
    from fastapi import HTTPException

    from app.modules.assessment.schemas import OnboardingAnswer
    from app.modules.assessment.service import _validate_onboarding_responses

    answers = _make_onboarding_answers()
    for i, ans in enumerate(answers):
        if ans.question_id == "q6":
            answers[i] = OnboardingAnswer(
                question_id="q6", format="mcq", selected_index=4, response_text="out of range"
            )
    with pytest.raises(HTTPException) as exc_info:
        _validate_onboarding_responses(answers)
    assert exc_info.value.status_code == 422


@pytest.mark.unit
def test_compute_penta_scores_top_options_yield_100_each() -> None:
    from app.modules.assessment.service import _compute_penta_scores

    answers = _make_onboarding_answers(penta_indices=_PENTA_TOP_INDEX)
    scores = _compute_penta_scores(answers)
    assert set(scores) == {"penta_iq", "penta_eq", "penta_sq", "penta_ctq", "penta_rrq"}
    for dim, val in scores.items():
        assert val == pytest.approx(100.0), f"{dim} should be 100.0 for the top-scoring option"


@pytest.mark.unit
def test_compute_penta_scores_low_options_stay_below_badge_threshold() -> None:
    from app.modules.assessment.service import _compute_penta_scores

    answers = _make_onboarding_answers(penta_indices=_PENTA_LOW_INDEX)
    scores = _compute_penta_scores(answers)
    for dim, val in scores.items():
        assert val < 70.0, f"{dim} should be below the badge threshold for the low-scoring option"


@pytest.mark.unit
def test_compute_penta_badge_labels_all_top_yields_all_5_badges() -> None:
    from app.modules.assessment.service import _compute_penta_badge_labels, _compute_penta_scores

    answers = _make_onboarding_answers(penta_indices=_PENTA_TOP_INDEX)
    scores = _compute_penta_scores(answers)
    labels = _compute_penta_badge_labels(scores)
    assert set(labels) == {
        "Sharp Reasoner",
        "Empathetic Responder",
        "Principled Decision-Maker",
        "Fact-Checker",
        "Deep Researcher",
    }


@pytest.mark.unit
def test_compute_penta_badge_labels_all_low_yields_zero_badges() -> None:
    from app.modules.assessment.service import _compute_penta_badge_labels, _compute_penta_scores

    answers = _make_onboarding_answers(penta_indices=_PENTA_LOW_INDEX)
    scores = _compute_penta_scores(answers)
    labels = _compute_penta_badge_labels(scores)
    assert labels == []


@pytest.mark.unit
def test_compute_penta_badge_labels_no_iq_eq_sq() -> None:
    from app.modules.assessment.service import _compute_penta_badge_labels

    scores = {
        "penta_iq": 100.0,
        "penta_eq": 100.0,
        "penta_sq": 100.0,
        "penta_ctq": 100.0,
        "penta_rrq": 100.0,
    }
    labels = _compute_penta_badge_labels(scores)
    for label in labels:
        label_lower = label.lower()
        for banned in ["iq", "eq", "sq", "quotient"]:
            assert banned not in label_lower


@pytest.mark.unit
async def test_process_onboarding_9_behavioral_dims_absent_from_upsert(mock_to_thread) -> None:
    """AC4/AC11: the 9 existing behavioral columns must never be in the upsert payload —
    they stay whatever they already were (NULL for a new row), seeded only by
    dna_fusion.py's session-driven EMA after the student's first completed session."""
    from app.modules.assessment.onboarding_questions import ALL_NINE_DIMENSIONS
    from app.modules.assessment.service import process_onboarding

    answers = _make_onboarding_answers()
    upsert_data_captured: dict = {}

    answers_v2_mock = MagicMock()
    answers_v2_mock.upsert.return_value.execute.return_value = MagicMock(data=[], error=None)

    upsert_mock = MagicMock()

    def _capture_upsert(data, **kwargs):
        upsert_data_captured.update(data if isinstance(data, dict) else {})
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[{"user_id": "user-onb-001"}], error=None)
        return m

    upsert_mock.upsert.side_effect = _capture_upsert

    dna_select_mock = MagicMock()
    dna_select_resp = MagicMock()
    dna_select_resp.data = None
    dna_select_chain = dna_select_mock.select.return_value.eq.return_value.maybe_single.return_value
    dna_select_chain.execute.return_value = dna_select_resp

    supabase = MagicMock()
    supabase.table.side_effect = [dna_select_mock, answers_v2_mock, upsert_mock]

    p1, p2, p3 = _patched_llm()
    with p1 as mock_provider_cls, p2 as mock_settings, p3 as mock_prompts_settings:
        mock_provider_inst = MagicMock()
        mock_provider_inst.complete = AsyncMock(return_value="You reason carefully.")
        mock_provider_cls.return_value = mock_provider_inst
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_prompts_settings.return_value.llm_mini = "gpt-4o-mini"
        await process_onboarding(responses=answers, user_id="user-onb-001", supabase=supabase)

    for dim in ALL_NINE_DIMENSIONS:
        assert dim not in upsert_data_captured, (
            f"AC4: behavioral dimension '{dim}' must not be written by process_onboarding"
        )
    for col in ("penta_iq", "penta_eq", "penta_sq", "penta_ctq", "penta_rrq"):
        assert col in upsert_data_captured, f"AC4: penta column '{col}' missing from upsert"
        assert 0.0 <= upsert_data_captured[col] <= 100.0

    assert upsert_data_captured.get("session_count") == 0
    assert "profile_text" in upsert_data_captured
    assert upsert_data_captured["profile_text"].endswith("— Pursuant to DPDP Act 2023.")


@pytest.mark.unit
async def test_process_onboarding_writes_onboarding_answers_v2_via_upsert_on_conflict(
    mock_to_thread,
) -> None:
    """D173 fix: a resubmission (reassessment) must not dead-end on the table's own
    UNIQUE(user_id, question_id) constraint. process_onboarding upserts on that exact
    conflict target instead of inserting, so a second submission for the same 30
    question_ids overwrites cleanly rather than raising a duplicate-key error."""
    from app.modules.assessment.service import process_onboarding

    supabase = _build_onboarding_supabase()
    answers = _make_onboarding_answers()

    p1, p2, p3 = _patched_llm()
    with p1 as mock_provider_cls, p2 as mock_settings, p3 as mock_prompts_settings:
        mock_provider_inst = MagicMock()
        mock_provider_inst.complete = AsyncMock(return_value="You reason carefully.")
        mock_provider_cls.return_value = mock_provider_inst
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_prompts_settings.return_value.llm_mini = "gpt-4o-mini"
        await process_onboarding(responses=answers, user_id="user-onb-001", supabase=supabase)

    # _build_onboarding_supabase wires onboarding_answers_v2's table() call to a mock
    # whose only configured write method is .upsert — if service.py regresses to
    # .insert(), that call hits an unconfigured MagicMock chain whose .error is
    # itself a (truthy) MagicMock, which process_onboarding would raise as a 500 for.
    # The call completing without raising is itself the regression guard.
    onboarding_calls = [
        c for c in supabase.table.call_args_list if c.args == ("onboarding_answers_v2",)
    ]
    assert len(onboarding_calls) == 1


@pytest.mark.unit
async def test_process_onboarding_write_error_returns_500(mock_to_thread) -> None:
    """Any onboarding_answers_v2 write failure — including a duplicate-key-shaped
    error string — now surfaces as 500, not 409. Duplicate *submission attempts* are
    gated upstream by router.py's Redis SET NX; a (user_id, question_id) conflict at
    the DB layer is absorbed by Step 5's upsert (D173), so if an error reaches this
    branch at all it is a genuine write failure, never an expected duplicate."""
    from fastapi import HTTPException

    from app.modules.assessment.service import process_onboarding

    for error_text in (
        "connection timeout — database unreachable",
        "duplicate key value violates unique constraint",  # no longer special-cased
    ):
        generic_error = MagicMock()
        generic_error.__str__ = lambda s, _t=error_text: _t
        supabase = _build_onboarding_supabase(insert_error=generic_error)
        answers = _make_onboarding_answers()

        with pytest.raises(HTTPException) as exc_info:
            await process_onboarding(responses=answers, user_id="user-onb-001", supabase=supabase)

        assert exc_info.value.status_code == 500


@pytest.mark.unit
async def test_process_onboarding_rejects_invalid_responses_before_any_db_call(
    mock_to_thread,
) -> None:
    """AC4: validation runs first — an invalid submission never reaches the DB at all."""
    from fastapi import HTTPException

    from app.modules.assessment.schemas import OnboardingAnswer
    from app.modules.assessment.service import process_onboarding

    answers = _make_onboarding_answers()
    answers[0] = OnboardingAnswer(
        question_id="unknown_q", format="mcq", selected_index=0, response_text="x"
    )
    supabase = MagicMock()  # no side_effect configured — any table() call would raise StopIteration

    with pytest.raises(HTTPException) as exc_info:
        await process_onboarding(responses=answers, user_id="user-onb-001", supabase=supabase)

    assert exc_info.value.status_code == 422
    supabase.table.assert_not_called()


@pytest.mark.unit
async def test_process_onboarding_profile_text_has_dpdp_disclaimer(mock_to_thread) -> None:
    from app.modules.assessment.service import process_onboarding

    supabase = _build_onboarding_supabase()
    answers = _make_onboarding_answers()

    p1, p2, p3 = _patched_llm()
    with p1 as mock_provider_cls, p2 as mock_settings, p3 as mock_prompts_settings:
        mock_provider_inst = MagicMock()
        mock_provider_inst.complete = AsyncMock(return_value="You think carefully in patterns.")
        mock_provider_cls.return_value = mock_provider_inst
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_prompts_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await process_onboarding(
            responses=answers, user_id="user-onb-001", supabase=supabase
        )

    assert result.profile_text.endswith("— Pursuant to DPDP Act 2023.")


@pytest.mark.unit
async def test_process_onboarding_returns_onboarding_result(mock_to_thread) -> None:
    from app.modules.assessment.schemas import OnboardingResult
    from app.modules.assessment.service import process_onboarding

    supabase = _build_onboarding_supabase()
    answers = _make_onboarding_answers()

    p1, p2, p3 = _patched_llm()
    with p1 as mock_provider_cls, p2 as mock_settings, p3 as mock_prompts_settings:
        mock_provider_inst = MagicMock()
        mock_provider_inst.complete = AsyncMock(return_value="You are curious and precise.")
        mock_provider_cls.return_value = mock_provider_inst
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_prompts_settings.return_value.llm_mini = "gpt-4o-mini"
        result = await process_onboarding(
            responses=answers, user_id="user-onb-001", supabase=supabase
        )

    assert isinstance(result, OnboardingResult)
    result_dict = result.model_dump()
    for field in ["pattern_recognition", "penta_iq", "penta_eq"]:
        assert field not in result_dict


@pytest.mark.unit
async def test_process_onboarding_upsert_row_payload_mapping(mock_to_thread) -> None:
    """All 30 onboarding_answers_v2 rows must carry the right format-specific fields,
    and the write must be an upsert keyed on (user_id, question_id) — D173: a plain
    insert dead-ends every reassessment resubmission on the table's own UNIQUE
    constraint, since the 30 question_ids repeat across attempts for a given user."""
    from app.modules.assessment.service import process_onboarding

    answers = _make_onboarding_answers()
    upsert_rows_captured: list[dict] = []
    on_conflict_captured: list[str] = []

    answers_v2_mock = MagicMock()

    def _capture_upsert(rows, on_conflict=None):
        upsert_rows_captured.extend(rows if isinstance(rows, list) else [rows])
        on_conflict_captured.append(on_conflict)
        m = MagicMock()
        m.execute.return_value = MagicMock(data=[], error=None)
        return m

    answers_v2_mock.upsert.side_effect = _capture_upsert

    upsert_mock = MagicMock()
    upsert_mock.upsert.return_value.execute.return_value = MagicMock(
        data=[{"user_id": "user-onb-001"}], error=None
    )

    dna_select_mock = MagicMock()
    dna_select_resp = MagicMock()
    dna_select_resp.data = None
    dna_select_chain = dna_select_mock.select.return_value.eq.return_value.maybe_single.return_value
    dna_select_chain.execute.return_value = dna_select_resp

    supabase = MagicMock()
    supabase.table.side_effect = [dna_select_mock, answers_v2_mock, upsert_mock]

    p1, p2, p3 = _patched_llm()
    with p1 as mock_provider_cls, p2 as mock_settings, p3 as mock_prompts_settings:
        mock_provider_inst = MagicMock()
        mock_provider_inst.complete = AsyncMock(return_value="You are a precise thinker.")
        mock_provider_cls.return_value = mock_provider_inst
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_prompts_settings.return_value.llm_mini = "gpt-4o-mini"
        await process_onboarding(responses=answers, user_id="user-onb-001", supabase=supabase)

    assert on_conflict_captured == ["user_id,question_id"]
    assert len(upsert_rows_captured) == 30
    by_id = {r["question_id"]: r for r in upsert_rows_captured}
    assert by_id["q1"]["format"] == "mcq"
    assert by_id["q1"]["selected_index"] is not None
    assert by_id["q21"]["format"] == "one_liner"
    assert by_id["q21"]["response_text"]
    assert by_id["q26"]["format"] == "true_false"
    assert by_id["q26"]["response_bool"] is True
    for r in upsert_rows_captured:
        assert r["user_id"] == "user-onb-001"


@pytest.mark.unit
async def test_process_onboarding_upsert_error_returns_500(mock_to_thread) -> None:
    from fastapi import HTTPException

    from app.modules.assessment.service import process_onboarding

    upsert_error = MagicMock()
    upsert_error.__str__ = lambda s: "connection timeout — database unreachable"
    supabase = _build_onboarding_supabase(upsert_error=upsert_error)
    answers = _make_onboarding_answers()

    p1, p2, p3 = _patched_llm()
    with p1 as mock_provider_cls, p2 as mock_settings, p3 as mock_prompts_settings:
        mock_provider_inst = MagicMock()
        mock_provider_inst.complete = AsyncMock(return_value="You are a visual learner.")
        mock_provider_cls.return_value = mock_provider_inst
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_prompts_settings.return_value.llm_mini = "gpt-4o-mini"
        with pytest.raises(HTTPException) as exc_info:
            await process_onboarding(responses=answers, user_id="user-onb-001", supabase=supabase)

    assert exc_info.value.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# TASK 6 — HTTP endpoint (router layer)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_http_422_when_fewer_than_30_responses() -> None:
    payload = {"responses": _make_30_responses()[:29]}
    response = _client.post("/api/assessment/onboarding/submit", json=payload)
    assert response.status_code == 422


@pytest.mark.unit
def test_http_422_when_more_than_30_responses() -> None:
    extra = {"question_id": "q1", "format": "mcq", "selected_index": 1, "response_text": "A"}
    payload = {"responses": _make_30_responses() + [extra]}
    response = _client.post("/api/assessment/onboarding/submit", json=payload)
    assert response.status_code == 422


@pytest.mark.unit
def test_http_422_when_invalid_format() -> None:
    responses = _make_30_responses()
    responses[0]["format"] = "invalid_format"
    response = _client.post("/api/assessment/onboarding/submit", json={"responses": responses})
    assert response.status_code == 422


@pytest.mark.unit
def test_http_422_when_selected_index_negative() -> None:
    responses = _make_30_responses()
    responses[0]["selected_index"] = -1
    response = _client.post("/api/assessment/onboarding/submit", json={"responses": responses})
    assert response.status_code == 422


@pytest.mark.unit
def test_http_409_when_onboarding_already_done() -> None:
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=None)  # SET NX returns None when key already exists

    with patch("app.core.redis.get_redis", return_value=mock_redis):
        response = _client.post(
            "/api/assessment/onboarding/submit",
            json={"responses": _make_30_responses()},
        )

    assert response.status_code == 409


@pytest.mark.unit
def test_http_403_when_not_approved() -> None:
    _app.dependency_overrides[get_settings] = lambda: MagicMock(approved_emails=[])
    try:
        with patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(side_effect=AssertionError("must not be called when unapproved")),
        ):
            response = _client.post(
                "/api/assessment/onboarding/submit",
                json={"responses": _make_30_responses()},
            )
    finally:
        _app.dependency_overrides[get_settings] = _fake_settings

    assert response.status_code == 403


@pytest.mark.unit
def test_http_201_on_success() -> None:
    from app.modules.assessment.schemas import OnboardingResult

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)

    mock_result = OnboardingResult(
        badge_labels=["Sharp Reasoner", "Deep Researcher"],
        profile_text=(
            "You reason carefully and dig into sources. "
            "This assessment reflects your personal learning preferences, not your intelligence "
            "or capability. HIE Learner DNA is not a clinical assessment and does not "
            "diagnose any learning or psychological condition. — Pursuant to DPDP Act 2023."
        ),
        session_count=0,
    )

    with patch("app.core.redis.get_redis", return_value=mock_redis):
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            with patch(
                "app.modules.assessment.service.process_onboarding",
                new=AsyncMock(return_value=mock_result),
            ):
                response = _client.post(
                    "/api/assessment/onboarding/submit",
                    json={"responses": _make_30_responses()},
                )

    assert response.status_code == 201, response.text[:300]
    body = response.json()
    assert "badge_labels" in body
    assert "profile_text" in body
    assert "session_count" in body
    assert body["session_count"] == 0


@pytest.mark.unit
def test_http_redis_set_called_after_success() -> None:
    from app.modules.assessment.schemas import OnboardingResult

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)

    mock_result = OnboardingResult(
        badge_labels=[],
        profile_text="Descriptive text. — Pursuant to DPDP Act 2023.",
        session_count=0,
    )

    with patch("app.core.redis.get_redis", return_value=mock_redis):
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            with patch(
                "app.modules.assessment.service.process_onboarding",
                new=AsyncMock(return_value=mock_result),
            ):
                _client.post(
                    "/api/assessment/onboarding/submit",
                    json={"responses": _make_30_responses()},
                )

    mock_redis.set.assert_called_once_with("user:user-onb-001:onboarding_done", "1", nx=True)


@pytest.mark.unit
def test_http_response_no_raw_dimension_scores() -> None:
    from app.modules.assessment.schemas import OnboardingResult

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)

    mock_result = OnboardingResult(
        badge_labels=["Deep Researcher"],
        profile_text="Descriptive text. — Pursuant to DPDP Act 2023.",
        session_count=0,
    )

    with patch("app.core.redis.get_redis", return_value=mock_redis):
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            with patch(
                "app.modules.assessment.service.process_onboarding",
                new=AsyncMock(return_value=mock_result),
            ):
                response = _client.post(
                    "/api/assessment/onboarding/submit",
                    json={"responses": _make_30_responses()},
                )

    assert response.status_code == 201
    body = response.json()
    for field in ["pattern_recognition", "penta_iq", "penta_eq"]:
        assert field not in body


@pytest.mark.unit
def test_http_profile_text_no_raw_numeric_scores() -> None:
    from app.modules.assessment.schemas import OnboardingResult

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)

    clean_profile = (
        "You tend to think in patterns and ask good questions. — Pursuant to DPDP Act 2023."
    )
    mock_result = OnboardingResult(
        badge_labels=["Sharp Reasoner"], profile_text=clean_profile, session_count=0
    )

    with patch("app.core.redis.get_redis", return_value=mock_redis):
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            with patch(
                "app.modules.assessment.service.process_onboarding",
                new=AsyncMock(return_value=mock_result),
            ):
                response = _client.post(
                    "/api/assessment/onboarding/submit",
                    json={"responses": _make_30_responses()},
                )

    assert response.status_code == 201
    body = response.json()
    raw_float_pattern = re.compile(r"\b\d+\.\d+\b")
    assert raw_float_pattern.search(body["profile_text"]) is None


@pytest.mark.unit
def test_onboarding_router_releases_lock_on_503() -> None:
    from fastapi import HTTPException as HttpExc

    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    with (
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(side_effect=HttpExc(status_code=503, detail="retry")),
        ),
    ):
        response = _client.post(
            "/api/assessment/onboarding/submit",
            json={"responses": _make_30_responses()},
        )

    assert response.status_code == 503
    mock_redis.delete.assert_called()
    deleted_keys = [str(c.args[0]) for c in mock_redis.delete.call_args_list]
    assert any("onboarding_done" in k for k in deleted_keys)
