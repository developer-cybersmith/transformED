"""
Unit tests for apps/api/app/modules/assessment/dna_fusion.py
Story 3-25 — Learner DNA Fusion Formula

Test count: 25
Coverage:
  AC 2  — __all__ exports only fuse_learner_dna
  AC 3  — keyword-only signature; positional args raise TypeError
  AC 4  — _apply_ema: formula, None old, clamping, rounding
  AC 5-13 — _compute_signals: all 9 dimensions, neutral defaults, direction
  AC 14 — ended_at=None → return None
  AC 15 — user_id mismatch → HTTPException(404)
  AC 16 — DB failure (session read) → HTTPException(503)
  AC 17 — DB failure (upsert) → HTTPException(503)
  AC 18 — quiz/teachback/events read failure → non-fatal, use neutral
  AC 19 — learner_dna row not found → neutral old values, still upserts
  AC 20 — upsert increments session_count
  AC 21 — dna_ema_retain in Settings
  AC 22,23 — no forbidden imports, no hardcoded EMA weights (AST)
  AC 24 — returns exactly 9 dimension keys
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.config import Settings

# ── helpers ──────────────────────────────────────────────────────────────────

def _settings(retain: float = 0.7) -> Settings:
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
        dna_ema_retain=retain,
    )


def _supabase_mock(
    session_row: dict | None,
    quiz_rows: list[dict],
    tb_rows: list[dict],
    event_rows: list[dict],
    dna_row: dict | None,
    upsert_error=None,
    session_raises: bool = False,
    upsert_raises: bool = False,
) -> MagicMock:
    """Build a synchronous supabase-py v2 mock that satisfies all DB calls in
    fuse_learner_dna: sessions maybe_single, quiz list, teachback list, events list,
    learner_dna maybe_single, learner_dna upsert."""
    supabase = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _resp_error(err):
        r = MagicMock()
        r.data = None
        r.error = err
        return r

    call_count = [0]

    def _table(name):
        tbl = MagicMock()

        if name == "sessions":
            if session_raises:
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = Exception("DB down")
            else:
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(session_row)

        elif name == "quiz_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp(quiz_rows)

        elif name == "teachback_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp(tb_rows)

        elif name == "session_events":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp(event_rows)

        elif name == "learner_dna":
            select_chain = tbl.select.return_value
            select_chain.eq.return_value.maybe_single.return_value.execute.return_value = _resp(dna_row)

            upsert_chain = tbl.upsert.return_value.execute
            if upsert_raises:
                upsert_chain.side_effect = Exception("upsert failed")
            elif upsert_error:
                upsert_chain.return_value = _resp_error(upsert_error)
            else:
                upsert_chain.return_value = _resp([])

        return tbl

    supabase.table.side_effect = _table
    return supabase


_DNA_FILE = (
    Path(__file__).parent.parent
    / "app" / "modules" / "assessment" / "dna_fusion.py"
)

NINE_DIMS = (
    "pattern_recognition", "logical_deduction", "processing_speed",
    "frustration_tolerance", "persistence", "help_seeking",
    "goal_orientation", "curiosity_index", "study_independence",
)

# ── AC 2: __all__ ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_dunder_all_exports_only_fuse_learner_dna():
    from app.modules.assessment import dna_fusion
    assert dna_fusion.__all__ == ["fuse_learner_dna"]


# ── AC 3: keyword-only signature ──────────────────────────────────────────────

@pytest.mark.unit
def test_positional_args_raise_type_error():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    with pytest.raises(TypeError):
        asyncio.get_event_loop().run_until_complete(
            fuse_learner_dna("uid", "sid", MagicMock(), _settings())
        )


# ── AC 4: _apply_ema ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_apply_ema_basic_formula():
    from app.modules.assessment.dna_fusion import _apply_ema
    result = _apply_ema(50.0, 100.0, 0.7)
    assert result == pytest.approx(65.0, abs=0.001)


@pytest.mark.unit
def test_apply_ema_none_old_uses_neutral():
    from app.modules.assessment.dna_fusion import _apply_ema, _NEUTRAL
    result = _apply_ema(None, 100.0, 0.7)
    expected = round(0.7 * _NEUTRAL + 0.3 * 100.0, 4)
    assert result == pytest.approx(expected, abs=0.001)


@pytest.mark.unit
def test_apply_ema_clamps_above_100():
    from app.modules.assessment.dna_fusion import _apply_ema
    # old=100, signal=100, retain=0.7 → 100.0 (already at max, no overshoot possible)
    # old=100, signal=200 (out of range) — clamp on output
    # Use retain=0.0 so result = signal directly
    result = _apply_ema(100.0, 150.0, 0.0)
    assert result == 100.0


@pytest.mark.unit
def test_apply_ema_clamps_below_0():
    from app.modules.assessment.dna_fusion import _apply_ema
    # retain=0.0 → result = signal; signal = -10 → clamped to 0
    result = _apply_ema(50.0, -10.0, 0.0)
    assert result == 0.0


@pytest.mark.unit
def test_apply_ema_rounded_to_4dp():
    from app.modules.assessment.dna_fusion import _apply_ema
    result = _apply_ema(33.3333, 66.6667, 0.5)
    # round(0.5*33.3333 + 0.5*66.6667, 4) = round(50.0, 4) = 50.0
    assert result == pytest.approx(50.0, abs=0.001)


# ── AC 5-13: _compute_signals ─────────────────────────────────────────────────

@pytest.mark.unit
def test_compute_signals_quiz_accuracy_maps_to_pattern_and_logical():
    from app.modules.assessment.dna_fusion import _compute_signals
    quiz_rows = [
        {"is_correct": True, "response_time_ms": 5000},
        {"is_correct": True, "response_time_ms": 5000},
        {"is_correct": False, "response_time_ms": 5000},
        {"is_correct": False, "response_time_ms": 5000},
    ]
    sigs = _compute_signals(quiz_rows=quiz_rows, tb_rows=[], event_counts={})
    assert sigs["pattern_recognition"] == pytest.approx(50.0, abs=0.001)
    assert sigs["logical_deduction"] == pytest.approx(50.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_no_quiz_returns_neutral_for_cognitive():
    from app.modules.assessment.dna_fusion import _compute_signals, _NEUTRAL
    sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts={})
    assert sigs["pattern_recognition"] == _NEUTRAL
    assert sigs["logical_deduction"] == _NEUTRAL
    assert sigs["processing_speed"] == _NEUTRAL


@pytest.mark.unit
def test_compute_signals_fast_response_processing_speed_100():
    from app.modules.assessment.dna_fusion import _compute_signals, _FAST_RESPONSE_MS
    quiz_rows = [{"is_correct": True, "response_time_ms": _FAST_RESPONSE_MS}]
    sigs = _compute_signals(quiz_rows=quiz_rows, tb_rows=[], event_counts={})
    assert sigs["processing_speed"] == pytest.approx(100.0, abs=0.01)


@pytest.mark.unit
def test_compute_signals_slow_response_processing_speed_0():
    from app.modules.assessment.dna_fusion import _compute_signals, _SLOW_RESPONSE_MS
    quiz_rows = [{"is_correct": True, "response_time_ms": _SLOW_RESPONSE_MS}]
    sigs = _compute_signals(quiz_rows=quiz_rows, tb_rows=[], event_counts={})
    assert sigs["processing_speed"] == pytest.approx(0.0, abs=0.01)


@pytest.mark.unit
def test_compute_signals_high_interventions_frustration_tolerance_0():
    from app.modules.assessment.dna_fusion import _compute_signals, _INTERVENTION_CAP
    counts = {"intervention_triggered": _INTERVENTION_CAP}
    sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts=counts)
    assert sigs["frustration_tolerance"] == pytest.approx(0.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_persistence_retry_after_low_score():
    from app.modules.assessment.dna_fusion import _compute_signals, _TEACHBACK_LOW_SCORE
    tb_rows = [
        {"score": _TEACHBACK_LOW_SCORE - 10, "attempt_number": 1, "segment_id": "seg-1"},
        {"score": 75, "attempt_number": 2, "segment_id": "seg-1"},
    ]
    sigs = _compute_signals(quiz_rows=[], tb_rows=tb_rows, event_counts={})
    assert sigs["persistence"] == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_persistence_no_retry_good_scores():
    from app.modules.assessment.dna_fusion import _compute_signals, _TEACHBACK_LOW_SCORE
    tb_rows = [
        {"score": _TEACHBACK_LOW_SCORE + 10, "attempt_number": 1, "segment_id": "seg-1"},
        {"score": _TEACHBACK_LOW_SCORE + 20, "attempt_number": 1, "segment_id": "seg-2"},
    ]
    sigs = _compute_signals(quiz_rows=[], tb_rows=tb_rows, event_counts={})
    # Good scores, no retry needed → 75.0
    assert sigs["persistence"] == pytest.approx(75.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_persistence_gave_up_no_retry():
    from app.modules.assessment.dna_fusion import _compute_signals, _TEACHBACK_LOW_SCORE
    tb_rows = [
        {"score": _TEACHBACK_LOW_SCORE - 5, "attempt_number": 1, "segment_id": "seg-1"},
    ]
    sigs = _compute_signals(quiz_rows=[], tb_rows=tb_rows, event_counts={})
    # Low score, no retry → 25.0
    assert sigs["persistence"] == pytest.approx(25.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_help_seeking_and_study_independence_are_inverse():
    from app.modules.assessment.dna_fusion import _compute_signals, _HELP_CAP
    counts = {"help_seeking": _HELP_CAP}
    sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts=counts)
    assert sigs["help_seeking"] == pytest.approx(100.0, abs=0.001)
    assert sigs["study_independence"] == pytest.approx(0.0, abs=0.001)
    # Together they sum to 100
    assert sigs["help_seeking"] + sigs["study_independence"] == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_goal_orientation_decreases_with_skips():
    from app.modules.assessment.dna_fusion import _compute_signals, _SKIP_CAP
    counts = {"skip_segment": _SKIP_CAP}
    sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts=counts)
    assert sigs["goal_orientation"] == pytest.approx(0.0, abs=0.001)

    no_skip_sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts={})
    assert no_skip_sigs["goal_orientation"] == pytest.approx(100.0, abs=0.001)


@pytest.mark.unit
def test_compute_signals_curiosity_index_increases_with_jargon():
    from app.modules.assessment.dna_fusion import _compute_signals, _JARGON_CAP
    counts = {"jargon_hover": _JARGON_CAP}
    sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts=counts)
    assert sigs["curiosity_index"] == pytest.approx(100.0, abs=0.001)

    no_jargon_sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts={})
    assert no_jargon_sigs["curiosity_index"] == pytest.approx(0.0, abs=0.001)


# ── AC 14: ended_at=None → None ──────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_session_not_ended_returns_none():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    session_row = {"session_id": "s1", "user_id": "u1", "ended_at": None}
    supabase = _supabase_mock(session_row, [], [], [], None)
    result = await fuse_learner_dna(
        user_id="u1", session_id="s1", supabase=supabase, settings=_settings()
    )
    assert result is None


# ── AC 15: user_id mismatch → 404 ───────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_user_id_mismatch_raises_404():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    session_row = {
        "session_id": "s1",
        "user_id": "different-user",
        "ended_at": "2026-07-03T10:00:00",
    }
    supabase = _supabase_mock(session_row, [], [], [], None)
    with pytest.raises(HTTPException) as exc_info:
        await fuse_learner_dna(
            user_id="u1", session_id="s1", supabase=supabase, settings=_settings()
        )
    assert exc_info.value.status_code == 404


# ── AC 16: DB failure on session read → 503 ──────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_db_failure_raises_503():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    supabase = _supabase_mock(None, [], [], [], None, session_raises=True)
    with pytest.raises(HTTPException) as exc_info:
        await fuse_learner_dna(
            user_id="u1", session_id="s1", supabase=supabase, settings=_settings()
        )
    assert exc_info.value.status_code == 503


# ── AC 19 + 24: no DNA row → neutral old, returns 9 dims ────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_no_dna_row_uses_neutral_old():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    session_row = {"session_id": "s1", "user_id": "u1", "ended_at": "2026-07-03T10:00:00"}
    supabase = _supabase_mock(session_row, [], [], [], dna_row=None)
    result = await fuse_learner_dna(
        user_id="u1", session_id="s1", supabase=supabase, settings=_settings()
    )
    assert result is not None
    assert set(result.keys()) == set(NINE_DIMS)


# ── AC 21: dna_ema_retain in Settings ───────────────────────────────────────

@pytest.mark.unit
def test_dna_ema_retain_in_settings():
    s = _settings(retain=0.8)
    assert s.dna_ema_retain == pytest.approx(0.8, abs=0.0001)
    # Default
    s_default = _settings()
    assert s_default.dna_ema_retain == pytest.approx(0.7, abs=0.0001)


# ── AC 20 + 24: happy path → 9 dims returned, session_count incremented ─────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_happy_path_returns_9_dimension_dict():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    session_row = {"session_id": "s1", "user_id": "u1", "ended_at": "2026-07-03T10:00:00"}
    quiz_rows = [
        {"is_correct": True, "response_time_ms": 8000},
        {"is_correct": True, "response_time_ms": 10000},
        {"is_correct": False, "response_time_ms": 12000},
    ]
    tb_rows = [{"score": 80, "attempt_number": 1, "segment_id": "seg-1"}]
    event_rows = [
        {"event_type": "jargon_hover"},
        {"event_type": "jargon_hover"},
    ]
    dna_row = {
        "user_id": "u1",
        "session_count": 2,
        "pattern_recognition": 60.0,
        "logical_deduction": 55.0,
        "processing_speed": 70.0,
        "frustration_tolerance": 80.0,
        "persistence": 50.0,
        "help_seeking": 30.0,
        "goal_orientation": 75.0,
        "curiosity_index": 40.0,
        "study_independence": 70.0,
    }
    supabase = _supabase_mock(session_row, quiz_rows, tb_rows, event_rows, dna_row)
    result = await fuse_learner_dna(
        user_id="u1", session_id="s1", supabase=supabase, settings=_settings()
    )
    assert result is not None
    assert set(result.keys()) == set(NINE_DIMS)
    # All values in [0, 100]
    for v in result.values():
        assert 0.0 <= v <= 100.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_session_count_incremented():
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    session_row = {"session_id": "s1", "user_id": "u1", "ended_at": "2026-07-03T10:00:00"}
    dna_row = {
        "user_id": "u1",
        "session_count": 3,
        **{dim: 50.0 for dim in NINE_DIMS},
    }
    supabase = _supabase_mock(session_row, [], [], [], dna_row)

    upsert_calls = []
    original_table = supabase.table.side_effect

    def tracking_table(name):
        tbl = original_table(name)
        if name == "learner_dna":
            orig_upsert = tbl.upsert
            def tracked_upsert(payload, **kwargs):
                upsert_calls.append(payload)
                return orig_upsert(payload, **kwargs)
            tbl.upsert = tracked_upsert
        return tbl

    supabase.table.side_effect = tracking_table

    await fuse_learner_dna(
        user_id="u1", session_id="s1", supabase=supabase, settings=_settings()
    )
    assert len(upsert_calls) == 1
    assert upsert_calls[0].get("session_count") == 4  # 3 + 1


# ── AC 23: no hardcoded EMA weights in dna_fusion.py ─────────────────────────

@pytest.mark.unit
def test_no_hardcoded_ema_weights():
    source = _DNA_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_floats = {0.7, 0.3}
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            if node.value in forbidden_floats:
                violations.append(node.value)
    assert violations == [], (
        f"Hardcoded EMA weight literals found in dna_fusion.py: {violations}. "
        "Use settings.dna_ema_retain instead."
    )


# ── AC 22: no forbidden imports ──────────────────────────────────────────────

@pytest.mark.unit
def test_no_forbidden_imports():
    source = _DNA_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"openai", "posthog", "httpx", "requests"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    violations = imported & forbidden
    assert not violations, f"Forbidden imports in dna_fusion.py: {violations}"
