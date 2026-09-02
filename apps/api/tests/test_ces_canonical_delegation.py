"""Story 3-34: Delegation test — tutor.service.compute_ces delegates to assessment.ces.

Verifies AC 8 (Story 3-34): the production path (tutor/service.py::compute_ces)
and the canonical reference (assessment/ces.py::compute_ces) produce identical
results for the same inputs, confirming unification.

All tests are @pytest.mark.unit — no DB, no network, no LLM.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def _settings(
    quiz: float = 0.35,
    tb: float = 0.25,
    beh: float = 0.20,
    hp: float = 0.12,
    blink: float = 0.08,
) -> Settings:
    return Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
        langfuse_public_key="x",
        langfuse_secret_key="x",
        ces_weight_quiz=quiz,
        ces_weight_teachback=tb,
        ces_weight_behavioral=beh,
        ces_weight_head_pose=hp,
        ces_weight_blink=blink,
    )


# ── Test cases covering the main branches ────────────────────────────────────

_DELEGATION_CASES = [
    # (quiz, tb, beh, hp, blink, label)
    (0.8, 0.6, 0.7, 0.9, 0.3, "all_present"),
    (None, 0.6, 0.7, 0.9, 0.3, "quiz_none"),
    (0.8, None, 0.7, 0.9, 0.3, "teachback_none"),
    (None, None, 0.7, 0.9, 0.3, "both_academic_none"),
    (0.8, 0.6, None, 0.9, 0.3, "behavioral_none"),
    (0.8, 0.6, 0.7, None, 0.3, "head_pose_none"),
    (0.8, 0.6, 0.7, 0.9, None, "blink_none"),
    (None, None, None, None, None, "all_none"),
    (0.0, 0.0, 0.0, 0.0, 0.0, "all_zero"),
    (1.0, 1.0, 1.0, 1.0, 1.0, "all_one"),
]


@pytest.mark.unit
@pytest.mark.parametrize("quiz,tb,beh,hp,blink,label", _DELEGATION_CASES)
def test_tutor_service_delegates_to_assessment_ces(quiz, tb, beh, hp, blink, label):
    """Story 3-34 AC 8: tutor.service.compute_ces and assessment.ces.compute_ces
    produce identical results for the same inputs.

    This test confirms that the two formerly-divergent implementations have been
    unified into a single canonical source (assessment/ces.py) that the tutor
    service delegates to.
    """
    from unittest.mock import patch

    from app.modules.assessment.ces import compute_ces as canonical_compute_ces
    from app.modules.tutor import service as tutor_service

    s = _settings()

    # Call canonical directly
    canonical_result = canonical_compute_ces(
        quiz_accuracy=quiz,
        teachback_score=tb,
        behavioral=beh,
        head_pose=hp,
        blink=blink,
        settings=s,
    )

    # Build NormalizedSignal for the tutor service wrapper
    from app.modules.tutor.service import NormalizedSignal

    signal = NormalizedSignal(
        session_id="test-session",
        quiz_accuracy=quiz,
        teachback_score=tb,
        behavioral_score=beh if beh is not None else beh,
        head_pose_score=hp if hp is not None else hp,
        blink_rate=blink if blink is not None else blink,
    )

    # get_settings is imported inside compute_ces body; patch at the config module
    with patch("app.config.get_settings", return_value=s):
        service_result = tutor_service.compute_ces(signal)

    assert service_result == pytest.approx(canonical_result, abs=1e-4), (
        f"[{label}] tutor.service.compute_ces={service_result} "
        f"!= assessment.ces.compute_ces={canonical_result}"
    )
