"""CI tests for scripts/dna_profile_quality_check.py (Story 4-36).

Tests cover:
- check_profile(): all 5 quality criteria, edge cases, None-safety
- print_report(): return value semantics (True=any FAIL, False=all PASS)
- AC 5 bug fix: 'clinical' inside the DPDP disclaimer suffix must NOT trigger
  the 'No banned terms' criterion (the scan excludes the disclaimer body).

All tests are @pytest.mark.unit — zero Supabase, Redis, or LLM calls.
"""

from __future__ import annotations

import os
import sys

import pytest

# Resolve scripts/ directory (3 levels up from apps/api/tests/)
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts")),
)

from dna_profile_quality_check import check_profile, print_report  # noqa: E402

from app.modules.assessment.prompts import DPDP_DISCLAIMER  # noqa: E402

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BODY = (
    "You are a curious learner who builds understanding step by step. "
    "Your strength lies in connecting ideas across topics, which helps you "
    "retain information more effectively."
)
_VALID_PROFILE: dict = {
    "user_id": "test-user-001",
    "profile_text": _BODY + " " + DPDP_DISCLAIMER,
    "badge_labels": ["Pattern Thinker", "Deep Diver"],
    "session_count": 1,
}

# ---------------------------------------------------------------------------
# Helper: extract result for a named criterion
# ---------------------------------------------------------------------------


def _get(results: list[dict], criterion: str) -> dict:
    for r in results:
        if r["criterion"] == criterion:
            return r
    raise KeyError(f"Criterion {criterion!r} not found in results: {results}")


# ---------------------------------------------------------------------------
# AC 2 — fully valid profile passes all 5 criteria
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_profile_all_pass() -> None:
    """AC 2: all 5 criteria return PASS for a compliant profile."""
    results = check_profile(_VALID_PROFILE)
    for r in results:
        assert r["status"] == "PASS", (
            f"Criterion {r['criterion']!r} expected PASS, got {r['status']!r}: {r['detail']}"
        )


# ---------------------------------------------------------------------------
# AC 3 — DPDP disclaimer absent → criterion 1 FAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_dpdp_disclaimer_fails_criterion_1() -> None:
    """AC 3: profile_text without DPDP disclaimer → 'DPDP disclaimer' FAIL."""
    row = {**_VALID_PROFILE, "profile_text": _BODY}
    results = check_profile(row)
    r = _get(results, "DPDP disclaimer")
    assert r["status"] == "FAIL"
    assert "Missing DPDP disclaimer" in r["detail"]


# ---------------------------------------------------------------------------
# AC 4 — banned term "iq" in body → criterion 2 FAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_banned_term_iq_in_body_fails_criterion_2() -> None:
    """AC 4: 'iq' in main profile body → 'No banned terms' FAIL."""
    body_with_iq = "Your iq score is high. " + DPDP_DISCLAIMER
    row = {**_VALID_PROFILE, "profile_text": body_with_iq}
    results = check_profile(row)
    r = _get(results, "No banned terms")
    assert r["status"] == "FAIL"
    assert "iq" in r["detail"]


# ---------------------------------------------------------------------------
# AC 5 — 'clinical' inside DPDP disclaimer must NOT fail criterion 2 (bug fix)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clinical_in_disclaimer_does_not_fail_criterion_2() -> None:
    """AC 5 (bug fix): 'clinical' appears only inside DPDP disclaimer suffix.
    The banned-term scan must exclude the disclaimer, so criterion 2 returns PASS.
    """
    assert "clinical" in DPDP_DISCLAIMER.lower(), (
        "Test premise: DPDP_DISCLAIMER must contain 'clinical' for this test to be meaningful"
    )
    row = {**_VALID_PROFILE, "profile_text": _BODY + " " + DPDP_DISCLAIMER}
    results = check_profile(row)
    r = _get(results, "No banned terms")
    assert r["status"] == "PASS", (
        f"'clinical' inside the DPDP disclaimer should NOT trigger banned-term FAIL. "
        f"Got: {r['status']!r}, detail: {r['detail']!r}"
    )


# ---------------------------------------------------------------------------
# AC 6 — 'clinical' in body text (outside disclaimer) → criterion 2 FAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clinical_in_body_outside_disclaimer_fails_criterion_2() -> None:
    """AC 6: 'clinical' in the main body (not in disclaimer) → 'No banned terms' FAIL."""
    body_with_clinical = "This is a clinical diagnosis tool. " + DPDP_DISCLAIMER
    row = {**_VALID_PROFILE, "profile_text": body_with_clinical}
    results = check_profile(row)
    r = _get(results, "No banned terms")
    assert r["status"] == "FAIL"
    assert "clinical" in r["detail"]


# ---------------------------------------------------------------------------
# AC 7 — banned term in badge_label → criterion 2 FAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_banned_term_in_badge_label_fails_criterion_2() -> None:
    """AC 7: 'iq' in a badge_label entry → 'No banned terms' FAIL."""
    row = {**_VALID_PROFILE, "badge_labels": ["iq", "Pattern Thinker"]}
    results = check_profile(row)
    r = _get(results, "No banned terms")
    assert r["status"] == "FAIL"


@pytest.mark.unit
def test_badge_label_eq_fails_criterion_2() -> None:
    """AC 7 (extra): 'eq' in a badge_label → 'No banned terms' FAIL."""
    row = {**_VALID_PROFILE, "badge_labels": ["eq score", "Deep Diver"]}
    results = check_profile(row)
    r = _get(results, "No banned terms")
    assert r["status"] == "FAIL"


# ---------------------------------------------------------------------------
# AC 8 — raw score pattern in body → criterion 3 WARN
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_raw_score_pattern_warns_criterion_3() -> None:
    """AC 8: '87/100' in profile body → 'No raw scores' WARN."""
    row = {**_VALID_PROFILE, "profile_text": "Your score is 87/100. " + DPDP_DISCLAIMER}
    results = check_profile(row)
    r = _get(results, "No raw scores")
    assert r["status"] == "WARN"


# ---------------------------------------------------------------------------
# AC 9 — year "2026" is NOT flagged as raw score
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_year_2026_does_not_trigger_raw_score_warn() -> None:
    """AC 9: '2026' in profile text must NOT be flagged as a raw score."""
    row = {
        **_VALID_PROFILE,
        "profile_text": "Updated in 2026. " + _BODY + " " + DPDP_DISCLAIMER,
    }
    results = check_profile(row)
    r = _get(results, "No raw scores")
    assert r["status"] == "PASS", (
        f"Year '2026' should not be flagged as a raw score. Got: {r['status']!r}"
    )


# ---------------------------------------------------------------------------
# AC 10 — profile_text < 50 chars → criterion 4 WARN
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_short_profile_warns_criterion_4() -> None:
    """AC 10: profile_text shorter than 50 chars → 'Length (50–800 chars)' WARN."""
    row = {**_VALID_PROFILE, "profile_text": "Short. " + DPDP_DISCLAIMER[:5]}
    results = check_profile(row)
    r = _get(results, "Length (50–800 chars)")
    assert r["status"] == "WARN"
    assert "Too short" in r["detail"]


@pytest.mark.unit
def test_empty_string_profile_warns_criterion_4() -> None:
    """AC 10 (edge): empty string → 'Length (50–800 chars)' WARN (0 chars < 50)."""
    row = {**_VALID_PROFILE, "profile_text": ""}
    results = check_profile(row)
    r = _get(results, "Length (50–800 chars)")
    assert r["status"] == "WARN"


# ---------------------------------------------------------------------------
# AC 11 — profile_text > 800 chars → criterion 4 WARN
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_long_profile_warns_criterion_4() -> None:
    """AC 11: profile_text > 800 chars → 'Length (50–800 chars)' WARN."""
    row = {**_VALID_PROFILE, "profile_text": "x" * 801}
    results = check_profile(row)
    r = _get(results, "Length (50–800 chars)")
    assert r["status"] == "WARN"
    assert "Too long" in r["detail"]


# ---------------------------------------------------------------------------
# AC 12 — badge label "IQ: 87" → criterion 5 FAIL
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_badge_label_with_score_fails_criterion_5() -> None:
    """AC 12: badge_label 'IQ: 87' matches [A-Z]+:\\s*\\d → FAIL."""
    row = {**_VALID_PROFILE, "badge_labels": ["IQ: 87", "Pattern Thinker"]}
    results = check_profile(row)
    r = _get(results, "Badge labels plain English")
    assert r["status"] == "FAIL"
    assert "IQ: 87" in r["detail"]


@pytest.mark.unit
def test_plain_english_badge_labels_pass_criterion_5() -> None:
    """AC 12 (inverse): plain-English badge labels → criterion 5 PASS."""
    row = {**_VALID_PROFILE, "badge_labels": ["Pattern Thinker", "Deep Diver", "Explorer"]}
    results = check_profile(row)
    r = _get(results, "Badge labels plain English")
    assert r["status"] == "PASS"


# ---------------------------------------------------------------------------
# AC 13 — None profile_text → no AttributeError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_none_profile_text_no_exception() -> None:
    """AC 13: profile_text=None must not raise AttributeError."""
    row = {**_VALID_PROFILE, "profile_text": None}
    results = check_profile(row)
    assert len(results) == 5, "check_profile must always return 5 criterion results"


@pytest.mark.unit
def test_none_profile_text_dpdp_fails() -> None:
    """AC 13: profile_text=None → 'DPDP disclaimer' FAIL (no disclaimer in None)."""
    row = {**_VALID_PROFILE, "profile_text": None}
    results = check_profile(row)
    r = _get(results, "DPDP disclaimer")
    assert r["status"] == "FAIL"


@pytest.mark.unit
def test_none_profile_text_length_warns() -> None:
    """AC 13: profile_text=None → 'Length (50–800 chars)' WARN (treated as 0 chars)."""
    row = {**_VALID_PROFILE, "profile_text": None}
    results = check_profile(row)
    r = _get(results, "Length (50–800 chars)")
    assert r["status"] == "WARN"


# ---------------------------------------------------------------------------
# AC 14 — print_report with FAIL returns True
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_print_report_returns_true_on_any_fail(capsys) -> None:
    """AC 14: print_report() returns True when any criterion is FAIL."""
    fail_row = {**_VALID_PROFILE, "profile_text": "No disclaimer here."}
    results = [check_profile(fail_row)]
    any_fail = print_report([fail_row], results)
    assert any_fail is True


# ---------------------------------------------------------------------------
# AC 15 — print_report with all PASS returns False
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_print_report_returns_false_when_all_pass(capsys) -> None:
    """AC 15: print_report() returns False when all criteria pass."""
    results = [check_profile(_VALID_PROFILE)]
    any_fail = print_report([_VALID_PROFILE], results)
    assert any_fail is False


# ---------------------------------------------------------------------------
# Extra: check_profile always returns exactly 5 criteria
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_profile_always_returns_5_criteria() -> None:
    """Invariant: check_profile() always returns exactly 5 criterion dicts."""
    for row in [
        _VALID_PROFILE,
        {"user_id": "x", "profile_text": None, "badge_labels": None},
        {"user_id": "y", "profile_text": "", "badge_labels": []},
    ]:
        results = check_profile(row)
        assert len(results) == 5, f"Expected 5 criteria, got {len(results)} for row={row!r}"
