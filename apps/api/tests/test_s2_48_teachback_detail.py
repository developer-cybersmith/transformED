"""Tests for Story 2-48: teachback_details field in SessionReport.

AC-1  GET session report includes teachback_details field.
AC-2  teachback_details is None when session has no teachback rows.
AC-3  Each TeachbackDetail has exactly 7 fields matching DB columns.
AC-4  Details ordered by created_at ascending (.order("created_at") in query).
AC-5  At most 50 rows (limit preserved).
AC-6  No migration required — verified by column presence in existing migration.
AC-7  teachback_score aggregate is unchanged by the new detail field.
AC-8  No LLM call — verified by mock patch coverage.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── shared mock builder ───────────────────────────────────────────────────────


def _build_supabase(*, tb_rows: list, quiz_rows: list | None = None) -> MagicMock:
    """Minimal Supabase mock wired to get_session_report's 7-table call sequence."""
    if quiz_rows is None:
        quiz_rows = [{"is_correct": True}, {"is_correct": False}]

    session_row = {
        "session_id": "ses-248",
        "user_id": "user-248",
        "lesson_id": "lesson-248",
        "ces_final": 70.0,
        "started_at": "2026-08-18T10:00:00+00:00",
        "ended_at": "2026-08-18T10:30:00+00:00",
    }
    tier_row = {"tier": "T2"}

    mock = MagicMock()
    call_count = [0]

    def _table(_name):
        call_count[0] += 1
        n = call_count[0]
        m = MagicMock()
        _ms = m.select.return_value.eq.return_value.maybe_single.return_value.execute
        _s2 = m.select.return_value.eq.return_value.eq.return_value.execute
        if n == 1:
            _ms.return_value.data = session_row
        elif n == 2:
            _ms.return_value.data = tier_row
        elif n == 3:
            # quiz_attempts: .select(...).eq(...).limit(500).execute()
            _qlim = m.select.return_value.eq.return_value.limit.return_value
            _qlim.execute.return_value.data = quiz_rows
        elif n == 4:
            # teachback_attempts: .select(...).eq(...).order(...).limit(50).execute()
            _tord = m.select.return_value.eq.return_value.order.return_value
            _tord.limit.return_value.execute.return_value.data = tb_rows
        elif n == 5:
            _s2.return_value.count = 0
        elif n == 6:
            _ms.return_value.data = None
        elif n == 7:
            _s2.return_value.data = []
            _dlim = m.select.return_value.eq.return_value.eq.return_value.limit.return_value
            _dlim.execute.return_value.data = []
        return m

    mock.table.side_effect = _table
    return mock


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.ces_weight_quiz = 0.35
    s.ces_weight_teachback = 0.25
    s.ces_weight_behavioral = 0.20
    s.ces_weight_head_pose = 0.12
    s.ces_weight_blink = 0.08
    return s


async def _run_report(*, tb_rows: list, quiz_rows: list | None = None):
    from app.modules.assessment.service import get_session_report

    async def _shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    with (
        patch("app.modules.assessment.service.asyncio.to_thread", side_effect=_shim),
        patch("app.modules.assessment.service.get_settings", return_value=_mock_settings()),
    ):
        return await get_session_report(
            session_id="ses-248",
            user_id="user-248",
            supabase=_build_supabase(tb_rows=tb_rows, quiz_rows=quiz_rows),
        )


_FULL_ROW = {
    "segment_id": "seg-1",
    "score": 85,
    "feedback_praise": "Great explanation of mitosis.",
    "feedback_correction": "Cell plate forms before cleavage furrow.",
    "concepts_hit": ["mitosis", "chromosomes"],
    "concepts_missed": ["cytokinesis"],
    "attempt_number": 1,
}

_SECOND_ROW = {
    "segment_id": "seg-2",
    "score": 60,
    "feedback_praise": "Correct on osmosis.",
    "feedback_correction": None,
    "concepts_hit": ["osmosis"],
    "concepts_missed": [],
    "attempt_number": 1,
}


# ── AC-1: field present in response ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_details_field_present_on_report():
    """AC-1: teachback_details key exists in the report response."""
    report = await _run_report(tb_rows=[_FULL_ROW])
    assert hasattr(report, "teachback_details")


# ── AC-2: None when no rows ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_details_is_none_when_no_attempts():
    """AC-2: teachback_details is None (not []) when the session has no teach-back rows."""
    report = await _run_report(tb_rows=[])
    assert report.teachback_details is None


# ── AC-3: 7-field model ───────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_detail_has_seven_fields():
    """AC-3: each TeachbackDetail exposes exactly the 7 DB-mapped fields."""
    report = await _run_report(tb_rows=[_FULL_ROW])
    assert report.teachback_details is not None
    detail = report.teachback_details[0]
    assert detail.segment_id == "seg-1"
    assert detail.score == 85
    assert detail.feedback_praise == "Great explanation of mitosis."
    assert detail.feedback_correction == "Cell plate forms before cleavage furrow."
    assert detail.concepts_hit == ["mitosis", "chromosomes"]
    assert detail.concepts_missed == ["cytokinesis"]
    assert detail.attempt_number == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_detail_nullable_fields_can_be_none():
    """AC-3: feedback_praise and feedback_correction may be None."""
    row = {**_FULL_ROW, "feedback_praise": None, "feedback_correction": None}
    report = await _run_report(tb_rows=[row])
    detail = report.teachback_details[0]  # type: ignore[index]
    assert detail.feedback_praise is None
    assert detail.feedback_correction is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_detail_empty_concept_lists():
    """AC-3: concepts_hit / concepts_missed default to [] when absent or None."""
    row = {**_FULL_ROW, "concepts_hit": None, "concepts_missed": None}
    report = await _run_report(tb_rows=[row])
    detail = report.teachback_details[0]  # type: ignore[index]
    assert detail.concepts_hit == []
    assert detail.concepts_missed == []


# ── AC-4: ordering preserved ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_details_order_preserved_from_db():
    """AC-4: details preserve the order returned by the DB (created_at ASC from .order())."""
    report = await _run_report(tb_rows=[_FULL_ROW, _SECOND_ROW])
    assert report.teachback_details is not None
    assert len(report.teachback_details) == 2
    assert report.teachback_details[0].segment_id == "seg-1"
    assert report.teachback_details[1].segment_id == "seg-2"


# ── AC-5: limit 50 wired correctly ───────────────────────────────────────────


@pytest.mark.unit
def test_teachback_query_uses_order_and_limit_50():
    """AC-5: the Supabase call chain includes .order('created_at').limit(50)."""
    import inspect

    import app.modules.assessment.service as svc

    src = inspect.getsource(svc.get_session_report)
    assert '.order("created_at")' in src or ".order('created_at')" in src
    assert ".limit(50)" in src


# ── AC-7: aggregate teachback_score unchanged ─────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_score_aggregate_unchanged():
    """AC-7: adding teachback_details does not change the teachback_score average."""
    rows = [
        {**_FULL_ROW, "score": 80},
        {**_SECOND_ROW, "score": 60},
    ]
    report = await _run_report(tb_rows=rows)
    assert report.teachback_score == 70.0  # (80+60)/2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_teachback_score_none_when_no_attempts():
    """AC-7: teachback_score is None when teachback_details is also None."""
    report = await _run_report(tb_rows=[])
    assert report.teachback_score is None
    assert report.teachback_details is None


# ── AC-8: no LLM call ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_llm_call_in_get_session_report():
    """AC-8: get_session_report completes successfully with LLM provider blocked."""

    async def _shim(func, *args, **kwargs):
        return func(*args, **kwargs)

    def _boom(*_a, **_kw):
        raise AssertionError("get_session_report must not call any LLM")

    with (
        patch("app.modules.assessment.service.asyncio.to_thread", side_effect=_shim),
        patch("app.modules.assessment.service.get_settings", return_value=_mock_settings()),
        patch("app.modules.assessment.service.OpenAILLMProvider.complete", side_effect=_boom),
    ):
        report = await _run_report(tb_rows=[_FULL_ROW])

    assert report.teachback_details is not None
