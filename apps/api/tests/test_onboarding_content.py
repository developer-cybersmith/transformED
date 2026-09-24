"""
Content validation tests for the onboarding diagnostic questions (Story 235 — 30
question redesign).

These tests read the TypeScript frontend files and validate that the 30-question
onboarding diagnostic complies with:
  - Question count and format-mix requirements (20 MCQ + 5 one-liner + 5 true/false)
  - CLAUDE.md language rules (no IQ/EQ/SQ terms)
  - DPDP Act 2023 compliance (no clinical claims or medical data requests)
  - Format values matching the onboarding_answers_v2 CHECK constraint

These are pure @pytest.mark.unit tests — no imports from app code, no DB, no network.
The TypeScript files are read as plain text; no TypeScript compilation required.
"""

from __future__ import annotations

import pathlib
import re

import pytest

# ---------------------------------------------------------------------------
# Files under test
# ---------------------------------------------------------------------------

# Paths are relative to apps/api/ (where pytest is run from).
_ONBOARDING_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "web" / "src" / "components" / "onboarding"
)
ONBOARDING_FLOW_FILE = _ONBOARDING_DIR / "OnboardingFlow.tsx"
ONBOARDING_QUESTIONS_FILE = _ONBOARDING_DIR / "questions.ts"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content() -> str:
    """Return the combined text of both onboarding content files (cached per test session)."""
    return ONBOARDING_FLOW_FILE.read_text(encoding="utf-8") + ONBOARDING_QUESTIONS_FILE.read_text(
        encoding="utf-8"
    )


def _content_lower() -> str:
    """Return lower-cased content for case-insensitive scans."""
    return _content().lower()


def _questions_content() -> str:
    """questions.ts content ONLY -- for id/format COUNTING assertions.

    Story 235: OnboardingFlow.tsx's own handleSubmit() legitimately contains
    literal `format: "mcq"` / `"one_liner"` / `"true_false"` strings when
    building the wire-format payload, which would double-count against
    `_content()`'s combined text for any COUNT-based (not just presence-based)
    assertion. Count checks must scan questions.ts alone; existence-only
    checks can still safely use `_content()`.
    """
    return ONBOARDING_QUESTIONS_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_onboarding_file_exists() -> None:
    """Both onboarding content files must exist at their expected paths."""
    assert ONBOARDING_FLOW_FILE.exists(), f"OnboardingFlow.tsx not found at {ONBOARDING_FLOW_FILE}."
    assert ONBOARDING_QUESTIONS_FILE.exists(), (
        f"questions.ts not found at {ONBOARDING_QUESTIONS_FILE}. "
        "The 30 question objects live here (Story 235)."
    )


# ---------------------------------------------------------------------------
# Question ID presence — q1-q30
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_all_30_question_ids_present() -> None:
    """All 30 question IDs q1-q30 must appear in the file."""
    content = _questions_content()
    for i in range(1, 31):
        assert f"'q{i}'" in content or f'"q{i}"' in content, f"Missing question id q{i}"


@pytest.mark.unit
def test_total_question_count_is_30() -> None:
    """The QUESTIONS array must contain exactly 30 question objects."""
    content = _questions_content()
    id_pattern = re.compile(r"\bid:\s*['\"]q\d+['\"]")
    matches = id_pattern.findall(content)
    assert len(matches) == 30, f"Expected 30 question id entries, found {len(matches)}."


# ---------------------------------------------------------------------------
# Format split: 20 mcq + 5 one_liner + 5 true_false
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mcq_format_count_is_20() -> None:
    content = _questions_content()
    matches = re.findall(r"format:\s*['\"]mcq['\"]", content)
    assert len(matches) == 20, f"Expected 20 mcq questions, found {len(matches)}"


@pytest.mark.unit
def test_one_liner_format_count_is_5() -> None:
    content = _questions_content()
    matches = re.findall(r"format:\s*['\"]one_liner['\"]", content)
    assert len(matches) == 5, f"Expected 5 one_liner questions, found {len(matches)}"


@pytest.mark.unit
def test_true_false_format_count_is_5() -> None:
    content = _questions_content()
    matches = re.findall(r"format:\s*['\"]true_false['\"]", content)
    assert len(matches) == 5, f"Expected 5 true_false questions, found {len(matches)}"


# ---------------------------------------------------------------------------
# IQ / EQ / SQ language ban (CLAUDE.md non-negotiable rule)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_iq_language() -> None:
    """No IQ/EQ/SQ language may appear in the onboarding content.

    CLAUDE.md rule: "No IQ / EQ / SQ language anywhere in prompts, responses, or comments"
    This test enforces that rule at the frontend content level.
    """
    content_lower = _content_lower()
    banned_terms = [
        "intelligence quotient",
        "emotional quotient",
        "social quotient",
    ]
    for term in banned_terms:
        assert term not in content_lower, (
            f"Banned language found in onboarding content: '{term}'. "
            "This violates CLAUDE.md non-negotiable rules."
        )

    content_original = _content()
    for short_term in [r"\biq\b", r"\beq\b", r"\bsq\b"]:
        matches = re.findall(short_term, content_original, flags=re.IGNORECASE)
        assert not matches, (
            f"Banned IQ/EQ/SQ label '{short_term}' found in onboarding content: {matches}. "
            "This violates CLAUDE.md non-negotiable rules."
        )


# ---------------------------------------------------------------------------
# No clinical claims (DPDP Act 2023 compliance)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_clinical_claims() -> None:
    """No clinical or diagnostic language may appear in onboarding questions.

    DPDP Act 2023 restricts processing of medical/health data. Questions must
    describe learning preferences, not probe for clinical conditions.
    """
    content_lower = _content_lower().replace("not a clinical assessment", "")
    clinical_terms = [
        "adhd",
        "autism",
        "depression",
        "anxiety disorder",
        "bipolar",
        "diagnosis",
        "clinical",
        "psychiatric",
        "disorder",
        "symptom",
    ]
    for term in clinical_terms:
        assert term not in content_lower, (
            f"Clinical term '{term}' found in onboarding content. "
            "Remove it — DPDP Act 2023 prohibits collecting medical/health data."
        )


# ---------------------------------------------------------------------------
# Format values match the onboarding_answers_v2 CHECK constraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_format_values_match_db_schema() -> None:
    """All three format values used in onboarding_answers_v2's CHECK constraint
    must appear in the frontend.

    DB schema (supabase/migrations/20260922010000_onboarding_answers_v2.sql):
      onboarding_answers_v2.format TEXT CHECK IN ('mcq', 'one_liner', 'true_false')
    """
    content = _content()
    for fmt in ("mcq", "one_liner", "true_false"):
        assert f"'{fmt}'" in content or f'"{fmt}"' in content, (
            f"format value '{fmt}' not found in onboarding content"
        )


# ---------------------------------------------------------------------------
# Submission payload shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submission_uses_correct_field_names() -> None:
    """The submit handler must map questions to the new OnboardingAnswer shape.

    Expected fields: question_id, format, and at least one of
    selected_index/response_text/response_bool depending on format.
    These must match the OnboardingAnswer Pydantic model in schemas.py.
    """
    content = _content()
    assert "question_id" in content, "Submission payload missing 'question_id' field"
    assert "selected_index" in content, "Submission payload missing 'selected_index' field"
    assert "response_text" in content, "Submission payload missing 'response_text' field"
    assert "response_bool" in content, "Submission payload missing 'response_bool' field"


# ---------------------------------------------------------------------------
# Learner DNA branding (not IQ-style)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_page_uses_learner_dna_branding() -> None:
    """The page heading must use 'Learner DNA' branding, not IQ-test framing.

    CLAUDE.md: "No raw IQ/EQ/SQ claims — branded as 'Learner DNA'"
    """
    content = _content()
    assert "Learner DNA" in content, (
        "Page must use 'Learner DNA' branding. Found no mention of 'Learner DNA'."
    )
