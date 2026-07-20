"""
Content validation tests for the onboarding diagnostic questions.

These tests read the TypeScript frontend file and validate that the 20-question
onboarding diagnostic complies with:
  - PRD quantity requirements (8 cognitive + 5 emotional + 7 self-direction = 20)
  - CLAUDE.md language rules (no IQ/EQ/SQ terms)
  - DPDP Act 2023 compliance (no clinical claims or medical data requests)
  - Dimension values matching the DB schema CHECK constraint

These are pure @pytest.mark.unit tests — no imports from app code, no DB, no network.
The TypeScript file is read as plain text; no TypeScript compilation required.
"""

from __future__ import annotations

import pathlib
import re

import pytest

# ---------------------------------------------------------------------------
# File under test
# ---------------------------------------------------------------------------

# Path is relative to apps/api/ (where pytest is run from).
# When running from the repo root: adjust accordingly.
ONBOARDING_FILE = (
    pathlib.Path(__file__).parent.parent.parent / "web" / "src" / "app" / "onboarding" / "page.tsx"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content() -> str:
    """Return the full text of the onboarding page (cached per test session)."""
    return ONBOARDING_FILE.read_text(encoding="utf-8")


def _content_lower() -> str:
    """Return lower-cased content for case-insensitive scans."""
    return _content().lower()


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_onboarding_file_exists() -> None:
    """The onboarding page.tsx must exist at the expected path."""
    assert ONBOARDING_FILE.exists(), (
        f"Onboarding page.tsx not found at {ONBOARDING_FILE}. "
        "File was moved from (app)/onboarding/ to onboarding/ in Sprint 0 — check the path."
    )


# ---------------------------------------------------------------------------
# Question ID presence — cognitive (c1–c8)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cognitive_question_ids_present() -> None:
    """All 8 cognitive question IDs c1–c8 must appear in the file."""
    content = _content()
    for i in range(1, 9):
        assert f"'c{i}'" in content or f'"c{i}"' in content, (
            f"Missing cognitive question id c{i} in onboarding page"
        )


# ---------------------------------------------------------------------------
# Question ID presence — emotional (e1–e5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_emotional_question_ids_present() -> None:
    """All 5 emotional question IDs e1–e5 must appear in the file."""
    content = _content()
    for i in range(1, 6):
        assert f"'e{i}'" in content or f'"e{i}"' in content, (
            f"Missing emotional question id e{i} in onboarding page"
        )


# ---------------------------------------------------------------------------
# Question ID presence — self-direction (s1–s7)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_self_direction_question_ids_present() -> None:
    """All 7 self-direction question IDs s1–s7 must appear in the file."""
    content = _content()
    for i in range(1, 8):
        assert f"'s{i}'" in content or f'"s{i}"' in content, (
            f"Missing self-direction question id s{i} in onboarding page"
        )


# ---------------------------------------------------------------------------
# Total question count
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_total_question_count_is_20() -> None:
    """The QUESTIONS array must contain exactly 20 question objects.

    We count occurrences of 'id:' inside the QUESTIONS const block as a proxy.
    Each question object has exactly one 'id:' field.
    """
    content = _content()
    # Count explicit id field assignments in the format: { id: 'cN', ...
    # Match both single and double quoted id values
    id_pattern = re.compile(r"\bid:\s*['\"][ces]\d+['\"]")
    matches = id_pattern.findall(content)
    assert len(matches) == 20, (
        f"Expected 20 question id entries, found {len(matches)}. "
        "Check cognitive (8) + emotional (5) + self-direction (7) counts."
    )


# ---------------------------------------------------------------------------
# Dimension split: 8 cognitive + 5 emotional + 7 self-direction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cognitive_question_count_is_8() -> None:
    """Exactly 8 questions must have dimension: 'cognitive'."""
    content = _content()
    # Match dimension field set to 'cognitive' or "cognitive"
    matches = re.findall(r"dimension:\s*['\"]cognitive['\"]", content)
    assert len(matches) == 8, f"Expected 8 cognitive questions, found {len(matches)}"


@pytest.mark.unit
def test_emotional_question_count_is_5() -> None:
    """Exactly 5 questions must have dimension: 'emotional'."""
    content = _content()
    matches = re.findall(r"dimension:\s*['\"]emotional['\"]", content)
    assert len(matches) == 5, f"Expected 5 emotional questions, found {len(matches)}"


@pytest.mark.unit
def test_self_direction_question_count_is_7() -> None:
    """Exactly 7 questions must have dimension: 'self_direction'."""
    content = _content()
    matches = re.findall(r"dimension:\s*['\"]self_direction['\"]", content)
    assert len(matches) == 7, f"Expected 7 self-direction questions, found {len(matches)}"


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
        # "iq" and "eq" are short and can false-positive on e.g. "unique", "require"
        # so we match them as whole words only
    ]
    for term in banned_terms:
        assert term not in content_lower, (
            f"Banned language found in onboarding content: '{term}'. "
            "This violates CLAUDE.md non-negotiable rules."
        )

    # Whole-word match for "iq", "eq", "sq" to avoid false positives
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
    content_lower = _content_lower()
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
# Dimension values match DB schema CHECK constraint
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dimension_values_match_db_schema() -> None:
    """All three dimension values used in the DB CHECK constraint must appear in the frontend.

    DB schema (supabase/migrations/20260611000000_initial_schema.sql):
      onboarding_responses.dimension_tag TEXT CHECK IN ('cognitive', 'emotional', 'self_direction')

    The frontend Dimension type and question objects must use these exact strings.
    """
    content = _content()
    assert "'cognitive'" in content or '"cognitive"' in content, (
        "dimension value 'cognitive' not found in onboarding page"
    )
    assert "'emotional'" in content or '"emotional"' in content, (
        "dimension value 'emotional' not found in onboarding page"
    )
    assert "'self_direction'" in content or '"self_direction"' in content, (
        "dimension value 'self_direction' not found in onboarding page"
    )


# ---------------------------------------------------------------------------
# Submission payload shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_submission_uses_correct_field_names() -> None:
    """The submit handler must map questions to the OnboardingAnswer shape.

    Expected fields: question_id, dimension, selected_index, selected_text
    These must match the OnboardingAnswer Pydantic model in router.py.
    """
    content = _content()
    assert "question_id" in content, "Submission payload missing 'question_id' field"
    assert "selected_index" in content, "Submission payload missing 'selected_index' field"
    assert "selected_text" in content, "Submission payload missing 'selected_text' field"


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
