"""
T18 Demo — Learner DNA profile generation with real onboarding data (Story 235 rewrite).

Validates the full onboarding pipeline with real question_ids (q1-q30, 3 formats):
  _validate_onboarding_responses -> _compute_penta_scores (Q16-Q20 answer-key lookup)
  -> _compute_penta_badge_labels -> generate_onboarding_profile -> learner_dna upsert
  -> OnboardingResult.

All tests are @pytest.mark.unit — no real DB or LLM connections.
asyncio_mode = "auto" (pyproject.toml) — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.assessment.onboarding_questions import (
    ALL_NINE_DIMENSIONS,
    MCQ_OPTION_COUNTS,
    PENTA_BADGE_THRESHOLD,
    PENTA_DIMENSIONS,
    Q_SPEC,
)
from app.modules.assessment.schemas import OnboardingAnswer

# ── Constants ─────────────────────────────────────────────────────────────────

_USER_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# Q16-Q20 index choices producing the highest Penta score for every dimension —
# mirrors PENTA_SCORING in onboarding_questions.py.
_PENTA_TOP_INDEX = {"q16": 1, "q17": 1, "q18": 2, "q19": 2, "q20": 3}
_PENTA_LOW_INDEX = {"q16": 0, "q17": 0, "q18": 0, "q19": 0, "q20": 0}


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _build_real_onboarding_responses(
    penta_indices: dict[str, int] | None = None,
) -> list[OnboardingAnswer]:
    """30 OnboardingAnswer objects with real question_ids (q1-q30, 3 formats)."""
    penta_indices = penta_indices or {}
    answers: list[OnboardingAnswer] = []
    for qid, fmt in Q_SPEC.items():
        if fmt == "mcq":
            index = penta_indices.get(qid, min(1, MCQ_OPTION_COUNTS[qid] - 1))
            answers.append(
                OnboardingAnswer(
                    question_id=qid,
                    format="mcq",
                    selected_index=index,
                    response_text="Option C",
                    response_time_ms=1500,
                )
            )
        elif fmt == "one_liner":
            answers.append(
                OnboardingAnswer(
                    question_id=qid,
                    format="one_liner",
                    response_text=f"Honest answer for {qid}.",
                    response_time_ms=1500,
                )
            )
        else:
            answers.append(
                OnboardingAnswer(
                    question_id=qid, format="true_false", response_bool=True, response_time_ms=1500
                )
            )
    return answers


def _build_supabase_process_onboarding(
    capture_upsert: dict[str, Any] | None = None,
) -> MagicMock:
    """Supabase mock for process_onboarding — 3-call order:
    1. learner_dna (select — _fetch_existing_dna)
    2. onboarding_answers_v2 (insert)
    3. learner_dna (upsert)
    """
    mock = MagicMock()

    dna_select_table = MagicMock()
    dna_select_resp = MagicMock()
    dna_select_resp.data = None
    dna_select_chain = dna_select_table.select.return_value.eq.return_value.maybe_single.return_value
    dna_select_chain.execute.return_value = dna_select_resp

    insert_table = MagicMock()
    insert_resp = MagicMock()
    insert_resp.error = None
    insert_resp.data = []
    insert_table.insert.return_value.execute.return_value = insert_resp

    upsert_table = MagicMock()
    if capture_upsert is not None:

        def _spy_upsert(data: dict[str, Any], **kwargs: Any) -> MagicMock:
            capture_upsert.update(data)
            m = MagicMock()
            m.execute.return_value.error = None
            m.execute.return_value.data = [{"user_id": _USER_UUID}]
            return m

        upsert_table.upsert.side_effect = _spy_upsert
    else:
        upsert_resp = MagicMock()
        upsert_resp.error = None
        upsert_resp.data = [{"user_id": _USER_UUID}]
        upsert_table.upsert.return_value.execute.return_value = upsert_resp

    mock.table.side_effect = [dna_select_table, insert_table, upsert_table]
    return mock


# ── Autouse fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_analytics_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.assessment.service.get_analytics_consent",
        AsyncMock(return_value=False),
    )


@pytest.fixture(autouse=True)
def _mock_capture_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.assessment.service.capture_event", MagicMock())


@pytest.fixture
def mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — _compute_penta_scores maps real Q16-Q20 answers via the PDF answer key
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_penta_scores_maps_real_question_ids() -> None:
    """AC1: top-scoring indices for Q16-Q20 -> all 5 penta_* keys score 100.0."""
    from app.modules.assessment.service import _compute_penta_scores

    responses = _build_real_onboarding_responses(penta_indices=_PENTA_TOP_INDEX)
    scores = _compute_penta_scores(responses)

    assert len(scores) == 5, f"Expected 5 penta dimensions, got {len(scores)}: {list(scores)}"
    for dim in PENTA_DIMENSIONS:
        assert dim in scores, f"Missing penta dimension key: {dim!r}"
        assert scores[dim] == pytest.approx(100.0), f"{dim} should be 100.0, got {scores[dim]}"
    assert all(0.0 <= v <= 100.0 for v in scores.values())


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — _compute_penta_badge_labels returns plain-English labels, no IQ/EQ/SQ
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_penta_badge_labels_plain_english_no_iqeqsq() -> None:
    """AC2: all 5 penta scores at 100.0 -> all 5 badges awarded; no label contains
    'IQ', 'EQ', or 'SQ'."""
    from app.modules.assessment.service import _compute_penta_badge_labels, _compute_penta_scores

    responses = _build_real_onboarding_responses(penta_indices=_PENTA_TOP_INDEX)
    scores = _compute_penta_scores(responses)
    labels = _compute_penta_badge_labels(scores)

    assert len(labels) == 5, (
        f"Expected 5 badges when all penta scores are 100.0 "
        f"(threshold={PENTA_BADGE_THRESHOLD}), got: {labels}"
    )
    assert "Sharp Reasoner" in labels, f"'Sharp Reasoner' missing from badge_labels: {labels}"
    for label in labels:
        assert "IQ" not in label
        assert "EQ" not in label
        assert "SQ" not in label


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — process_onboarding upsert row contains all 5 penta_* scores + profile_text,
# and NOT the 9 behavioral dimensions
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_process_onboarding_upsert_row_contains_penta_not_behavioral(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3/AC4: spy on learner_dna upsert; all 5 penta_* keys + profile_text must be
    present, and the 9 behavioral dimension keys must be ABSENT (they're seeded by
    dna_fusion.py's session-driven path, not onboarding)."""
    from app.modules.assessment.service import process_onboarding

    captured_upsert: dict[str, Any] = {}
    supabase = _build_supabase_process_onboarding(capture_upsert=captured_upsert)

    monkeypatch.setattr("app.modules.assessment.service.OpenAILLMProvider", MagicMock())
    monkeypatch.setattr(
        "app.modules.assessment.service.generate_onboarding_profile",
        AsyncMock(return_value="You are a Sharp Reasoner."),
    )

    responses = _build_real_onboarding_responses(penta_indices=_PENTA_TOP_INDEX)
    result = await process_onboarding(responses=responses, user_id=_USER_UUID, supabase=supabase)

    assert result is not None
    for dim in PENTA_DIMENSIONS:
        assert dim in captured_upsert, f"'{dim}' missing from learner_dna upsert row."
    for dim in ALL_NINE_DIMENSIONS:
        assert dim not in captured_upsert, (
            f"Behavioral dimension '{dim}' must NOT be in the onboarding upsert row."
        )
    assert "profile_text" in captured_upsert
    assert captured_upsert["profile_text"] == "You are a Sharp Reasoner."
    assert captured_upsert.get("user_id") == _USER_UUID


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — DPDP_DISCLAIMER uses HIE, not TransformED (D72 regression guard, unchanged)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_dpdp_disclaimer_uses_hie_not_transformed() -> None:
    from app.modules.assessment.prompts import DPDP_DISCLAIMER

    assert "TransformED" not in DPDP_DISCLAIMER
    assert "HIE" in DPDP_DISCLAIMER


# ══════════════════════════════════════════════════════════════════════════════
# AC5 — generate_onboarding_profile receives non-empty badge_labels when scores are high
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_generate_onboarding_profile_receives_nonempty_badge_labels(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5: generate_onboarding_profile is called with len(badge_labels) >= 1 when all
    5 penta scores are >= PENTA_BADGE_THRESHOLD."""
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

    responses = _build_real_onboarding_responses(penta_indices=_PENTA_TOP_INDEX)
    await process_onboarding(responses=responses, user_id=_USER_UUID, supabase=supabase)

    assert "badge_labels" in captured
    assert len(captured["badge_labels"]) >= 1
    assert "Sharp Reasoner" in captured["badge_labels"]
    assert call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — OnboardingResult exposes no raw dimension scores to the frontend
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_onboarding_result_has_no_raw_dimension_scores(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: OnboardingResult has exactly {badge_labels, profile_text, session_count}."""
    from app.modules.assessment.prompts import DPDP_DISCLAIMER
    from app.modules.assessment.service import process_onboarding

    supabase = _build_supabase_process_onboarding()
    monkeypatch.setattr("app.modules.assessment.service.OpenAILLMProvider", MagicMock())
    monkeypatch.setattr(
        "app.modules.assessment.service.generate_onboarding_profile",
        AsyncMock(return_value=f"Profile.\n\n{DPDP_DISCLAIMER}"),
    )

    responses = _build_real_onboarding_responses(penta_indices=_PENTA_TOP_INDEX)
    result = await process_onboarding(responses=responses, user_id=_USER_UUID, supabase=supabase)

    assert hasattr(result, "badge_labels")
    assert hasattr(result, "profile_text")
    assert hasattr(result, "session_count")
    for dim in [*ALL_NINE_DIMENSIONS, *PENTA_DIMENSIONS]:
        assert not hasattr(result, dim), f"OnboardingResult exposes raw score '{dim}'"
    expected_fields = {"badge_labels", "profile_text", "session_count"}
    assert set(type(result).model_fields.keys()) == expected_fields


# ══════════════════════════════════════════════════════════════════════════════
# AC7 — a low-scoring Penta answer among otherwise-high ones only misses its own badge
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_penta_scores_one_low_answer_only_affects_its_own_dimension() -> None:
    """AC7: lowering only Q19 (CTQ) -> only penta_ctq drops; the other 4 stay at 100.0."""
    from app.modules.assessment.service import _compute_penta_scores

    indices = {**_PENTA_TOP_INDEX, "q19": 0}  # q19 index 0 scores 0.0
    responses = _build_real_onboarding_responses(penta_indices=indices)
    scores = _compute_penta_scores(responses)

    assert scores["penta_ctq"] == pytest.approx(0.0)
    for dim in PENTA_DIMENSIONS:
        if dim != "penta_ctq":
            assert scores[dim] == pytest.approx(100.0), f"{dim} should be unaffected, got {scores[dim]}"


# ══════════════════════════════════════════════════════════════════════════════
# AC8 — _compute_penta_badge_labels returns [] when all scores are below threshold
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_penta_badge_labels_empty_when_all_scores_below_threshold() -> None:
    """AC8: lowest-scoring options for Q16-Q20 -> no dim meets PENTA_BADGE_THRESHOLD
    (70.0) -> badge_labels == []."""
    from app.modules.assessment.service import _compute_penta_badge_labels, _compute_penta_scores

    responses = _build_real_onboarding_responses(penta_indices=_PENTA_LOW_INDEX)
    scores = _compute_penta_scores(responses)

    for dim, score in scores.items():
        assert score < PENTA_BADGE_THRESHOLD, f"{dim} should be below threshold, got {score}"

    labels = _compute_penta_badge_labels(scores)
    assert labels == [], f"Expected no badges when all scores are low, got: {labels!r}"


# ══════════════════════════════════════════════════════════════════════════════
# AC9 — ONBOARDING_PROFILE_SYSTEM_PROMPT uses HIE, not TransformED (D72, unchanged)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_onboarding_system_prompt_uses_hie_not_transformed() -> None:
    from app.modules.assessment.prompts import ONBOARDING_PROFILE_SYSTEM_PROMPT

    assert "TransformED" not in ONBOARDING_PROFILE_SYSTEM_PROMPT
    assert "HIE" in ONBOARDING_PROFILE_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# P10 — a specific Penta answer-key value validates against the PDF (regression guard)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_penta_scores_specific_value_validates_answer_key() -> None:
    """P10: Q18 (SQ dilemma) index 3 ('Hand it to the police / authority') is the PDF's
    stated 'also high' answer, scored 85.0 — not the top score (100.0, index 2) and not
    a low score. Catches a regression that flattens PENTA_SCORING's SQ dilemma tiers."""
    from app.modules.assessment.service import _compute_penta_scores

    responses = _build_real_onboarding_responses(penta_indices={**_PENTA_TOP_INDEX, "q18": 3})
    scores = _compute_penta_scores(responses)

    assert scores["penta_sq"] == pytest.approx(85.0), (
        f"Q18 index 3 ('also high') should score 85.0 per the PDF answer key; "
        f"got {scores['penta_sq']}"
    )
