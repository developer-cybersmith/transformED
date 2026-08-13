"""
T18 Demo — Learner DNA profile generation with real onboarding data.

Validates the full onboarding pipeline with real question_ids (c1-c8, e1-e5, s1-s7):
  QUESTION_SUBDIMENSION_MAP → 9 sub-dimension scores → badge labels →
  generate_onboarding_profile → learner_dna upsert → OnboardingResult.

9 tests: AC1 through AC9 (docs/stories/demo-t18-learner-dna-real-onboarding-data.md).
All tests are @pytest.mark.unit — no real DB or LLM connections.
asyncio_mode = "auto" (pyproject.toml) — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.assessment.onboarding_questions import (
    ALL_NINE_DIMENSIONS,
    BADGE_THRESHOLD,
)
from app.modules.assessment.schemas import OnboardingAnswer

# ── Constants ─────────────────────────────────────────────────────────────────

_USER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _build_real_onboarding_responses(selected_index: int = 3) -> list[OnboardingAnswer]:
    """20 OnboardingAnswer objects with real question_ids (c1-c8, e1-e5, s1-s7)."""
    questions = [
        ("c1", "cognitive"), ("c2", "cognitive"), ("c3", "cognitive"), ("c4", "cognitive"),
        ("c5", "cognitive"), ("c6", "cognitive"), ("c7", "cognitive"), ("c8", "cognitive"),
        ("e1", "emotional"), ("e2", "emotional"), ("e3", "emotional"),
        ("e4", "emotional"), ("e5", "emotional"),
        ("s1", "self_direction"), ("s2", "self_direction"), ("s3", "self_direction"),
        ("s4", "self_direction"), ("s5", "self_direction"), ("s6", "self_direction"),
        ("s7", "self_direction"),
    ]
    return [
        OnboardingAnswer(
            question_id=qid,
            dimension=dim,
            selected_index=selected_index,
            selected_text="Option C",
            response_time_ms=1500,
        )
        for qid, dim in questions
    ]


def _build_supabase_process_onboarding(
    capture_upsert: dict[str, Any] | None = None,
) -> MagicMock:
    """Supabase mock for process_onboarding — 2-call order:
    1. onboarding_responses (insert)
    2. learner_dna (upsert)
    """
    mock = MagicMock()

    # Call 1 — onboarding_responses insert
    insert_table = MagicMock()
    insert_resp = MagicMock()
    insert_resp.error = None
    insert_table.insert.return_value.execute.return_value = insert_resp

    # Call 2 — learner_dna upsert
    dna_table = MagicMock()
    if capture_upsert is not None:
        def _spy_upsert(data: dict[str, Any], **kwargs: Any) -> MagicMock:
            capture_upsert.update(data)
            m = MagicMock()
            m.execute.return_value.error = None
            return m

        dna_table.upsert.side_effect = _spy_upsert
    else:
        upsert_resp = MagicMock()
        upsert_resp.error = None
        dna_table.upsert.return_value.execute.return_value = upsert_resp

    mock.table.side_effect = lambda name: {
        "onboarding_responses": insert_table,
        "learner_dna": dna_table,
    }[name]
    return mock


# ── Autouse fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_analytics_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppress analytics-consent DB call for all T18 tests.

    process_onboarding() calls get_analytics_consent() after the upsert; patching it
    here keeps supabase.table.side_effect at exactly 2 entries (insert + upsert).
    """
    monkeypatch.setattr(
        "app.modules.assessment.service.get_analytics_consent",
        AsyncMock(return_value=False),
    )


@pytest.fixture(autouse=True)
def _mock_capture_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppress PostHog capture_event for all T18 tests."""
    monkeypatch.setattr(
        "app.modules.assessment.service.capture_event",
        MagicMock(),
    )


@pytest.fixture
def mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shim asyncio.to_thread to run synchronously for MagicMock chain compatibility."""

    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — _compute_dimension_scores maps real question_ids to correct sub-dimensions
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_dimension_scores_maps_real_question_ids() -> None:
    """AC1: c1,c5,c8→pattern_recognition (100.0); c2,c3,c7→logical_deduction (100.0);
    e2 alone→persistence (100.0); all 9 sub-dimensions present."""
    from app.modules.assessment.service import _compute_dimension_scores

    responses = _build_real_onboarding_responses(selected_index=3)
    scores = _compute_dimension_scores(responses)

    assert len(scores) == 9, (
        f"Expected 9 sub-dimensions, got {len(scores)}: {list(scores.keys())}"
    )
    assert scores["pattern_recognition"] == 100.0, (
        f"c1,c5,c8 at index 3 → (3/3)×100=100.0 each → mean=100.0; "
        f"got {scores['pattern_recognition']}"
    )
    assert scores["logical_deduction"] == 100.0, (
        f"c2,c3,c7 at index 3 → mean=100.0; got {scores['logical_deduction']}"
    )
    assert scores["persistence"] == 100.0, (
        f"e2 at index 3 is the only persistence question → mean=100.0; "
        f"got {scores['persistence']}"
    )
    for dim in ALL_NINE_DIMENSIONS:
        assert dim in scores, f"Missing sub-dimension key: {dim!r}"
    # P8: all 9 dimension values must equal 100.0 when selected_index=3
    for dim, score in scores.items():
        assert score == 100.0, (
            f"Expected 100.0 for {dim!r} with all selected_index=3; got {score}"
        )
    # P5: validate [0, 100] range to guard against denominator regression
    assert all(0.0 <= v <= 100.0 for v in scores.values()), (
        f"Score out of valid range [0, 100]: {scores}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — _compute_badge_labels returns plain-English labels, no IQ/EQ/SQ
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_badge_labels_plain_english_no_iqeqsq() -> None:
    """AC2: all 9 dims at 100.0 → badges awarded; 'Pattern Thinker' present;
    no label contains 'IQ', 'EQ', or 'SQ'."""
    from app.modules.assessment.service import _compute_badge_labels, _compute_dimension_scores

    responses = _build_real_onboarding_responses(selected_index=3)
    scores = _compute_dimension_scores(responses)
    labels = _compute_badge_labels(scores)

    assert len(labels) > 0, (
        "Expected badges when all dimension scores are 100.0 "
        f"(threshold={BADGE_THRESHOLD}), got empty list"
    )
    assert "Pattern Thinker" in labels, (
        f"'Pattern Thinker' missing from badge_labels: {labels}. "
        "Check BADGE_THRESHOLDS['pattern_recognition']."
    )
    for label in labels:
        assert "IQ" not in label, f"Badge label contains 'IQ': {label!r}"
        assert "EQ" not in label, f"Badge label contains 'EQ': {label!r}"
        assert "SQ" not in label, f"Badge label contains 'SQ': {label!r}"


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — process_onboarding upsert row contains all 9 dimension scores + profile_text
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_process_onboarding_upsert_row_contains_all_nine_dimensions(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3: spy on learner_dna upsert; all 9 sub-dimension keys + profile_text must be
    present in the upserted row. Mock returns a plain string (no DPDP_DISCLAIMER) to
    prove the service stores exactly what generate_onboarding_profile returns (non-circular)."""
    from app.modules.assessment.service import process_onboarding

    captured_upsert: dict[str, Any] = {}
    supabase = _build_supabase_process_onboarding(capture_upsert=captured_upsert)

    monkeypatch.setattr("app.modules.assessment.service.OpenAILLMProvider", MagicMock())
    monkeypatch.setattr(
        "app.modules.assessment.service.generate_onboarding_profile",
        AsyncMock(return_value="You are a Pattern Thinker."),
    )

    responses = _build_real_onboarding_responses(selected_index=3)
    result = await process_onboarding(
        responses=responses,
        user_id=_USER_UUID,
        supabase=supabase,
    )

    assert result is not None
    for dim in ALL_NINE_DIMENSIONS:
        assert dim in captured_upsert, (
            f"Sub-dimension '{dim}' missing from learner_dna upsert row. "
            f"Keys present: {list(captured_upsert.keys())}"
        )
    assert "profile_text" in captured_upsert, "profile_text missing from learner_dna upsert row"
    assert captured_upsert["profile_text"] == "You are a Pattern Thinker.", (
        "profile_text in upsert row does not match generate_onboarding_profile return value. "
        f"Got: {captured_upsert.get('profile_text')!r}"
    )
    # P7: user_id must be stored in the upsert row
    assert captured_upsert.get("user_id") == _USER_UUID, (
        f"user_id missing or wrong in learner_dna upsert row; got: {captured_upsert.get('user_id')!r}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — DPDP_DISCLAIMER uses HIE, not TransformED (D72 regression guard)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_dpdp_disclaimer_uses_hie_not_transformED() -> None:
    """AC4: D72 guard — DPDP_DISCLAIMER must contain 'HIE', not 'TransformED'."""
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    assert "TransformED" not in DPDP_DISCLAIMER, (
        "D72 regression: DPDP_DISCLAIMER still contains 'TransformED'. Replace with 'HIE'."
    )
    assert "HIE" in DPDP_DISCLAIMER, (
        "DPDP_DISCLAIMER does not contain the brand name 'HIE'."
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC5 — generate_onboarding_profile receives non-empty badge_labels when scores are high
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_generate_onboarding_profile_receives_nonempty_badge_labels(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5: generate_onboarding_profile is called with len(badge_labels) >= 1 when all
    9 dimension scores are >= BADGE_THRESHOLD (70.0). Prevents silent scoring error
    where no badges are awarded despite high scores."""
    from app.modules.assessment.prompts import DPDP_DISCLAIMER
    from app.modules.assessment.service import process_onboarding

    captured: dict[str, Any] = {}
    call_count = 0

    async def _spy_generate(*, badge_labels: list[str], provider: Any) -> str:
        nonlocal call_count
        call_count += 1
        captured["badge_labels"] = list(badge_labels)
        return f"Profile text.\n\n{DPDP_DISCLAIMER}"

    supabase = _build_supabase_process_onboarding()
    monkeypatch.setattr("app.modules.assessment.service.OpenAILLMProvider", MagicMock())
    monkeypatch.setattr("app.modules.assessment.service.generate_onboarding_profile", _spy_generate)

    responses = _build_real_onboarding_responses(selected_index=3)
    await process_onboarding(responses=responses, user_id=_USER_UUID, supabase=supabase)

    assert "badge_labels" in captured, "generate_onboarding_profile was never called"
    assert len(captured["badge_labels"]) >= 1, (
        f"generate_onboarding_profile received empty badge_labels when all scores=100.0. "
        f"Check _compute_badge_labels threshold ({BADGE_THRESHOLD}). "
        f"Got: {captured['badge_labels']!r}"
    )
    # P9: verify actual badge content, not just length
    assert "Pattern Thinker" in captured["badge_labels"], (
        f"'Pattern Thinker' not in badge_labels sent to generate_onboarding_profile: "
        f"{captured['badge_labels']!r}"
    )
    # P11: guard against double-call
    assert call_count == 1, (
        f"generate_onboarding_profile should be called exactly once; called {call_count} times"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — OnboardingResult exposes no raw dimension scores to the frontend
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_onboarding_result_has_no_raw_dimension_scores(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: OnboardingResult has exactly {badge_labels, profile_text, session_count}.
    Raw dimension score attributes (pattern_recognition, etc.) must not be present
    on the returned object — only descriptive output reaches the frontend."""
    from app.modules.assessment.prompts import DPDP_DISCLAIMER
    from app.modules.assessment.service import process_onboarding

    supabase = _build_supabase_process_onboarding()
    monkeypatch.setattr("app.modules.assessment.service.OpenAILLMProvider", MagicMock())
    monkeypatch.setattr(
        "app.modules.assessment.service.generate_onboarding_profile",
        AsyncMock(return_value=f"Profile.\n\n{DPDP_DISCLAIMER}"),
    )

    responses = _build_real_onboarding_responses(selected_index=3)
    result = await process_onboarding(responses=responses, user_id=_USER_UUID, supabase=supabase)

    assert hasattr(result, "badge_labels"), "OnboardingResult missing badge_labels"
    assert hasattr(result, "profile_text"), "OnboardingResult missing profile_text"
    assert hasattr(result, "session_count"), "OnboardingResult missing session_count"
    for dim in ALL_NINE_DIMENSIONS:
        assert not hasattr(result, dim), (
            f"OnboardingResult exposes raw dimension score '{dim}' to the frontend. "
            "Only badge_labels, profile_text, session_count are allowed (CLAUDE.md)."
        )
    # P2: exhaustive field check — no undeclared 4th field (e.g. raw_scores) may leak
    assert set(type(result).model_fields.keys()) == {"badge_labels", "profile_text", "session_count"}, (
        f"OnboardingResult has unexpected fields: {set(type(result).model_fields.keys())}. "
        "Only badge_labels, profile_text, session_count are allowed."
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC7 — _compute_dimension_scores returns 0.0 for dimension with no matching responses
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_dimension_scores_missing_dimension_returns_zero() -> None:
    """AC7: removing e2 (the only persistence question) → persistence=0.0.
    All other dimensions remain unaffected."""
    from app.modules.assessment.service import _compute_dimension_scores

    responses = [r for r in _build_real_onboarding_responses() if r.question_id != "e2"]
    assert len(responses) == 19, "Expected 19 responses after removing e2"

    scores = _compute_dimension_scores(responses)

    assert "persistence" in scores, "persistence key must still be present (from ALL_NINE_DIMENSIONS)"
    assert scores["persistence"] == 0.0, (
        f"persistence should be 0.0 when e2 is absent, got {scores['persistence']}"
    )
    # P3: verify all 8 non-persistence dims are unaffected by removing e2
    for dim, score in scores.items():
        if dim != "persistence":
            assert score == 100.0, (
                f"Removing e2 should not affect {dim!r}; got {score}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# AC8 — _compute_badge_labels returns [] when all dimension scores are below threshold
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_badge_labels_empty_when_all_scores_below_threshold() -> None:
    """AC8: selected_index=0 → all normalized scores=0.0 → no dim meets BADGE_THRESHOLD
    (70.0) → badge_labels==[]."""
    from app.modules.assessment.service import _compute_badge_labels, _compute_dimension_scores

    responses = _build_real_onboarding_responses(selected_index=0)
    scores = _compute_dimension_scores(responses)

    for dim, score in scores.items():
        assert score == 0.0, (
            f"Expected 0.0 for {dim!r} with selected_index=0; "
            f"formula: (0/3)×100=0.0; got {score}"
        )

    labels = _compute_badge_labels(scores)
    assert labels == [], (
        f"Expected no badges when all scores=0.0 (threshold={BADGE_THRESHOLD}), "
        f"got: {labels!r}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC9 — ONBOARDING_PROFILE_SYSTEM_PROMPT uses HIE, not TransformED (D72 regression guard)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_onboarding_system_prompt_uses_hie_not_transformED() -> None:
    """AC9: D72 guard — ONBOARDING_PROFILE_SYSTEM_PROMPT must contain 'HIE',
    not 'TransformED'."""
    from app.modules.assessment.prompts import ONBOARDING_PROFILE_SYSTEM_PROMPT

    assert "TransformED" not in ONBOARDING_PROFILE_SYSTEM_PROMPT, (
        "D72 regression: ONBOARDING_PROFILE_SYSTEM_PROMPT still contains 'TransformED'. "
        "Replace with 'HIE'."
    )
    assert "HIE" in ONBOARDING_PROFILE_SYSTEM_PROMPT, (
        "ONBOARDING_PROFILE_SYSTEM_PROMPT does not contain the brand name 'HIE'."
    )


# ══════════════════════════════════════════════════════════════════════════════
# P10 — Intermediate score validates the /3 denominator
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_dimension_scores_intermediate_score_validates_denominator() -> None:
    """P10: selected_index=2 → (2/3)×100 ≈ 66.67; validates the /3 denominator.
    A wrong denominator (e.g. 4) produces 50.0 at index=2, catching silent regression."""
    from app.modules.assessment.service import _compute_dimension_scores

    responses = _build_real_onboarding_responses(selected_index=2)
    scores = _compute_dimension_scores(responses)

    assert scores["pattern_recognition"] == pytest.approx(66.67, rel=1e-2), (
        f"selected_index=2 → (2/3)×100 ≈ 66.67; got {scores['pattern_recognition']}. "
        "If denominator changed from 3, this test catches the regression."
    )
