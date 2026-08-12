"""RED tests for S3-38 (D13): behavioral_score, head_pose_score, blink_rate are Optional.

Written RED-first — they fail before _parse_signal is changed to use _optional_float
for those three fields.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_behavioral_score_is_optional_in_normalized_signal():
    """AC1: NormalizedSignal.behavioral_score annotated as float | None."""
    import typing

    from app.modules.tutor.service import NormalizedSignal  # noqa: PLC0415

    hints = typing.get_type_hints(NormalizedSignal)
    bs_type = hints["behavioral_score"]
    origin = typing.get_origin(bs_type)
    assert origin is typing.Union or bs_type is type(None) or "None" in str(bs_type), (
        f"behavioral_score should be float | None, got {bs_type!r}"
    )


@pytest.mark.unit
def test_head_pose_score_is_optional_in_normalized_signal():
    """AC1: NormalizedSignal.head_pose_score annotated as float | None."""
    import typing

    from app.modules.tutor.service import NormalizedSignal  # noqa: PLC0415

    hints = typing.get_type_hints(NormalizedSignal)
    hp_type = hints["head_pose_score"]
    assert "None" in str(hp_type), f"head_pose_score should be float | None, got {hp_type!r}"


@pytest.mark.unit
def test_blink_rate_is_optional_in_normalized_signal():
    """AC1: NormalizedSignal.blink_rate annotated as float | None."""
    import typing

    from app.modules.tutor.service import NormalizedSignal  # noqa: PLC0415

    hints = typing.get_type_hints(NormalizedSignal)
    br_type = hints["blink_rate"]
    assert "None" in str(br_type), f"blink_rate should be float | None, got {br_type!r}"


@pytest.mark.unit
def test_parse_signal_null_mediapipe_fields_does_not_raise():
    """AC3: null behavioral/head_pose/blink produces NormalizedSignal without ValueError."""
    from app.modules.tutor.service import _parse_signal  # noqa: PLC0415

    signal = _parse_signal(
        {
            "session_id": "ses-38",
            "quiz_accuracy": 0.7,
            "teachback_score": None,
            "behavioral_score": None,
            "head_pose_score": None,
            "blink_rate": None,
        }
    )
    assert signal.behavioral_score is None
    assert signal.head_pose_score is None
    assert signal.blink_rate is None


@pytest.mark.unit
def test_parse_signal_missing_mediapipe_fields_does_not_raise():
    """AC3: absent behavioral/head_pose/blink produces NormalizedSignal without ValueError."""
    from app.modules.tutor.service import _parse_signal  # noqa: PLC0415

    # No behavioral/head_pose/blink keys in payload at all
    signal = _parse_signal({"session_id": "ses-38b", "quiz_accuracy": 0.5})
    assert signal.behavioral_score is None
    assert signal.head_pose_score is None
    assert signal.blink_rate is None


@pytest.mark.unit
def test_compute_ces_redistributes_when_only_quiz_present():
    """AC4: compute_ces with only quiz=0.5 => 50.0 (full redistribution to single signal)."""
    from app.modules.tutor.service import NormalizedSignal, compute_ces  # noqa: PLC0415

    signal = NormalizedSignal(
        session_id="ses-38c",
        quiz_accuracy=0.5,
        teachback_score=None,
        behavioral_score=None,
        head_pose_score=None,
        blink_rate=None,
    )
    ces = compute_ces(signal)
    assert ces == pytest.approx(50.0, abs=0.01), (
        f"Expected 50.0 when only quiz=0.5 present (full weight redistribution), got {ces}"
    )
