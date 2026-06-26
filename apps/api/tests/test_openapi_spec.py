"""Verify the assessment OpenAPI spec is complete, correct, and free of banned fields.

Builds a minimal FastAPI app from the assessment router — no env vars, Redis,
or DB required. All tests are @pytest.mark.unit.

AC coverage:
  AC1 — All 5 assessment paths present
  AC2 — Correct HTTP methods on each path
  AC3 — No banned field: transcript
  AC4 — No banned field: duration_seconds
  AC5 — OnboardingDiagnosticSubmission has responses[], not subject/grade_level
  AC6 — TeachbackSubmission has response_text, not transcript
  AC7 — LearnerDNA has badge_labels and profile_text (no raw numeric scores exposed)
  AC8 — spec is valid JSON (structural sanity)
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI

from app.modules.assessment.router import router as assessment_router

# ── Fixture ───────────────────────────────────────────────────────────────────

ASSESSMENT_PREFIX = "/api/assessment"
EXPECTED_PATHS = {
    f"{ASSESSMENT_PREFIX}/quiz",
    f"{ASSESSMENT_PREFIX}/teachback",
    f"{ASSESSMENT_PREFIX}/session/{{session_id}}/report",
    f"{ASSESSMENT_PREFIX}/user/dna",
    f"{ASSESSMENT_PREFIX}/onboarding/submit",
}


@pytest.fixture(scope="module")
def spec() -> dict:
    """Build a minimal FastAPI app with only the assessment router, return its spec.

    Prefix must match apps/api/app/main.py:112 — keep in sync.
    """
    mini = FastAPI(title="HIE Assessment API Test", version="0.0.1")
    mini.include_router(assessment_router, prefix=ASSESSMENT_PREFIX)
    return mini.openapi()


@pytest.fixture(scope="module")
def spec_str(spec: dict) -> str:
    """Serialised spec for full-text searches (banned field checks)."""
    return json.dumps(spec)


@pytest.fixture(scope="module")
def schemas(spec: dict) -> dict:
    """Convenience accessor for spec['components']['schemas']."""
    return spec.get("components", {}).get("schemas", {})


# ── AC1: All 5 paths present ──────────────────────────────────────────────────

@pytest.mark.unit
def test_all_five_assessment_paths_exist(spec: dict) -> None:
    actual = set(spec.get("paths", {}).keys())
    missing = EXPECTED_PATHS - actual
    assert not missing, f"Missing assessment paths: {sorted(missing)}"


# ── AC2: Correct HTTP methods ─────────────────────────────────────────────────

@pytest.mark.unit
def test_quiz_endpoint_is_post(spec: dict) -> None:
    assert "post" in spec["paths"][f"{ASSESSMENT_PREFIX}/quiz"]


@pytest.mark.unit
def test_teachback_endpoint_is_post(spec: dict) -> None:
    assert "post" in spec["paths"][f"{ASSESSMENT_PREFIX}/teachback"]


@pytest.mark.unit
def test_session_report_endpoint_is_get(spec: dict) -> None:
    assert "get" in spec["paths"][f"{ASSESSMENT_PREFIX}/session/{{session_id}}/report"]


@pytest.mark.unit
def test_learner_dna_endpoint_is_get(spec: dict) -> None:
    assert "get" in spec["paths"][f"{ASSESSMENT_PREFIX}/user/dna"]


@pytest.mark.unit
def test_onboarding_submit_endpoint_is_post(spec: dict) -> None:
    assert "post" in spec["paths"][f"{ASSESSMENT_PREFIX}/onboarding/submit"]


# ── AC3: No banned field — transcript ────────────────────────────────────────

@pytest.mark.unit
def test_spec_contains_no_transcript_field(spec_str: str) -> None:
    assert '"transcript"' not in spec_str, (
        'Field "transcript" found in spec — implies STT which is banned (CLAUDE.md §dev-rules)'
    )


# ── AC4: No banned field — duration_seconds ───────────────────────────────────

@pytest.mark.unit
def test_spec_contains_no_duration_seconds_field(spec_str: str) -> None:
    assert "duration_seconds" not in spec_str, (
        '"duration_seconds" found in spec — implies a teach-back timer which is banned (CLAUDE.md §dev-rules)'
    )


# ── AC5: OnboardingDiagnosticSubmission shape ─────────────────────────────────

@pytest.mark.unit
def test_onboarding_submission_has_responses_field(schemas: dict) -> None:
    props = schemas.get("OnboardingDiagnosticSubmission", {}).get("properties", {})
    assert "responses" in props, (
        "OnboardingDiagnosticSubmission missing 'responses' field — "
        "Dev 2 must use responses[], not subject+grade_level"
    )


@pytest.mark.unit
def test_onboarding_submission_has_no_subject_or_grade_level(schemas: dict) -> None:
    props = schemas.get("OnboardingDiagnosticSubmission", {}).get("properties", {})
    assert "subject" not in props, "'subject' found in OnboardingDiagnosticSubmission — old shape, must be removed"
    assert "grade_level" not in props, "'grade_level' found in OnboardingDiagnosticSubmission — old shape, must be removed"


# ── AC6: TeachbackSubmission shape ────────────────────────────────────────────

@pytest.mark.unit
def test_teachback_submission_has_response_text(schemas: dict) -> None:
    props = schemas.get("TeachbackSubmission", {}).get("properties", {})
    assert "response_text" in props, (
        "TeachbackSubmission missing 'response_text' — Dev 2 must send typed text, not a transcript"
    )


@pytest.mark.unit
def test_teachback_submission_has_no_transcript_field(schemas: dict) -> None:
    props = schemas.get("TeachbackSubmission", {}).get("properties", {})
    assert "transcript" not in props, (
        "'transcript' field in TeachbackSubmission — implies STT, which is banned"
    )


# ── AC7: LearnerDNA shape ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_learner_dna_has_badge_labels_and_profile_text(schemas: dict) -> None:
    props = schemas.get("LearnerDNA", {}).get("properties", {})
    assert "badge_labels" in props, "LearnerDNA missing 'badge_labels'"
    assert "profile_text" in props, "LearnerDNA missing 'profile_text'"


# ── AC8: Structural sanity ────────────────────────────────────────────────────

@pytest.mark.unit
def test_spec_is_valid_json_roundtrip(spec: dict) -> None:
    serialised = json.dumps(spec)
    parsed = json.loads(serialised)
    assert parsed.get("info", {}).get("title") is not None, "spec missing 'info.title'"
    assert "paths" in parsed, "spec missing 'paths'"
    assert "components" in parsed, "spec missing 'components'"
