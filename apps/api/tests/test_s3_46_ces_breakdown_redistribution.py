"""RED tests for S3-46 (D2): _build_ces_breakdown helper with proportional weight
redistribution when teachback_normalised=None.

All 23 tests written RED-first — they fail before _build_ces_breakdown is
extracted and get_session_report is updated to delegate to it.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

# ── Settings mock ─────────────────────────────────────────────────────────────


def _settings(
    *,
    quiz: float = 0.35,
    teachback: float = 0.25,
    behavioral: float = 0.20,
    head_pose: float = 0.12,
    blink: float = 0.08,
) -> MagicMock:
    s = MagicMock()
    s.ces_weight_quiz = quiz
    s.ces_weight_teachback = teachback
    s.ces_weight_behavioral = behavioral
    s.ces_weight_head_pose = head_pose
    s.ces_weight_blink = blink
    return s


# ── Shared inputs for nominal / redistributed pair ────────────────────────────

_QUIZ_N = 0.5
_TB_N = 0.85
_BEHAV_N = 0.7
_HEAD_N = 0.5
_BLINK_N = 0.4


# ── AC 1: function is importable as a module-level name ───────────────────────


@pytest.mark.unit
def test_function_is_importable():
    """AC 1: _build_ces_breakdown importable from assessment.service."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    assert callable(_build_ces_breakdown)


# ── AC 2 & 11: Nominal path — all 5 expected contributions, 4dp rounding ─────


@pytest.mark.unit
def test_nominal_path_quiz_contribution():
    """AC 2: quiz = quiz_accuracy * ces_weight_quiz * 100 when teachback present."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=_TB_N,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["quiz"] == pytest.approx(round(_QUIZ_N * 0.35 * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_nominal_path_teachback_contribution():
    """AC 2: teachback = teachback_normalised * ces_weight_teachback * 100."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=_TB_N,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["teachback"] == pytest.approx(round(_TB_N * 0.25 * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_nominal_path_behavioral_contribution():
    """AC 2: behavioral = behavioral_avg * ces_weight_behavioral * 100."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=_TB_N,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["behavioral"] == pytest.approx(round(_BEHAV_N * 0.20 * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_nominal_path_head_pose_contribution():
    """AC 2: head_pose = head_pose_avg * ces_weight_head_pose * 100."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=_TB_N,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["head_pose"] == pytest.approx(round(_HEAD_N * 0.12 * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_nominal_path_blink_contribution():
    """AC 2: blink = blink_avg * ces_weight_blink * 100."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=_TB_N,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["blink"] == pytest.approx(round(_BLINK_N * 0.08 * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_nominal_path_full_dict():
    """AC 2: nominal dict: quiz=17.5, teachback=21.25, behavioral=14.0, head_pose=6.0, blink=3.2."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=_TB_N,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["quiz"] == pytest.approx(17.5, rel=1e-4)
    assert result["teachback"] == pytest.approx(21.25, rel=1e-4)
    assert result["behavioral"] == pytest.approx(14.0, rel=1e-4)
    assert result["head_pose"] == pytest.approx(6.0, rel=1e-4)
    assert result["blink"] == pytest.approx(3.2, rel=1e-4)


# ── AC 3, 4, 11: Redistributed path when teachback_normalised=None ────────────


@pytest.mark.unit
def test_redistributed_path_quiz_contribution():
    """AC 3: quiz = quiz_accuracy * (ces_weight_quiz / remaining) * 100 when teachback=None."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    remaining = 1.0 - 0.25  # = 0.75
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=None,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["quiz"] == pytest.approx(round(_QUIZ_N * (0.35 / remaining) * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_redistributed_path_teachback_zero():
    """AC 4: teachback = 0.0 in redistributed path (signal absent)."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=None,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["teachback"] == pytest.approx(0.0)


@pytest.mark.unit
def test_redistributed_path_behavioral_contribution():
    """AC 3: behavioral uses redistributed weight when teachback=None."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    remaining = 0.75
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=None,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["behavioral"] == pytest.approx(
        round(_BEHAV_N * (0.20 / remaining) * 100, 4), rel=1e-4
    )


@pytest.mark.unit
def test_redistributed_path_head_pose_contribution():
    """AC 3: head_pose uses redistributed weight when teachback=None."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    remaining = 0.75
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=None,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["head_pose"] == pytest.approx(
        round(_HEAD_N * (0.12 / remaining) * 100, 4), rel=1e-4
    )


@pytest.mark.unit
def test_redistributed_path_blink_contribution():
    """AC 3: blink uses redistributed weight when teachback=None."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    remaining = 0.75
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=None,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["blink"] == pytest.approx(round(_BLINK_N * (0.08 / remaining) * 100, 4), rel=1e-4)


@pytest.mark.unit
def test_redistributed_path_full_dict():
    """AC 3: redistributed path: quiz=23.3333, tb=0.0, behav=18.6667, hp=8.0, blink=4.2667."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=_QUIZ_N,
        teachback_normalised=None,
        behavioral_avg=_BEHAV_N,
        head_pose_avg=_HEAD_N,
        blink_avg=_BLINK_N,
        settings=s,
    )
    assert result["quiz"] == pytest.approx(23.3333, rel=1e-4)
    assert result["teachback"] == pytest.approx(0.0)
    assert result["behavioral"] == pytest.approx(18.6667, rel=1e-4)
    assert result["head_pose"] == pytest.approx(8.0, rel=1e-4)
    assert result["blink"] == pytest.approx(4.2667, rel=1e-4)


# ── AC 5: remaining = 1.0 - ces_weight_teachback ─────────────────────────────


@pytest.mark.unit
def test_redistributed_factor_uses_settings_weight():
    """AC 5: redistribution factor = 1.0 - ces_weight_teachback (env-var tunable)."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    # Non-default teachback weight: 0.40 → remaining = 0.60
    s = _settings(teachback=0.40, quiz=0.30, behavioral=0.15, head_pose=0.10, blink=0.05)
    remaining = 1.0 - 0.40  # = 0.60
    result = _build_ces_breakdown(
        quiz_accuracy=0.6,
        teachback_normalised=None,
        behavioral_avg=0.0,
        head_pose_avg=0.0,
        blink_avg=0.0,
        settings=s,
    )
    assert result["quiz"] == pytest.approx(round(0.6 * (0.30 / remaining) * 100, 4), rel=1e-4)


# ── AC 6: degenerate guard — remaining <= 0 → all zeros ──────────────────────


@pytest.mark.unit
def test_degenerate_guard_remaining_zero():
    """AC 6: if ces_weight_teachback >= 1.0, return all zeros (no divide-by-zero)."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings(teachback=1.0)
    result = _build_ces_breakdown(
        quiz_accuracy=0.9,
        teachback_normalised=None,
        behavioral_avg=0.9,
        head_pose_avg=0.9,
        blink_avg=0.9,
        settings=s,
    )
    zeros = {"quiz": 0.0, "teachback": 0.0, "behavioral": 0.0, "head_pose": 0.0, "blink": 0.0}
    assert result == zeros


# ── AC 7: output keys are exactly the 5 CES signals ──────────────────────────


@pytest.mark.unit
def test_output_keys_exactly_five_nominal():
    """AC 7: output dict has exactly {quiz, teachback, behavioral, head_pose, blink}."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=0.5,
        teachback_normalised=0.85,
        behavioral_avg=0.0,
        head_pose_avg=0.0,
        blink_avg=0.0,
        settings=s,
    )
    assert set(result.keys()) == {"quiz", "teachback", "behavioral", "head_pose", "blink"}


@pytest.mark.unit
def test_output_keys_exactly_five_redistributed():
    """AC 7: output dict keys unchanged in redistributed path."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=0.5,
        teachback_normalised=None,
        behavioral_avg=0.0,
        head_pose_avg=0.0,
        blink_avg=0.0,
        settings=s,
    )
    assert set(result.keys()) == {"quiz", "teachback", "behavioral", "head_pose", "blink"}


# ── AC 8: get_session_report delegates to _build_ces_breakdown ────────────────


@pytest.mark.unit
def test_get_session_report_delegates_to_helper():
    """AC 8: get_session_report source must call _build_ces_breakdown, not inline the formula."""
    from app.modules.assessment import service

    src = inspect.getsource(service.get_session_report)
    assert "_build_ces_breakdown" in src, (
        "get_session_report must delegate CES breakdown to _build_ces_breakdown"
    )


# ── AC 11: rounding to 4 decimal places ──────────────────────────────────────


@pytest.mark.unit
def test_rounding_to_4dp_nominal():
    """AC 11: all values rounded to 4dp in nominal path."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=1 / 3,
        teachback_normalised=1 / 7,
        behavioral_avg=1 / 6,
        head_pose_avg=1 / 9,
        blink_avg=1 / 11,
        settings=s,
    )
    for key, val in result.items():
        assert abs(val - round(val, 4)) < 1e-9, f"{key}={val!r} not rounded to 4dp"


@pytest.mark.unit
def test_rounding_to_4dp_redistributed():
    """AC 11: all values rounded to 4dp in redistributed path."""
    from app.modules.assessment.service import _build_ces_breakdown  # noqa: PLC2701

    s = _settings()
    result = _build_ces_breakdown(
        quiz_accuracy=1 / 3,
        teachback_normalised=None,
        behavioral_avg=1 / 6,
        head_pose_avg=1 / 9,
        blink_avg=1 / 11,
        settings=s,
    )
    for key, val in result.items():
        assert abs(val - round(val, 4)) < 1e-9, f"{key}={val!r} not rounded to 4dp"


# ── AC 12: teachback_normalised=None when teachback_count=0 (integration) ─────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_integration_no_teachback_uses_redistributed_weights(monkeypatch):
    """AC 9/12: session with no teachback → redistributed weights applied."""
    from unittest.mock import MagicMock, patch

    from app.modules.assessment.service import get_session_report

    async def _shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _shim)

    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    mock_settings.ces_weight_behavioral = 0.20
    mock_settings.ces_weight_head_pose = 0.12
    mock_settings.ces_weight_blink = 0.08

    with patch("app.modules.assessment.service.get_settings", return_value=mock_settings):
        supabase = _build_minimal_supabase(
            quiz_rows=[{"is_correct": True}, {"is_correct": False}],  # accuracy = 0.5
            tb_rows=[],  # no teachback
        )
        result = await get_session_report(
            session_id="ses-001",
            user_id="user-001",
            supabase=supabase,
        )

    remaining = 0.75
    expected_quiz = round(0.5 * (0.35 / remaining) * 100, 4)
    assert result.ces_breakdown["quiz"] == pytest.approx(expected_quiz, rel=1e-4)
    assert result.ces_breakdown["teachback"] == pytest.approx(0.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_integration_with_teachback_uses_nominal_weights(monkeypatch):
    """AC 10: session with teachback present → nominal weights."""
    from unittest.mock import MagicMock, patch

    from app.modules.assessment.service import get_session_report

    async def _shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _shim)

    mock_settings = MagicMock()
    mock_settings.ces_weight_quiz = 0.35
    mock_settings.ces_weight_teachback = 0.25
    mock_settings.ces_weight_behavioral = 0.20
    mock_settings.ces_weight_head_pose = 0.12
    mock_settings.ces_weight_blink = 0.08

    with patch("app.modules.assessment.service.get_settings", return_value=mock_settings):
        supabase = _build_minimal_supabase(
            quiz_rows=[{"is_correct": True}, {"is_correct": True}],  # accuracy = 1.0
            tb_rows=[{"score": 80}, {"score": 90}],  # avg = 85.0 → normalised = 0.85
        )
        result = await get_session_report(
            session_id="ses-001",
            user_id="user-001",
            supabase=supabase,
        )

    expected_quiz = round(1.0 * 0.35 * 100, 4)
    expected_tb = round(0.85 * 0.25 * 100, 4)
    assert result.ces_breakdown["quiz"] == pytest.approx(expected_quiz, rel=1e-4)
    assert result.ces_breakdown["teachback"] == pytest.approx(expected_tb, rel=1e-4)


# ── Helpers for integration tests ─────────────────────────────────────────────


def _build_minimal_supabase(*, quiz_rows: list, tb_rows: list) -> MagicMock:
    """Minimal Supabase mock wired to the 7-table sequence in get_session_report."""
    from unittest.mock import MagicMock

    session_row = {
        "session_id": "ses-001",
        "user_id": "user-001",
        "lesson_id": "lesson-001",
        "ces_final": 60.0,
        "started_at": "2026-08-12T10:00:00+00:00",
        "ended_at": "2026-08-12T10:30:00+00:00",
    }
    tier_row = {"tier": "T2"}

    mock = MagicMock()
    call_count = [0]

    def _table(_name):
        call_count[0] += 1
        n = call_count[0]
        m = MagicMock()
        _ms = m.select.return_value.eq.return_value.maybe_single.return_value.execute
        _s = m.select.return_value.eq.return_value.execute
        _s2 = m.select.return_value.eq.return_value.eq.return_value.execute
        if n == 1:
            _ms.return_value.data = session_row
        elif n == 2:
            _ms.return_value.data = tier_row
        elif n == 3:
            # quiz_attempts: .select(...).eq(...).limit(500).execute()
            _s.return_value.data = quiz_rows
            _lim = m.select.return_value.eq.return_value.limit.return_value.execute
            _lim.return_value.data = quiz_rows
        elif n == 4:
            # teachback_attempts: .select(...).eq(...).order(...).limit(50).execute() — Story 2-48
            m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = tb_rows
        elif n == 5:
            _s2.return_value.count = 0
        elif n == 6:
            _ms.return_value.data = None
        elif n == 7:
            # session_events/dna_update: .select(...).eq(...).eq(...).limit(20).execute()
            _s2.return_value.data = []
            _lim2 = m.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute
            _lim2.return_value.data = []
        return m

    mock.table.side_effect = _table
    return mock
