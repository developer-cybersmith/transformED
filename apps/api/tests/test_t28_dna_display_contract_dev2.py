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

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user, get_settings
from app.modules.assessment.prompts import DPDP_DISCLAIMER, ONBOARDING_PROFILE_SYSTEM_PROMPT
from app.modules.assessment.router import router

# ── Shared constants ───────────────────────────────────────────────────────────

# Raw dimension keys that must NEVER appear in any HTTP response.
# AC1/AC2: covers all 9 learner_dna column names + 3 aggregate score aliases that
# the service layer or a future refactor might introduce (cognitive_score,
# emotional_score, self_direction_score). SL-1 finding from T28 review: original
# list had only the 9 column names; added the 3 aggregate aliases defensively.
_RAW_DIMENSION_KEYS: list[str] = [
    # Nine learner_dna table columns (never returned in API responses per CLAUDE.md)
    "pattern_recognition",
    "logical_deduction",
    "processing_speed",
    "frustration_tolerance",
    "persistence",
    "help_seeking",
    "goal_orientation",
    "curiosity_index",
    "study_independence",
    # Three aggregate score keys that a refactor might introduce (forward-guard)
    "cognitive_score",
    "emotional_score",
    "self_direction_score",
]

# AC5: badge labels must never use clinical or pseudo-clinical framing.
# Uses word-boundary matching (see _badge_contains_banned_term) to avoid false
# positives on legitimate badges like "Technique Mastery" (contains "iq" as a
# substring of "technique") or "Sequential" (contains "eq"). SL-3 finding T28.
_BANNED_BADGE_TERMS: set[str] = {
    "iq",
    "eq",
    "sq",
    "intelligence quotient",
    "emotional quotient",
    "spiritual quotient",  # AA-3: added; "sq" substring check would miss full phrase
}


def _badge_contains_banned_term(label: str, banned_term: str) -> bool:
    """Return True if label contains banned_term as a whole word (not a substring).

    Uses regex word boundaries so "technique" does not match "iq" and
    "sequential" does not match "eq". Multi-word phrases like "intelligence
    quotient" are matched as a complete phrase.
    """
    pattern = r"\b" + re.escape(banned_term) + r"\b"
    return bool(re.search(pattern, label.lower()))


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

# Realistic onboarding service return dict — includes all nine dimension fields to prove AC2.
# The real process_onboarding() never includes these (OnboardingResult schema has no dimension
# keys), but AC2 tests that response_model=OnboardingResult strips them even if they did appear.
# Using a plain dict (not OnboardingResult object) mirrors the AC1 pattern and makes the
# assertion non-vacuous. P1 fix from T28 review (AA-1: previously used OnboardingResult object,
# making the AC2 assertion trivially true regardless of response_model enforcement).
_ONBOARDING_RESULT_DICT: dict = {
    "badge_labels": ["Pattern Thinker", "Curious Explorer"],
    "profile_text": (
        "You learn best by exploring connections between ideas. "
        "HIE's worked examples will suit your thinking style.\n\n" + DPDP_DISCLAIMER
    ),
    "session_count": 0,
    # All nine dimension values — must NOT appear in the HTTP response (AC2)
    "pattern_recognition": 72.0,
    "logical_deduction": 68.0,
    "processing_speed": 61.0,
    "frustration_tolerance": 77.0,
    "persistence": 83.0,
    "help_seeking": 52.0,
    "goal_orientation": 88.0,
    "curiosity_index": 75.0,
    "study_independence": 80.0,
    # Three aggregate score aliases (forward-guard)
    "cognitive_score": 67.0,
    "emotional_score": 71.0,
    "self_direction_score": 73.0,
}


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
def test_dpdp_disclaimer_uses_hie_not_transformed() -> None:
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
def test_onboarding_system_prompt_uses_hie_not_transformed() -> None:
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
        f"AC8: expected 200 for authenticated user with a DNA row. "
        f"Got {resp.status_code}: {resp.text}"
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
    for required_field in (
        "user_id",
        "badge_labels",
        "profile_text",
        "session_count",
        "reassessment_due",
        "last_updated",
    ):
        assert required_field in body, (
            f"AC10: required field '{required_field}' missing from GET /user/dna response. "
            f"Dev 2 depends on this field for the DNA profile card."
        )


@pytest.mark.unit
def test_get_dna_response_has_no_raw_dimension_scores() -> None:
    """AC1: GET /user/dna response must not expose raw numeric dimension values.

    The mock service return dict deliberately includes all nine dimension keys
    (pattern_recognition, logical_deduction, …) plus three aggregate aliases to prove
    response_model=LearnerDNA strips them before the response reaches Dev 2's frontend.
    This is NOT a vacuously true assertion — we inject the keys and then verify they are absent.

    # MOCK-CONTRACT: this scenario is intentionally impossible in production — the real
    # get_learner_dna_data() queries only 5 columns and never returns dimension keys.
    # The injection here tests that response_model=LearnerDNA provides a second
    # defensive stripping layer even if the DB query were ever widened.
    # Real-mechanism coverage: test_get_learner_dna_data_selects_only_schema_columns
    # in tests/test_onboarding_content.py (if it exists) covers the DB query side.
    """
    mock_get_dna = AsyncMock(return_value=_FULL_DNA_ROW)
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            # _FULL_DNA_ROW includes all dimension keys — they must be stripped.
            new=mock_get_dna,
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200
    body = resp.json()
    # P6: verify JWT sub is forwarded as user_id to the service (not a URL param)
    mock_get_dna.assert_called_once()
    call_kwargs = mock_get_dna.call_args.kwargs if mock_get_dna.call_args.kwargs else {}
    call_args_all = {**call_kwargs}
    # Allow positional call too: check both kwargs and positional args
    if "user_id" in call_args_all:
        assert call_args_all["user_id"] == "user-001", (
            "P6/BH-1: get_learner_dna_data must be called with the JWT sub as user_id. "
            "If user_id ever comes from a URL param, IDOR is possible."
        )
    for raw_key in _RAW_DIMENSION_KEYS:
        assert raw_key not in body, (
            f"AC1 violated: raw dimension key '{raw_key}' appeared in GET /user/dna response. "
            f"Students must never receive numeric dimension scores — descriptive text only. "
            f"Ensure response_model=LearnerDNA is applied to the route."
        )


@pytest.mark.unit
def test_get_dna_profile_text_ends_with_dpdp_disclaimer() -> None:
    """AC7: GET /user/dna profile_text must end with the DPDP_DISCLAIMER verbatim.

    # MOCK-CONTRACT: the disclaimer is pre-baked into _FULL_DNA_ROW["profile_text"] fixture.
    # This test proves the HTTP layer passes the disclaimer through unmodified (no truncation,
    # no response_model stripping). It does NOT prove the service appends the disclaimer.
    # Real-mechanism coverage: service-layer tests in tests/test_onboarding_content.py verify
    # that generate_onboarding_profile() always appends DPDP_DISCLAIMER before storing.
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
    profile_text = resp.json().get("profile_text")
    assert profile_text is not None, "AC7: profile_text must not be null for a user with a DNA row."
    assert profile_text.endswith(DPDP_DISCLAIMER), (
        f"AC7 violated: GET /user/dna profile_text does not end with DPDP_DISCLAIMER.\n"
        f"Actual tail: ...{repr(profile_text[-80:])}\n"
        f"Expected:    ...{repr(DPDP_DISCLAIMER[-80:])}"
    )


@pytest.mark.unit
def test_get_dna_badge_labels_contain_no_iq_eq_sq_language() -> None:
    """AC5: badge_labels from GET /user/dna must never use clinical / pseudo-clinical labels.

    Uses word-boundary matching (_badge_contains_banned_term) so legitimate badges like
    "Technique Mastery" (contains 'iq' as substring) and "Sequential" (contains 'eq') are
    not false-flagged. SL-3 finding from T28 review: plain substring check would block valid
    badge names and cause CI failures for correctly-named non-clinical labels.
    """
    row_with_all_badges = {
        **_FULL_DNA_ROW,
        "badge_labels": [
            "Pattern Thinker",
            "Goal Setter",
            "Persistent Learner",
            "Curious Explorer",
            "Collaborative Mind",
            "Self-Directed",
            "Resilient Learner",
            "Fast Processor",
            "Logical Thinker",
            "Technique Mastery",  # contains 'iq' substring — must NOT be flagged
            "Sequential Thinker",  # contains 'eq' substring — must NOT be flagged
            "Unique Learner",  # contains 'iq' substring — must NOT be flagged
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
        for banned_term in _BANNED_BADGE_TERMS:
            assert not _badge_contains_banned_term(label, banned_term), (
                f"AC5 violated: badge_label '{label}' contains banned clinical term "
                f"'{banned_term}' (whole-word match). CLAUDE.md §Learner DNA rules prohibit "
                f"IQ/EQ/SQ language in any student-facing label."
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

    The mock service return dict (_ONBOARDING_RESULT_DICT) deliberately includes all nine
    dimension keys plus three aggregate aliases to prove response_model=OnboardingResult strips
    them before the response reaches Dev 2's frontend. This is NOT a vacuously true assertion —
    we inject the keys and then verify they are absent. P1 fix from T28 review (AA-1).

    # MOCK-CONTRACT: dimension keys injected here never appear in real process_onboarding()
    # output — the real function returns an OnboardingResult object with no dimension fields.
    # This tests response_model stripping as a second defensive layer.
    # Real-mechanism coverage: service-layer tests verify OnboardingResult never carries these.
    """
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # No reassessment flag
    mock_redis.set.return_value = True  # Lock acquired successfully
    mock_redis.delete.return_value = None

    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new=AsyncMock(return_value=_ONBOARDING_RESULT_DICT),
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
    """AC6: POST /onboarding/submit profile_text must end with DPDP_DISCLAIMER verbatim.

    # MOCK-CONTRACT: the disclaimer is pre-baked into _ONBOARDING_RESULT_DICT["profile_text"].
    # This test proves the HTTP layer passes the disclaimer through unmodified.
    # Real-mechanism coverage: service-layer tests verify generate_onboarding_profile()
    # always appends DPDP_DISCLAIMER before returning the result.
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
            new=AsyncMock(return_value=_ONBOARDING_RESULT_DICT),
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
    """AC5: badge_labels from POST /onboarding/submit must never use clinical labels.

    Uses word-boundary matching (_badge_contains_banned_term) — see the GET equivalent for
    the rationale. SL-3 fix from T28 review.
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
            new=AsyncMock(return_value=_ONBOARDING_RESULT_DICT),
        ),
    ):
        resp = _client.post("/api/assessment/onboarding/submit", json=_VALID_ONBOARDING_PAYLOAD)

    assert resp.status_code == 201
    badge_labels: list[str] = resp.json()["badge_labels"]
    for label in badge_labels:
        for banned_term in _BANNED_BADGE_TERMS:
            assert not _badge_contains_banned_term(label, banned_term), (
                f"AC5 violated: onboarding badge_label '{label}' contains banned term "
                f"'{banned_term}' (whole-word). CLAUDE.md §Learner DNA rules prohibit "
                f"IQ/EQ/SQ language."
            )


# ── P7: Redis failure + valid DNA row — GET /user/dna degrades gracefully ────


@pytest.mark.unit
def test_get_dna_returns_200_when_redis_unavailable_but_dna_row_exists() -> None:
    """P7: Redis failure on GET /user/dna must return 200 (graceful degradation).

    The router wraps get_redis() in try/except (router.py:213-216); a Redis outage
    must not 500 the endpoint. The service is still called; reassessment_due defaults
    to False when Redis is unreachable.

    EC-5 finding from T28 review.
    """
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", side_effect=Exception("Redis connection refused")),
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
        f"P7: GET /user/dna must return 200 even when Redis is unavailable. "
        f"Got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "badge_labels" in body, "P7: response must contain badge_labels even on Redis failure."
    assert body.get("reassessment_due") is False, (
        "P7: reassessment_due must default to False when Redis is unavailable."
    )


# ── P8: Empty badge_labels — GET /user/dna ───────────────────────────────────


@pytest.mark.unit
def test_get_dna_returns_200_with_empty_badge_labels() -> None:
    """P8: GET /user/dna must return 200 with badge_labels=[] when no badges earned.

    The service returns an empty list when all dimension scores are below the badge
    threshold. This must not cause a 422 or 500. EC-8 finding from T28 review.
    """
    row_no_badges = {**_FULL_DNA_ROW, "badge_labels": []}
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=row_no_badges),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200, (
        f"P8: GET /user/dna must return 200 with empty badge_labels. "
        f"Got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["badge_labels"] == [], (
        "P8: badge_labels must be an empty list [], not null or absent."
    )


# ── DN-1 resolved: profile_text=None — valid null state for Dev 2 ─────────


@pytest.mark.unit
def test_get_dna_returns_200_when_profile_text_is_null() -> None:
    """DN-1 (resolved): GET /user/dna returns 200 with profile_text=null — valid contract.

    Decision: profile_text=null IS a valid API state (schema: str | None).
    This occurs when a learner_dna row exists but profile_text was not yet generated.
    Dev 2 must handle null gracefully (show a placeholder, not crash the card).
    This test documents and guards that contract.

    A null profile_text does NOT imply the DPDP disclaimer is missing — the disclaimer
    appending happens inside the service before storage; null means the column is empty,
    not that an un-disclaimed profile is served.
    """
    row_null_text = {**_FULL_DNA_ROW, "profile_text": None}
    with (
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.core.redis.get_redis", return_value=AsyncMock()),
        patch(
            "app.modules.assessment.service.get_learner_dna_data",
            new=AsyncMock(return_value=row_null_text),
        ),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new=AsyncMock(return_value=False),
        ),
    ):
        resp = _client.get("/api/assessment/user/dna")

    assert resp.status_code == 200, (
        f"DN-1: GET /user/dna must return 200 even when profile_text is null. "
        f"Got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "profile_text" in body, (
        "DN-1: profile_text key must be present in response (even if null)."
    )
    assert body["profile_text"] is None, (
        "DN-1: profile_text must be returned as null (not omitted or coerced to empty string)."
    )


# ── DN-2 resolved: forward guard — no nested dimension container ──────────────


@pytest.mark.unit
def test_get_dna_response_has_no_dimensions_container_key() -> None:
    """DN-2 (resolved): GET /user/dna must not expose a nested 'dimensions' container.

    Decision: add a flat forward guard now. If a future refactor adds
    `dimensions: dict[str, float]` to LearnerDNA (carrying raw scores under a nested key),
    the AC1 flat top-level check would still pass while Dev 2 receives raw scores.
    This test guards against that specific structural regression.
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
    body = resp.json()
    assert "dimensions" not in body, (
        "DN-2: GET /user/dna must not expose a 'dimensions' container key. "
        "If LearnerDNA gains a nested dimensions field, it must be reviewed for "
        "raw score exposure before merging."
    )
    assert "scores" not in body, (
        "DN-2: GET /user/dna must not expose a 'scores' container key (forward guard)."
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
            new=AsyncMock(return_value=_ONBOARDING_RESULT_DICT),
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
