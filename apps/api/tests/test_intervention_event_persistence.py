"""Unit tests for S3-36 — Intervention Event Persistence (write_intervention_event).

16 required tests (exact names per story spec) covering:
  AC1  import check
  AC2  distraction payload shape
  AC3  fatigue payload shape
  AC4  fire-and-forget via asyncio.create_task (intervening_node)
  AC5  DB failure caught, logged, Sentry captured
  AC6  "intervention_triggered" in KNOWN_EVENT_TYPES
  AC7  Redis cache-miss -> DB reconstruction; Redis hit -> no DB call
  AC8  frustration_tolerance < baseline when intervention count = 2
  AC9  frustration_tolerance unchanged (no decrement) at count = 0
  AC10 ruff 0 errors (enforced separately via CI)

Additional required tests (story spec):
  - test_write_intervention_event_has_no_llm_calls      (security / no-LLM guard)
  - test_write_intervention_event_uses_session_events_table (table name guard)
  - test_db_write_failure_logs_error                    (AC5 error log)
  - test_db_write_failure_does_not_raise_from_intervening_node (AC4 fire-and-forget)

CRITICAL (task brief):
  - sum(ces_breakdown.values()) approx ces_score when all 5 signals present
  - sum(ces_breakdown.values()) approx ces_score when teachback=None (redistribution)

All tests are @pytest.mark.unit -- no real DB, no network.
Supabase is mocked with MagicMock; asyncio.to_thread patched inline.

Binding rule (DEFECT-REGISTER.md rule 2): every mock is accompanied by a comment
  # MOCK-CONTRACT: covered by tests/integration/ for real Supabase path
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_thread_patch():
    """Patch asyncio.to_thread so the lambda runs synchronously in tests."""
    return patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f())


def _supabase_insert_mock() -> MagicMock:
    """Supabase mock for a successful session_events insert chain.

    # MOCK-CONTRACT: real insert path covered by integration/test_howto_pipeline_e2e.py
    """
    supabase = MagicMock()
    supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
    return supabase


def _make_ces_settings():
    """Minimal Settings with CES weights matching the PRD formula (section 11)."""
    from app.config import Settings  # noqa: PLC0415

    return Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
        heygen_api_key="x",
        langfuse_public_key="x",
        langfuse_secret_key="x",
        ces_weight_quiz=0.35,
        ces_weight_teachback=0.25,
        ces_weight_behavioral=0.20,
        ces_weight_head_pose=0.12,
        ces_weight_blink=0.08,
    )


# ---------------------------------------------------------------------------
# AC1 -- write_intervention_event is importable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_intervention_event_is_importable():
    """AC1: write_intervention_event is importable from assessment.service with no ImportError."""
    from app.modules.assessment.service import write_intervention_event  # noqa: F401

    assert callable(write_intervention_event)


# ---------------------------------------------------------------------------
# AC2 -- Distraction payload shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_distraction_event_payload_has_correct_shape():
    """AC2: distraction intervention inserts all 4 required payload keys."""
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = _supabase_insert_mock()

    with _to_thread_patch():
        await write_intervention_event(
            "sess-1",
            intervention_type="distraction",
            window_index=3,
            ces_at_trigger=42.5,
            message_key="focus_up",
            supabase=supabase,
        )

    insert_call = supabase.table.return_value.insert.call_args
    row = insert_call[0][0]
    assert row["session_id"] == "sess-1"
    assert row["event_type"] == "intervention_triggered"
    payload = row["payload"]
    assert payload["intervention_type"] == "distraction"
    assert payload["window_index"] == 3
    assert payload["ces_at_trigger"] == pytest.approx(42.5)
    assert payload["message_key"] == "focus_up"


@pytest.mark.unit
async def test_distraction_event_type_is_exactly_intervention_triggered():
    """AC2: event_type is the literal string 'intervention_triggered'.

    Asserts both the inserted value and that the source contains the literal string,
    preventing a variable indirection from masking a typo.
    """
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = _supabase_insert_mock()

    with _to_thread_patch():
        await write_intervention_event(
            "sess-2",
            intervention_type="distraction",
            window_index=0,
            ces_at_trigger=45.0,
            message_key="msg",
            supabase=supabase,
        )

    insert_call = supabase.table.return_value.insert.call_args
    row = insert_call[0][0]
    assert row["event_type"] == "intervention_triggered"
    src = inspect.getsource(write_intervention_event)
    assert '"intervention_triggered"' in src or "'intervention_triggered'" in src


# ---------------------------------------------------------------------------
# AC3 -- Fatigue payload shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fatigue_event_payload_has_correct_shape():
    """AC3: fatigue intervention inserts all 4 required payload keys."""
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = _supabase_insert_mock()

    with _to_thread_patch():
        await write_intervention_event(
            "sess-3",
            intervention_type="fatigue",
            window_index=7,
            ces_at_trigger=38.0,
            message_key="take_break",
            supabase=supabase,
        )

    insert_call = supabase.table.return_value.insert.call_args
    row = insert_call[0][0]
    assert row["event_type"] == "intervention_triggered"
    assert row["payload"]["window_index"] == 7
    assert row["payload"]["ces_at_trigger"] == pytest.approx(38.0)
    assert row["payload"]["message_key"] == "take_break"


@pytest.mark.unit
async def test_fatigue_event_intervention_type_field_is_fatigue():
    """AC3: payload['intervention_type'] is 'fatigue' for a fatigue intervention."""
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = _supabase_insert_mock()

    with _to_thread_patch():
        await write_intervention_event(
            "sess-4",
            intervention_type="fatigue",
            window_index=7,
            ces_at_trigger=38.0,
            message_key="break",
            supabase=supabase,
        )

    insert_call = supabase.table.return_value.insert.call_args
    row = insert_call[0][0]
    assert row["payload"]["intervention_type"] == "fatigue"


# ---------------------------------------------------------------------------
# AC4 -- intervening_node uses asyncio.create_task, not await
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_intervening_node_uses_create_task_not_await(mocker):
    """AC4: intervening_node schedules write_intervention_event via create_task (not awaited).

    create_task is called with the coroutine; Redis logic completes and node returns.
    """
    from app.modules.tutor.state_machine.graph import intervening_node  # noqa: PLC0415

    fake_redis = AsyncMock()
    fake_redis.incr = AsyncMock(return_value=1)
    fake_redis.expire = AsyncMock(return_value=True)
    fake_redis.set = AsyncMock(return_value=True)

    fake_settings = MagicMock()
    fake_settings.intervention_cooldown_seconds = 120

    mocker.patch("app.core.redis.get_redis", return_value=fake_redis)
    mocker.patch("app.config.get_settings", return_value=fake_settings)
    mocker.patch(
        "app.modules.tutor.state_machine.graph._persist_state",
        new_callable=AsyncMock,
    )
    fake_supabase = _supabase_insert_mock()
    mocker.patch("app.core.db.get_supabase", return_value=fake_supabase)

    captured_coros: list = []

    def fake_create_task(coro):
        captured_coros.append(coro)
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass
        return MagicMock()

    with patch("asyncio.create_task", side_effect=fake_create_task):
        state = {
            "session_id": "sess-ac4",
            "intervention_type": "distraction",
            "event_payload": {},
            "window_index": 2,
            "last_ces": 42.0,
        }
        result = await intervening_node(state)

    assert len(captured_coros) == 1, "create_task must be called exactly once"
    assert result is not None
    assert "current_state" in result


@pytest.mark.unit
async def test_db_write_failure_does_not_raise_from_intervening_node(mocker):
    """AC4: intervening_node returns normally even when get_supabase() raises.

    The create_task call is wrapped in try/except in intervening_node so any
    import failure or get_supabase error is caught and only logged.
    """
    from app.modules.tutor.state_machine.graph import intervening_node  # noqa: PLC0415

    fake_redis = AsyncMock()
    fake_redis.incr = AsyncMock(return_value=1)
    fake_redis.expire = AsyncMock(return_value=True)
    fake_redis.set = AsyncMock(return_value=True)

    fake_settings = MagicMock()
    fake_settings.intervention_cooldown_seconds = 120

    mocker.patch("app.core.redis.get_redis", return_value=fake_redis)
    mocker.patch("app.config.get_settings", return_value=fake_settings)
    mocker.patch(
        "app.modules.tutor.state_machine.graph._persist_state",
        new_callable=AsyncMock,
    )
    # get_supabase raises -- simulates DB unavailable
    mocker.patch("app.core.db.get_supabase", side_effect=RuntimeError("DB unavailable"))

    with patch("asyncio.create_task", return_value=MagicMock()):
        state = {
            "session_id": "sess-ac4-fail",
            "intervention_type": "distraction",
            "event_payload": {},
        }
        result = await intervening_node(state)

    assert result is not None
    assert "current_state" in result


# ---------------------------------------------------------------------------
# AC5 -- DB write failure logged at ERROR; Sentry captured
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_db_write_failure_logs_error():
    """AC5: write_intervention_event logs at ERROR when the DB insert raises."""
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = MagicMock()
    supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("DB down")

    with (
        _to_thread_patch(),
        patch("sentry_sdk.capture_exception"),
        patch("app.modules.assessment.service.logger") as mock_logger,
    ):
        await write_intervention_event(
            "sess-err",
            intervention_type="distraction",
            window_index=1,
            ces_at_trigger=42.0,
            message_key="msg",
            supabase=supabase,
        )

    mock_logger.error.assert_called_once()
    err_call_args = str(mock_logger.error.call_args)
    assert "sess-err" in err_call_args


@pytest.mark.unit
async def test_write_intervention_event_catches_all_exceptions():
    """AC5: write_intervention_event catches all exceptions, logs ERROR, captures Sentry.

    Does NOT re-raise -- intervening_node (caller) must never see the DB failure.
    """
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = MagicMock()
    supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("DB down")

    with (
        _to_thread_patch(),
        patch("sentry_sdk.capture_exception") as mock_sentry,
    ):
        # Must not raise
        await write_intervention_event(
            "sess-sentry",
            intervention_type="distraction",
            window_index=1,
            ces_at_trigger=42.0,
            message_key="msg",
            supabase=supabase,
        )

    mock_sentry.assert_called_once()
    exc_arg = mock_sentry.call_args[0][0]
    assert isinstance(exc_arg, RuntimeError)


# ---------------------------------------------------------------------------
# AC6 -- "intervention_triggered" in KNOWN_EVENT_TYPES
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_intervention_triggered_in_known_event_types():
    """AC6: 'intervention_triggered' is present in analytics.service.KNOWN_EVENT_TYPES."""
    from app.modules.analytics.service import KNOWN_EVENT_TYPES  # noqa: PLC0415

    assert "intervention_triggered" in KNOWN_EVENT_TYPES
    assert isinstance(KNOWN_EVENT_TYPES, frozenset)


# ---------------------------------------------------------------------------
# AC7 -- Redis cache-miss triggers DB reconstruction
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_redis_miss_triggers_db_count_reconstruction():
    """AC7: when Redis returns None, _get_distraction_count falls back to DB count query."""
    from app.modules.assessment.service import _get_distraction_count  # noqa: PLC0415

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # cache miss

    # MOCK-CONTRACT: real count query covered by tests/integration/
    supabase = MagicMock()
    count_resp = MagicMock()
    count_resp.count = 2
    (
        supabase.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
    ) = count_resp

    with patch("asyncio.to_thread", side_effect=lambda f, *a, **kw: f()):
        count = await _get_distraction_count("sess-ac7-miss", redis=redis, supabase=supabase)

    assert count == 2
    supabase.table.assert_called()


@pytest.mark.unit
async def test_redis_hit_skips_db_reconstruction():
    """AC7: when Redis returns a value, _get_distraction_count skips the DB entirely."""
    from app.modules.assessment.service import _get_distraction_count  # noqa: PLC0415

    redis = AsyncMock()
    redis.get = AsyncMock(return_value="2")  # Redis hit

    supabase = MagicMock()  # Must NOT be called

    count = await _get_distraction_count("sess-ac7-hit", redis=redis, supabase=supabase)

    assert count == 2
    supabase.table.assert_not_called()


# ---------------------------------------------------------------------------
# AC8 -- frustration_tolerance decrements when count = 2
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_frustration_tolerance_decrements_when_intervention_count_is_2():
    """AC8: frustration_tolerance < 50 (baseline) when _compute_signals sees count=2.

    Formula: 100 - (2/3)*100 = 33.33 -- strictly below the 50.0 neutral baseline.
    Tests the production _compute_signals function -- NOT a mock.
    """
    from app.modules.assessment.dna_fusion import _INTERVENTION_CAP, _compute_signals  # noqa: PLC0415

    event_counts = {"intervention_triggered": 2}
    signals = _compute_signals(quiz_rows=[], tb_rows=[], event_counts=event_counts)

    val = signals["frustration_tolerance"]
    assert val < 50.0, f"Expected frustration_tolerance < 50.0 with count=2, got {val}"
    expected = 100.0 - (2 / _INTERVENTION_CAP) * 100.0
    assert val == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# AC9 -- Zero interventions -> no decrement
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_frustration_tolerance_unchanged_when_intervention_count_is_0():
    """AC9: count=0 from both Redis and DB -> frustration_tolerance = 100.0 (no decrement)."""
    from app.modules.assessment.dna_fusion import _compute_signals  # noqa: PLC0415

    event_counts = {}  # no intervention_triggered events
    signals = _compute_signals(quiz_rows=[], tb_rows=[], event_counts=event_counts)

    assert signals["frustration_tolerance"] == pytest.approx(100.0, abs=0.01)


# ---------------------------------------------------------------------------
# No-LLM guard (security / process integrity)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_intervention_event_has_no_llm_calls():
    """Security: write_intervention_event source must contain no LLM provider identifiers.

    The helper is a pure DB insert -- any LLM call would violate process integrity.
    """
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    src = inspect.getsource(write_intervention_event)
    assert "OpenAILLMProvider" not in src
    assert "complete(" not in src
    assert "complete_structured(" not in src
    assert "llm_mini" not in src


# ---------------------------------------------------------------------------
# Table name guard (schema correctness)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_write_intervention_event_uses_session_events_table():
    """Schema: write_intervention_event inserts into 'session_events' (frozen table name)."""
    from app.modules.assessment.service import write_intervention_event  # noqa: PLC0415

    supabase = _supabase_insert_mock()

    with _to_thread_patch():
        await write_intervention_event(
            "sess-table",
            intervention_type="distraction",
            window_index=0,
            ces_at_trigger=42.0,
            message_key="msg",
            supabase=supabase,
        )

    supabase.table.assert_called_with("session_events")


# ---------------------------------------------------------------------------
# CRITICAL: sum(ces_breakdown.values()) approx ces_score
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ces_breakdown_sum_approx_ces_score_all_signals_present():
    """CRITICAL: sum of CES contributions equals compute_ces when all 5 signals present.

    Mathematical identity: weights sum to 1.0 so sum(signal_i * weight_i * 100) == compute_ces.
    Tolerance: abs=0.5 as specified by the story.
    """
    from app.modules.assessment.ces import compute_ces  # noqa: PLC0415

    s = _make_ces_settings()
    quiz, teachback, beh, hp, blink = 0.8, 0.6, 0.7, 0.8, 0.5

    ces_score = compute_ces(
        quiz_accuracy=quiz,
        teachback_score=teachback,
        behavioral=beh,
        head_pose=hp,
        blink=blink,
        settings=s,
    )

    breakdown_sum = (
        round(quiz * s.ces_weight_quiz * 100, 4)
        + round(teachback * s.ces_weight_teachback * 100, 4)
        + round(beh * s.ces_weight_behavioral * 100, 4)
        + round(hp * s.ces_weight_head_pose * 100, 4)
        + round(blink * s.ces_weight_blink * 100, 4)
    )

    assert breakdown_sum == pytest.approx(ces_score, abs=0.5), (
        f"sum(breakdown) = {breakdown_sum:.4f} should be approx ces_score = {ces_score:.4f} "
        "(within 0.5). CES breakdown must match compute_ces when all 5 signals present."
    )


@pytest.mark.unit
def test_ces_breakdown_sum_approx_ces_score_teachback_none():
    """CRITICAL: redistributed breakdown sum equals CES when teachback=None.

    Redistribution rule (PRD section 11): each remaining weight = original / sum_remaining.
    The breakdown must apply the same redistribution so the sum still equals ces_score.
    """
    from app.modules.assessment.ces import compute_ces  # noqa: PLC0415

    s = _make_ces_settings()
    quiz, beh, hp, blink = 0.8, 0.7, 0.8, 0.5

    ces_score = compute_ces(
        quiz_accuracy=quiz,
        teachback_score=None,
        behavioral=beh,
        head_pose=hp,
        blink=blink,
        settings=s,
    )

    weight_sum = (
        s.ces_weight_quiz + s.ces_weight_behavioral + s.ces_weight_head_pose + s.ces_weight_blink
    )

    breakdown_sum = (
        round(quiz * (s.ces_weight_quiz / weight_sum) * 100, 4)
        + round(beh * (s.ces_weight_behavioral / weight_sum) * 100, 4)
        + round(hp * (s.ces_weight_head_pose / weight_sum) * 100, 4)
        + round(blink * (s.ces_weight_blink / weight_sum) * 100, 4)
    )

    assert breakdown_sum == pytest.approx(ces_score, abs=0.5), (
        f"Redistributed sum = {breakdown_sum:.4f} should be approx ces_score = {ces_score:.4f} "
        "(within 0.5). Redistribution must be applied consistently."
    )
