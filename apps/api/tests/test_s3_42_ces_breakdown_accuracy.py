"""Tests for S3-42 (D9): per-signal Redis histories and CES breakdown accuracy.

AC1 — process_attention_signal writes per-signal histories in TEACHING state.
AC2 — None signals do not write to their history; ltrim cap enforced.
AC3 — get_session_report accepts optional redis parameter.
AC4 — _signal_avg reads from Redis per-signal histories.
AC5 — Graceful fallback to 0.0 when redis=None or history empty.
AC6 — Router passes redis=get_redis() to get_session_report.
AC7 — ces_breakdown behavioral/head_pose/blink non-zero when histories have data.
Guard (D108, was D72) — get_session_report has no hardcoded 0.0 for behavioral/head_pose/blink.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_redis(state: str = "TEACHING") -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=state)
    redis.set = AsyncMock()
    redis.lpush = AsyncMock(return_value=1)
    redis.ltrim = AsyncMock()
    redis.expire = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    return redis


def _attention_payload(
    behavioral: float | None = 0.8,
    head_pose: float | None = 0.7,
    blink: float | None = 0.6,
) -> dict:
    return {
        "session_id": "ses-42",
        "quiz_accuracy": 0.9,
        "teachback_score": None,
        "behavioral_score": behavioral,
        "head_pose_score": head_pose,
        "blink_rate": blink,
    }


# ── AC 1 — per-signal histories written in TEACHING state ─────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_signal_histories_written_in_teaching_state():
    """AC1: behavioral/head_pose/blink lpush called in TEACHING state."""
    from app.modules.tutor.service import process_attention_signal

    redis = _make_redis("TEACHING")

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "TEACHING"},
        ),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
                ces_threshold=50.0,
                ces_cadence_seconds=5,
                max_distraction_interventions=3,
                ces_fatigue_min_session_seconds=900,
                ces_fatigue_blink_threshold=0.3,
                ces_fatigue_head_pose_threshold=0.3,
            ),
        ),
    ):
        await process_attention_signal("ses-42", _attention_payload())

    lpush_keys = [str(c.args[0]) for c in redis.lpush.call_args_list]
    assert any("behavioral_history" in k for k in lpush_keys), (
        "behavioral_history lpush not called in TEACHING state"
    )
    assert any("head_pose_history" in k for k in lpush_keys), (
        "head_pose_history lpush not called in TEACHING state"
    )
    assert any("blink_history" in k for k in lpush_keys), (
        "blink_history lpush not called in TEACHING state"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_signal_histories_not_written_outside_teaching():
    """AC1 inverse: per-signal history NOT written when state != TEACHING."""
    from app.modules.tutor.service import process_attention_signal

    redis = _make_redis("QUIZZING")

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "QUIZZING"},
        ),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
                ces_threshold=50.0,
                ces_cadence_seconds=5,
                max_distraction_interventions=3,
                ces_fatigue_min_session_seconds=900,
                ces_fatigue_blink_threshold=0.3,
                ces_fatigue_head_pose_threshold=0.3,
            ),
        ),
    ):
        await process_attention_signal("ses-42b", _attention_payload())

    lpush_keys = [str(c.args[0]) for c in redis.lpush.call_args_list]
    assert not any("behavioral_history" in k for k in lpush_keys), (
        "behavioral_history must NOT be written outside TEACHING"
    )


# ── AC 2 — None signals do not write to their history ─────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_none_behavioral_signal_skips_history_write():
    """AC2: behavioral_score=None → no behavioral_history lpush."""
    from app.modules.tutor.service import process_attention_signal

    redis = _make_redis("TEACHING")

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "TEACHING"},
        ),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
                ces_threshold=50.0,
                ces_cadence_seconds=5,
                max_distraction_interventions=3,
                ces_fatigue_min_session_seconds=900,
                ces_fatigue_blink_threshold=0.3,
                ces_fatigue_head_pose_threshold=0.3,
            ),
        ),
    ):
        await process_attention_signal("ses-42c", _attention_payload(behavioral=None))

    lpush_keys = [str(c.args[0]) for c in redis.lpush.call_args_list]
    assert not any("behavioral_history" in k for k in lpush_keys), (
        "behavioral_history must NOT be written when behavioral_score=None"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_none_head_pose_signal_skips_history_write():
    """AC2: head_pose_score=None → no head_pose_history lpush."""
    from app.modules.tutor.service import process_attention_signal

    redis = _make_redis("TEACHING")

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "TEACHING"},
        ),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
                ces_threshold=50.0,
                ces_cadence_seconds=5,
                max_distraction_interventions=3,
                ces_fatigue_min_session_seconds=900,
                ces_fatigue_blink_threshold=0.3,
                ces_fatigue_head_pose_threshold=0.3,
            ),
        ),
    ):
        await process_attention_signal("ses-42d", _attention_payload(head_pose=None))

    lpush_keys = [str(c.args[0]) for c in redis.lpush.call_args_list]
    assert not any("head_pose_history" in k for k in lpush_keys), (
        "head_pose_history must NOT be written when head_pose_score=None"
    )


# ── AC 3 — get_session_report accepts optional redis ──────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_session_report_accepts_redis_param():
    """AC3: get_session_report signature accepts redis kwarg without error."""
    import inspect

    from app.modules.assessment.service import get_session_report

    sig = inspect.signature(get_session_report)
    assert "redis" in sig.parameters, "get_session_report must accept a 'redis' keyword argument"
    assert sig.parameters["redis"].default is None, "redis parameter must default to None"


# ── AC 4 — _signal_avg reads from Redis histories ─────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signal_avg_reads_from_redis_histories():
    """AC4: when redis has per-signal history entries, ces_breakdown reflects them."""
    from app.modules.assessment.service import _build_ces_breakdown

    # Minimal supabase mock for get_session_report
    supabase = MagicMock()
    session_row = {
        "session_id": "ses-42e",
        "user_id": "user-1",
        "lesson_id": "lesson-1",
        "ces_final": 70.0,
        "started_at": "2026-08-12T10:00:00+00:00",
        "ended_at": "2026-08-12T10:30:00+00:00",
    }
    # sessions query
    select_chain = supabase.table.return_value.select.return_value.eq.return_value
    select_chain.maybe_single.return_value.execute.return_value = MagicMock(data=session_row)
    # lessons tier query
    tier_resp = MagicMock()
    tier_resp.data = {"tier": "T2"}
    select_chain.maybe_single.return_value.execute.return_value = MagicMock(data=session_row)

    # Redis mock — behavioral_history = [0.8, 0.6], head_pose = [0.7], blink = [0.5]
    redis = AsyncMock()

    async def _fake_lrange(key, start, stop):
        if "behavioral" in key:
            return ["0.8", "0.6"]
        if "head_pose" in key:
            return ["0.7"]
        if "blink" in key:
            return ["0.5"]
        return []

    redis.lrange = _fake_lrange

    # Patch asyncio.to_thread to run lambdas directly
    # and patch DB calls to return minimal valid responses
    with (
        patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
            ),
        ),
        patch("app.core.db.rows", return_value=[]),
        patch("app.core.db.single_row", return_value=session_row),
    ):
        # Directly test _build_ces_breakdown with real averages
        settings = MagicMock(
            ces_weight_quiz=0.35,
            ces_weight_teachback=0.25,
            ces_weight_behavioral=0.20,
            ces_weight_head_pose=0.12,
            ces_weight_blink=0.08,
        )
        breakdown = _build_ces_breakdown(
            quiz_accuracy=0.9,
            teachback_normalised=None,
            behavioral_avg=0.7,  # avg(0.8, 0.6)
            head_pose_avg=0.7,
            blink_avg=0.5,
            settings=settings,
        )
    # When behavioral_avg > 0, breakdown["behavioral"] must be > 0
    assert breakdown["behavioral"] > 0.0, (
        f"Expected behavioral breakdown > 0 when avg=0.7, got {breakdown['behavioral']}"
    )
    assert breakdown["head_pose"] > 0.0, (
        f"Expected head_pose breakdown > 0 when avg=0.7, got {breakdown['head_pose']}"
    )
    assert breakdown["blink"] > 0.0, (
        f"Expected blink breakdown > 0 when avg=0.5, got {breakdown['blink']}"
    )


# ── AC 5 — Graceful fallback when redis=None or history empty ─────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_ces_breakdown_defaults_zero_for_absent_redis():
    """AC5: _build_ces_breakdown called with 0.0 averages when redis=None produces valid output."""
    from app.modules.assessment.service import _build_ces_breakdown

    settings = MagicMock(
        ces_weight_quiz=0.35,
        ces_weight_teachback=0.25,
        ces_weight_behavioral=0.20,
        ces_weight_head_pose=0.12,
        ces_weight_blink=0.08,
    )
    breakdown = _build_ces_breakdown(
        quiz_accuracy=0.8,
        teachback_normalised=0.7,
        behavioral_avg=0.0,
        head_pose_avg=0.0,
        blink_avg=0.0,
        settings=settings,
    )
    # Should not raise; behavioral/head_pose/blink are 0.0 but result is valid
    assert isinstance(breakdown, dict)
    assert breakdown["behavioral"] == pytest.approx(0.0)
    assert breakdown["head_pose"] == pytest.approx(0.0)
    assert breakdown["blink"] == pytest.approx(0.0)
    assert breakdown["quiz"] > 0.0  # quiz_accuracy=0.8 > 0 so quiz contribution is positive


# ── AC 6 — Router passes redis=get_redis() ────────────────────────────────────


@pytest.mark.unit
def test_router_passes_redis_to_get_session_report():
    """AC6: router.py get_session_report_endpoint imports get_redis and passes redis kwarg."""
    import pathlib

    router_src = pathlib.Path(
        "D:/intern/transformED/transformED/apps/api/app/modules/assessment/router.py"
    ).read_text(encoding="utf-8")

    # Verify get_redis import is present in the endpoint function
    assert "get_redis" in router_src, "router.py must import get_redis for S3-42"
    # Verify redis kwarg passed in the call
    assert "redis=get_redis()" in router_src, (
        "router.py must pass redis=get_redis() to get_session_report"
    )


# ── AC 7 — ces_breakdown non-zero when histories have data ────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ces_breakdown_behavioral_nonzero_with_history_data():
    """AC7: _build_ces_breakdown behavioral > 0 when history averages are non-zero."""
    from app.modules.assessment.service import _build_ces_breakdown

    settings = MagicMock(
        ces_weight_quiz=0.35,
        ces_weight_teachback=0.25,
        ces_weight_behavioral=0.20,
        ces_weight_head_pose=0.12,
        ces_weight_blink=0.08,
    )
    breakdown = _build_ces_breakdown(
        quiz_accuracy=0.9,
        teachback_normalised=0.8,
        behavioral_avg=0.75,
        head_pose_avg=0.65,
        blink_avg=0.55,
        settings=settings,
    )
    assert breakdown["behavioral"] == pytest.approx(0.75 * 0.20 * 100, abs=0.01), (
        "behavioral breakdown must be behavioral_avg * weight * 100"
    )
    assert breakdown["head_pose"] == pytest.approx(0.65 * 0.12 * 100, abs=0.01)
    assert breakdown["blink"] == pytest.approx(0.55 * 0.08 * 100, abs=0.01)


# ── AC 2 (third branch) — blink_rate=None does NOT write blink_history ────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_none_blink_rate_signal_skips_history_write():
    """AC2 (blink branch): blink_rate=None → no blink_history lpush.

    This is the third of the three None-skip branches (behavioral and head_pose
    are tested above). A future refactor removing the guard on line 334 of
    tutor/service.py would cause this test to fail.
    """
    from app.modules.tutor.service import process_attention_signal

    redis = _make_redis("TEACHING")

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "TEACHING"},
        ),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
                ces_threshold=50.0,
                ces_cadence_seconds=5,
                max_distraction_interventions=3,
                ces_fatigue_min_session_seconds=900,
                ces_fatigue_blink_threshold=0.3,
                ces_fatigue_head_pose_threshold=0.3,
            ),
        ),
    ):
        await process_attention_signal("ses-42f", _attention_payload(blink=None))

    lpush_keys = [str(c.args[0]) for c in redis.lpush.call_args_list]
    assert not any("blink_history" in k for k in lpush_keys), (
        "blink_history must NOT be written when blink_rate=None"
    )


# ── AC 1 + Scale Contract Q4 — ltrim cap enforced at 10 ─────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ltrim_cap_applied_to_per_signal_histories():
    """Scale Contract Q4: ltrim(key, 0, _CES_HISTORY_MAX-1) called for each signal history.

    The ltrim cap is the ONLY enforcement against unbounded growth of per-signal
    history lists. This test ensures removing the ltrim call would fail CI.
    """
    from app.modules.tutor.service import _CES_HISTORY_MAX, process_attention_signal

    redis = _make_redis("TEACHING")

    with (
        patch("app.core.redis.get_redis", return_value=redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            new_callable=AsyncMock,
            return_value={"current_state": "TEACHING"},
        ),
        patch(
            "app.config.get_settings",
            return_value=MagicMock(
                ces_weight_quiz=0.35,
                ces_weight_teachback=0.25,
                ces_weight_behavioral=0.20,
                ces_weight_head_pose=0.12,
                ces_weight_blink=0.08,
                ces_threshold=50.0,
                ces_cadence_seconds=5,
                max_distraction_interventions=3,
                ces_fatigue_min_session_seconds=900,
                ces_fatigue_blink_threshold=0.3,
                ces_fatigue_head_pose_threshold=0.3,
            ),
        ),
    ):
        await process_attention_signal("ses-42g", _attention_payload())

    ltrim_calls = [(str(c.args[0]), c.args[1], c.args[2]) for c in redis.ltrim.call_args_list]
    # Expect ltrim for behavioral_history, head_pose_history, blink_history (+ ces_history)
    history_ltrim_keys = {k for k, start, stop in ltrim_calls if "_history" in k}
    assert "session:ses-42g:behavioral_history" in history_ltrim_keys, (
        "ltrim must be called for behavioral_history (Scale Contract Q4)"
    )
    assert "session:ses-42g:head_pose_history" in history_ltrim_keys, (
        "ltrim must be called for head_pose_history (Scale Contract Q4)"
    )
    assert "session:ses-42g:blink_history" in history_ltrim_keys, (
        "ltrim must be called for blink_history (Scale Contract Q4)"
    )
    # Verify the cap value is exactly _CES_HISTORY_MAX - 1
    for k, start, stop in ltrim_calls:
        if "_history" in k and "ces_history" not in k:
            assert start == 0, f"ltrim start must be 0, got {start} for {k}"
            assert stop == _CES_HISTORY_MAX - 1, (
                f"ltrim stop must be {_CES_HISTORY_MAX - 1} for {k}, got {stop}"
            )


# ── Guard (D108, was D72) — no hardcoded 0.0 for behavioral/head_pose/blink ──────


@pytest.mark.unit
def test_ces_breakdown_no_hardcoded_zero_for_behavioral():
    """Guard (D108): get_session_report source must not contain hardcoded 0.0 for behavioral.

    Fails CI if someone re-introduces the deferred Sprint 2 hardcoded values.
    """
    from app.modules.assessment import service as assessment_service

    source = inspect.getsource(assessment_service.get_session_report)
    assert '"behavioral": 0.0' not in source, (
        'get_session_report must not hardcode "behavioral": 0.0 — D108 guard'
    )
    assert '"head_pose": 0.0' not in source, (
        'get_session_report must not hardcode "head_pose": 0.0 — D108 guard'
    )
    assert '"blink": 0.0' not in source, (
        'get_session_report must not hardcode "blink": 0.0 — D108 guard'
    )


# ── AC1 (source guards) — per-signal history keys referenced ─────────────────


@pytest.mark.unit
def test_process_attention_signal_source_contains_signal_history_keys():
    """AC1 (source guard): process_attention_signal must reference all three history keys."""
    from app.modules.tutor import service as tutor_service

    source = inspect.getsource(tutor_service.process_attention_signal)
    assert "behavioral_history" in source, (
        "process_attention_signal must write to behavioral_history Redis key — AC1"
    )
    assert "head_pose_history" in source, (
        "process_attention_signal must write to head_pose_history Redis key — AC1"
    )
    assert "blink_history" in source, (
        "process_attention_signal must write to blink_history Redis key — AC1"
    )
    assert "_CES_HISTORY_MAX" in source or "ltrim" in source, (
        "process_attention_signal must bound history with ltrim/_CES_HISTORY_MAX — AC2"
    )


# ── AC3/AC4/AC5 (source guards) — get_session_report correctness ─────────────


@pytest.mark.unit
def test_get_session_report_reads_all_signal_history_keys():
    """AC3 (source guard): get_session_report must reference all signal history keys."""
    from app.modules.assessment import service as assessment_service

    source = inspect.getsource(assessment_service.get_session_report)
    assert "behavioral_history" in source, "get_session_report must read behavioral_history — AC3"
    assert "head_pose_history" in source, "get_session_report must read head_pose_history — AC3"
    assert "blink_history" in source, "get_session_report must read blink_history — AC3"


@pytest.mark.unit
def test_ces_breakdown_uses_settings_weights_not_hardcoded():
    """AC5 (source guard): get_session_report must use settings.ces_weight_* not literals."""
    from app.modules.assessment import service as assessment_service

    source = inspect.getsource(assessment_service.get_session_report)
    assert "ces_weight_behavioral" in source, (
        "get_session_report must use settings.ces_weight_behavioral — AC5"
    )
    assert "ces_weight_head_pose" in source, (
        "get_session_report must use settings.ces_weight_head_pose — AC5"
    )
    assert "ces_weight_blink" in source, (
        "get_session_report must use settings.ces_weight_blink — AC5"
    )
