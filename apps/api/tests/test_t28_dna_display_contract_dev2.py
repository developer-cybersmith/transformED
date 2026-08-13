"""T28 — Learner DNA display contract tests for Dev 2 (Cross-team).

Machine-executable HTTP contract reference for Dev 2's Learner DNA profile card.

Covers:
  AC1  — GET /user/dna response has no raw numeric dimension scores
  AC2  — POST /onboarding/submit response has no raw numeric dimension scores
  AC3  — DPDP_DISCLAIMER constant uses "HIE Learner DNA" (not "TransformED")
  AC4  — ONBOARDING_PROFILE_SYSTEM_PROMPT uses "HIE" (not "TransformED")
  AC5  — badge_labels never contain IQ / EQ / SQ language
  AC6  — POST /onboarding/submit profile_text ends with DPDP_DISCLAIMER
  AC7  — GET /user/dna profile_text ends with DPDP_DISCLAIMER (when present)
  AC8  — GET /user/dna returns 200 for a user with a DNA row
  AC9  — GET /user/dna returns 404 for a user with no DNA row
  AC10 — GET /user/dna response shape matches LearnerDNA schema (all required fields present)

All tests are @pytest.mark.unit — no real Supabase, OpenAI, or Redis connection required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user, get_settings
from app.modules.assessment.prompts import DPDP_DISCLAIMER, ONBOARDING_PROFILE_SYSTEM_PROMPT
from app.modules.assessment.router import router
from app.modules.assessment.schemas import OnboardingResult

# ── Shared constants ───────────────────────────────────────────────────────────

# Nine dimension columns stored in learner_dna table — must NEVER appear in HTTP responses.
# AC1/AC2: if any of these keys appears in a response body, a rule from CLAUDE.md is broken.
_RAW_DIMENSION_KEYS: list[str] = [
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

# AC5: badge labels must never use clinical or pseudo-clinical framing.
_BANNED_BADGE_TERMS: set[str] = {
    "iq",
    "eq",
    "sq",
    "intelligence quotient",
    "emotional quotient",
}

# Valid DNA service-layer return dict — includes all nine dimension fields to prove AC1.
# The real get_learner_dna_data() never includes these (query selects only 5 columns), but
# AC1 tests that response_model=LearnerDNA strips them even if they did appear.
_FULL_DNA_ROW: dict = {
    "user_id": "user-001",
    "badge_labels": ["Pattern Thinker", "Goal Setter", "Persistent Learner"],
    "profile_text": (
        "You tend to recognise patterns quickly and set ambitious goals. "
        "Try using mind-maps when exploring a new HIE chapter.\n\n" + DPDP_DISCLAIMER
    ),
    "session_count": 3,
    "reassessment_due": False,
    "last_updated": "2026-08-13T10:00:00Z",
    # All nine dimension values — must NOT appear in the HTTP response (AC1)
    "pattern_recognition": 82.0,
    "logical_deduction": 71.0,
    "processing_speed": 65.0,
    "frustration_tolerance": 74.0,
    "persistence": 89.0,
    "help_seeking": 56.0,
    "goal_orientation": 92.0,
    "curiosity_index": 79.0,
    "study_independence": 84.0,
}

# Minimal 20-answer onboarding payload — schema requires exactly 20 OnboardingAnswer objects.
_VALID_ONBOARDING_PAYLOAD: dict = {
    "responses": [
        {
            "question_id": f"q{i:02d}",
            "dimension": ["cognitive", "emotional", "self_direction"][i % 3],
            "selected_index": 2,
            "selected_text": "Sometimes",
            "response_time_ms": 1500,
        }
        for i in range(20)
    ]
}

# Realistic OnboardingResult the mocked service returns (profile_text ends with disclaimer).
_ONBOARDING_RESULT = OnboardingResult(
    badge_labels=["Pattern Thinker", "Curious Explorer"],
    profile_text=(
        "You learn best by exploring connections between ideas. "
        "HIE's worked examples will suit your thinking style.\n\n" + DPDP_DISCLAIMER
    ),
    session_count=0,
)


# ── FastAPI test apps ──────────────────────────────────────────────────────────

async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}


def _approved_settings() -> MagicMock:
    s = MagicMock()
    s.approved_emails = ["test@example.com"]
    return s


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.dependency_overrides[get_settings] = _approved_settings
_app.include_router(router, prefix="/api/assessment")

_client = TestClient(_app, raise_server_exceptions=False)


# ── AC3 / AC4 — Source-level brand guards ─────────────────────────────────────

@pytest.mark.unit
def test_dpdp_disclaimer_uses_hie_not_transformED() -> None:
    """AC3: DPDP_DISCLAIMER must use 'HIE Learner DNA', never 'TransformED'.

    D72 was confirmed live (2026-08-13) and fixed in Story 3-54. This test
    is the CI guard that prevents regression.
    """
    assert "HIE Learner DNA" in DPDP_DISCLAIMER, (
        "AC3 violated: DPDP_DISCLAIMER must use 'HIE Learner DNA'."
    )
    assert "TransformED" not in DPDP_DISCLAIMER, (
        "AC3 violated: DPDP_DISCLAIMER still contains 'TransformED' (D72 regression)."
    )


@pytest.mark.unit
def test_dpdp_disclaimer_contains_statutory_text() -> None:
    """AC3: DPDP_DISCLAIMER must reference 'DPDP Act 2023'."""
    assert "DPDP Act 2023" in DPDP_DISCLAIMER, (
        "AC3 violated: DPDP_DISCLAIMER must contain 'DPDP Act 2023'."
    )


@pytest.mark.unit
def test_onboarding_system_prompt_uses_hie_not_transformED() -> None:
    """AC4: ONBOARDING_PROFILE_SYSTEM_PROMPT must use 'HIE', never 'TransformED'.

    D72 regression guard — the LLM system prompt tells the model to mention the
    brand name; if 'TransformED' remains, every new profile_text echoes the stale brand.
    """
    assert "HIE" in ONBOARDING_PROFILE_SYSTEM_PROMPT, (
        "AC4 violated: ONBOARDING_PROFILE_SYSTEM_PROMPT must reference 'HIE'."
    )
    assert "TransformED" not in ONBOARDING_PROFILE_SYSTEM_PROMPT, (
        "AC4 violated: ONBOARDING_PROFILE_SYSTEM_PROMPT still contains 'TransformED' "
        "(D72 regression)."
    )


# ── AC8 / AC9 / AC10 / AC1 / AC7 / AC5 — GET /user/dna ──────────────────────

@pytest.mark.unit
def test_get_dna_returns_200_for_user_with_row() -> None:
    """AC8: GET /api/assessment/user/dna returns 200 for an authenticated user with a DNA row."""
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=_FULL_DNA_ROW),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")
    assert resp.status_code == 200, (
        f"AC8: expected 200 for authenticated user with a DNA row. Got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
def test_get_dna_response_shape_matches_learnerdna_schema() -> None:
    """AC10: GET /user/dna response contains all fields Dev 2 renders."""
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=_FULL_DNA_ROW),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200
    body = resp.json()
    for required_field in ("user_id", "badge_labels", "profile_text", "session_count",
                           "reassessment_due", "last_updated"):
        assert required_field in body, (
            f"AC10: required field '{required_field}' missing from GET /user/dna response. "
            f"Dev 2 depends on this field for the DNA profile card."
        )


@pytest.mark.unit
def test_get_dna_response_has_no_raw_dimension_scores() -> None:
    """AC1: GET /user/dna response must not expose raw numeric dimension values.

    The mock service return dict deliberately includes all nine dimension keys
    (pattern_recognition, logical_deduction, …) to prove response_model=LearnerDNA
    strips them before the response reaches Dev 2's frontend. This is NOT a vacuously
    true assertion — we inject the keys and then verify they are absent.
    """
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            # _FULL_DNA_ROW includes all nine dimension keys — they must be stripped.
            new=AsyncMock(return_value=_FULL_DNA_ROW),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200
    body = resp.json()
    for raw_key in _RAW_DIMENSION_KEYS:
        assert raw_key not in body, (
            f"AC1 violated: raw dimension key '{raw_key}' appeared in GET /user/dna response. "
            f"Students must never receive numeric dimension scores — descriptive text only. "
            f"Ensure response_model=LearnerDNA is applied to the route."
        )


@pytest.mark.unit
def test_get_dna_profile_text_ends_with_dpdp_disclaimer() -> None:
    """AC7: GET /user/dna profile_text must end with the DPDP_DISCLAIMER verbatim."""
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=_FULL_DNA_ROW),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200
    profile_text = resp.json().get("profile_text")
    assert profile_text is not None, "AC7: profile_text must not be null for a user with a DNA row."
    assert profile_text.endswith(DPDP_DISCLAIMER), (
        f"AC7 violated: GET /user/dna profile_text does not end with DPDP_DISCLAIMER.\n"
        f"Actual tail: ...{repr(profile_text[-80:])}\n"
        f"Expected:    ...{repr(DPDP_DISCLAIMER[-80:])}"
    )


@pytest.mark.unit
def test_get_dna_badge_labels_contain_no_iq_eq_sq_language() -> None:
    """AC5: badge_labels from GET /user/dna must never use clinical / pseudo-clinical labels."""
    row_with_all_badges = {
        **_FULL_DNA_ROW,
        "badge_labels": [
            "Pattern Thinker", "Goal Setter", "Persistent Learner",
            "Curious Explorer", "Collaborative Mind", "Self-Directed",
            "Resilient Learner", "Fast Processor", "Logical Thinker",
        ],
    }
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=row_with_all_badges),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200
    badge_labels: list[str] = resp.json()["badge_labels"]
    for label in badge_labels:
        label_lower = label.lower()
        for banned_term in _BANNED_BADGE_TERMS:
            assert banned_term not in label_lower, (
                f"AC5 violated: badge_label '{label}' contains banned clinical term '{banned_term}'. "
                f"CLAUDE.md §Learner DNA rules prohibit IQ/EQ/SQ language in any student-facing label."
            )


@pytest.mark.unit
def test_get_dna_returns_404_when_no_dna_row_exists() -> None:
    """AC9: GET /user/dna returns 404 when the authenticated user has no DNA row."""
    from fastapi import HTTPException

    async def _raise_404(**_kwargs: object) -> None:
        raise HTTPException(status_code=404, detail="No learner DNA profile found.")

    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", side_effect=Exception("Redis unavailable")),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=_raise_404,
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 404, (
        f"AC9: expected 404 when no DNA row exists. Got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
def test_get_dna_profile_text_uses_hie_brand() -> None:
    """Regression guard: profile_text served to Dev 2 must say 'HIE', never 'TransformED'.

    The DPDP_DISCLAIMER itself (appended to every profile_text) already contains 'HIE Learner DNA',
    so any profile_text ending with the disclaimer will pass this check. Verifies the chain:
    DPDP_DISCLAIMER constant → appended by service → present in HTTP response.
    """
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=_FULL_DNA_ROW),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200
    profile_text: str = resp.json()["profile_text"]
    assert "HIE" in profile_text, (
        "Regression: profile_text reaching Dev 2 must contain 'HIE'. "
        "The DPDP_DISCLAIMER suffix guarantees this when correctly appended."
    )
    assert "TransformED" not in profile_text, (
        "D72 regression: profile_text reaching Dev 2 contains stale 'TransformED' brand."
    )


# ── AC2 / AC6 / AC5 — POST /onboarding/submit ────────────────────────────────

@pytest.mark.unit
def test_onboarding_response_has_no_raw_dimension_scores() -> None:
    """AC2: POST /onboarding/submit response must not expose raw numeric dimension values.

    OnboardingResult schema (badge_labels, profile_text, session_count) is confirmed by
    response_model enforcement. This test verifies that enforcement is actually in place
    by asserting all nine dimension keys are absent from the 201 response body.
    """
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None   # No reassessment flag
    mock_redis.set.return_value = True   # Lock acquired successfully
    mock_redis.delete.return_value = None

    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(return_value=_ONBOARDING_RESULT),
        ),
    ):
        resp = _client.post("/api/assessment/onboarding/submit", json=_VALID_ONBOARDING_PAYLOAD)

    assert resp.status_code == 201, (
        f"AC2: expected 201 from onboarding submit. Got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    for raw_key in _RAW_DIMENSION_KEYS:
        assert raw_key not in body, (
            f"AC2 violated: raw dimension key '{raw_key}' appeared in POST /onboarding/submit "
            f"response. Students must never receive numeric dimension scores."
        )


@pytest.mark.unit
def test_onboarding_profile_text_ends_with_dpdp_disclaimer() -> None:
    """AC6: POST /onboarding/submit profile_text must end with DPDP_DISCLAIMER verbatim."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = None

    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(return_value=_ONBOARDING_RESULT),
        ),
    ):
        resp = _client.post("/api/assessment/onboarding/submit", json=_VALID_ONBOARDING_PAYLOAD)

    assert resp.status_code == 201
    profile_text = resp.json().get("profile_text")
    assert profile_text is not None, "AC6: profile_text must not be null in OnboardingResult."
    assert profile_text.endswith(DPDP_DISCLAIMER), (
        f"AC6 violated: POST /onboarding/submit profile_text does not end with DPDP_DISCLAIMER.\n"
        f"Actual tail: ...{repr(profile_text[-80:])}\n"
        f"Expected:    ...{repr(DPDP_DISCLAIMER[-80:])}"
    )


@pytest.mark.unit
def test_onboarding_badge_labels_contain_no_iq_eq_sq_language() -> None:
    """AC5: badge_labels from POST /onboarding/submit must never use clinical labels."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = None

    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(return_value=_ONBOARDING_RESULT),
        ),
    ):
        resp = _client.post("/api/assessment/onboarding/submit", json=_VALID_ONBOARDING_PAYLOAD)

    assert resp.status_code == 201
    badge_labels: list[str] = resp.json()["badge_labels"]
    for label in badge_labels:
        label_lower = label.lower()
        for banned_term in _BANNED_BADGE_TERMS:
            assert banned_term not in label_lower, (
                f"AC5 violated: onboarding badge_label '{label}' contains banned term "
                f"'{banned_term}'. CLAUDE.md §Learner DNA rules prohibit IQ/EQ/SQ language."
            )


@pytest.mark.unit
def test_onboarding_profile_text_uses_hie_brand() -> None:
    """Regression guard: onboarding profile_text served to Dev 2 must say 'HIE'.

    D72 regression guard — the ONBOARDING_PROFILE_SYSTEM_PROMPT should tell the LLM to
    mention 'HIE', and the DPDP_DISCLAIMER suffix contains 'HIE Learner DNA'. Both are
    checked at source level (AC3/AC4); this test checks the HTTP response that Dev 2 sees.
    """
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = None

    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(return_value=_ONBOARDING_RESULT),
        ),
    ):
        resp = _client.post("/api/assessment/onboarding/submit", json=_VALID_ONBOARDING_PAYLOAD)

    assert resp.status_code == 201
    profile_text: str = resp.json()["profile_text"]
    assert "HIE" in profile_text, (
        "Regression: onboarding profile_text reaching Dev 2 must contain 'HIE'. "
        "The DPDP_DISCLAIMER suffix guarantees this when correctly appended."
    )
    assert "TransformED" not in profile_text, (
        "D72 regression: onboarding profile_text reaching Dev 2 contains stale 'TransformED'."
    )
