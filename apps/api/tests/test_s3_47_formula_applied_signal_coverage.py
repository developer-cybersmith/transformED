"""RED tests for S3-47 (D17): formula_applied + signal_coverage fields in SessionReport.

All 12 tests written RED-first — they fail before the two new fields are added
to SessionReport in router.py and populated in get_session_report in service.py.
"""

from __future__ import annotations

import typing
from unittest.mock import MagicMock, patch

import pytest

# ── Shared Supabase mock ───────────────────────────────────────────────────────


def _build_supabase(*, tb_rows: list, quiz_rows: list | None = None) -> MagicMock:
    """Minimal 7-table Supabase mock wired to get_session_report's call sequence."""
    if quiz_rows is None:
        quiz_rows = [{"is_correct": True}, {"is_correct": False}]

    session_row = {
        "session_id": "ses-47",
        "user_id": "user-47",
        "lesson_id": "lesson-47",
        "ces_final": 65.0,
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
            m.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = quiz_rows
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
            m.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        return m

    mock.table.side_effect = _table
    return mock


def _mock_settings_obj() -> MagicMock:
    s = MagicMock()
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    return s


async def _run_report(*, tb_rows: list, quiz_rows: list | None = None):
    """Run get_session_report with a controlled Supabase mock."""

    from app.modules.assessment.service import get_session_report

    async def _shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("app.modules.assessment.service.asyncio.to_thread", side_effect=_shim),
        patch(
            "app.modules.assessment.service.get_settings",
            return_value=_mock_settings_obj(),
        ),
    ):
        return await get_session_report(
            session_id="ses-47",
            user_id="user-47",
            supabase=_build_supabase(tb_rows=tb_rows, quiz_rows=quiz_rows),
        )


# ── AC 2 & AC 6: full_5_signal when teachback present ─────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_formula_applied_full_5_signal_when_teachback_present():
    """AC 2: formula_applied == 'full_5_signal' when teachback_attempts rows exist."""
    report = await _run_report(tb_rows=[{"score": 80}])
    assert report.formula_applied == "full_5_signal"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signal_coverage_5_when_teachback_present():
    """AC 6: signal_coverage == 5 when teachback rows exist."""
    report = await _run_report(tb_rows=[{"score": 80}])
    assert report.signal_coverage == 5


# ── AC 3 & AC 7: teachback_redistributed_4_signal when teachback absent ────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_formula_applied_redistributed_when_teachback_absent():
    """AC 3: formula_applied == 'teachback_redistributed_4_signal' when zero teachback rows."""
    report = await _run_report(tb_rows=[])
    assert report.formula_applied == "teachback_redistributed_4_signal"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signal_coverage_4_when_teachback_absent():
    """AC 7: signal_coverage == 4 when zero teachback rows."""
    report = await _run_report(tb_rows=[])
    assert report.signal_coverage == 4


# ── AC 4: formula_applied is Literal type ─────────────────────────────────────


@pytest.mark.unit
def test_formula_applied_is_literal_type():
    """AC 4: SessionReport.formula_applied annotated as Literal, not bare str."""
    from app.modules.assessment.router import SessionReport

    hints = typing.get_type_hints(SessionReport)
    fa_type = hints["formula_applied"]
    origin = typing.get_origin(fa_type)
    assert origin is typing.Literal, (
        f"formula_applied should be Literal, got {fa_type!r}"
    )


# ── AC 8: signal_coverage is int type ─────────────────────────────────────────


@pytest.mark.unit
def test_signal_coverage_is_int_type():
    """AC 8: SessionReport.signal_coverage annotated as int (not Optional, not float)."""
    from app.modules.assessment.router import SessionReport

    hints = typing.get_type_hints(SessionReport)
    assert hints["signal_coverage"] is int


# ── AC 9: signal_coverage range [0, 5] ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signal_coverage_range_is_0_to_5():
    """AC 9: 0 <= signal_coverage <= 5 for both formula variants."""
    report_with_tb = await _run_report(tb_rows=[{"score": 75}])
    report_no_tb = await _run_report(tb_rows=[])
    assert 0 <= report_with_tb.signal_coverage <= 5
    assert 0 <= report_no_tb.signal_coverage <= 5


# ── AC 10: formula_applied and signal_coverage are consistent ─────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fields_consistent_when_teachback_present():
    """AC 10: full_5_signal ↔ signal_coverage == 5 (must agree, not disagree)."""
    report = await _run_report(tb_rows=[{"score": 80}])
    assert (report.formula_applied == "full_5_signal") == (report.signal_coverage == 5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fields_consistent_when_teachback_absent():
    """AC 10: teachback_redistributed_4_signal ↔ signal_coverage == 4 (must agree)."""
    report = await _run_report(tb_rows=[])
    assert (report.formula_applied == "teachback_redistributed_4_signal") == (
        report.signal_coverage == 4
    )


# ── AC 11 & AC 12: both fields appear in the OpenAPI spec ────────────────────


@pytest.mark.unit
def test_openapi_spec_includes_formula_applied():
    """AC 11: exported OpenAPI spec has formula_applied in SessionReport properties."""
    from scripts.export_openapi import build_spec_app

    spec = build_spec_app().openapi()
    props = spec["components"]["schemas"]["SessionReport"]["properties"]
    assert "formula_applied" in props, f"formula_applied missing from spec; keys={list(props)}"


@pytest.mark.unit
def test_openapi_spec_includes_signal_coverage():
    """AC 12: exported OpenAPI spec has signal_coverage in SessionReport properties."""
    from scripts.export_openapi import build_spec_app

    spec = build_spec_app().openapi()
    props = spec["components"]["schemas"]["SessionReport"]["properties"]
    assert "signal_coverage" in props, f"signal_coverage missing from spec; keys={list(props)}"


# ── AC 13: no pre-S3-47 field removed or renamed ─────────────────────────────


@pytest.mark.unit
def test_no_existing_field_removed_or_renamed():
    """AC 13: all pre-S3-47 SessionReport fields are still present."""
    from app.modules.assessment.router import SessionReport

    pre_s3_47_fields = {
        "session_id",
        "user_id",
        "lesson_id",
        "ces_score",
        "ces_breakdown",
        "interventions_count",
        "quiz_score",
        "teachback_score",
        "duration_minutes",
        "completed_at",
        "tier",
        "tier_label",
        "quiz_total_questions",
        "quiz_correct_count",
        "quiz_accuracy_label",
        "learner_dna_snapshot",
    }
    actual_fields = set(SessionReport.model_fields.keys())
    missing = pre_s3_47_fields - actual_fields
    assert not missing, f"Pre-S3-47 fields missing from SessionReport: {missing}"
