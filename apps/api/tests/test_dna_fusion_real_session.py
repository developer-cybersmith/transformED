"""
T19 Demo — Learner DNA fusion with concrete EMA values and real session event mix.

Validates dna_fusion.py with:
  - Intermediate event counts (not just at-cap or zero)
  - Exact EMA output values in the upsert payload
  - Mixed real session: all 4 event types + quiz + teachback simultaneously
  - Two-segment teachback persistence (multi-segment grouping logic)
  - ended_at=None: no-op guard (return None, no upsert side-effect)
  - No-quiz cognitive signal policy divergence
  - IDOR → 404 (SEC-006)
  - Redis reassessment flag at session 10 (completely untested before T19)
  - Redis failure is non-fatal

9 tests: AC1 through AC9.
asyncio_mode = "auto" (pyproject.toml) — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Constants used across tests ───────────────────────────────────────────────

_USER_UUID = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
_SESSION_UUID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
_USER_B_UUID = "d4e5f6a7-b8c9-0123-defa-234567890123"

# ── Supabase mock ─────────────────────────────────────────────────────────────


def _make_resp(data: Any) -> MagicMock:
    r = MagicMock()
    r.data = data
    r.error = None
    return r


def _supabase_mock(
    *,
    session_row: dict[str, Any] | None,
    quiz_rows: list[dict[str, Any]],
    tb_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    dna_row: dict[str, Any] | None,
    capture_upsert: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Supabase client mock routed by table name (not call order — T18 P6 pattern).

    Supports an optional spy on the learner_dna upsert via `capture_upsert` (a list).
    Each upsert call appends a copy of the payload so call count is assertable.
    """
    mock = MagicMock()

    def _table(name: str) -> MagicMock:
        tbl = MagicMock()

        if name == "sessions":
            (tbl.select.return_value.eq.return_value.maybe_single.return_value.execute
             .return_value) = _make_resp(session_row)

        elif name == "quiz_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _make_resp(quiz_rows)

        elif name == "teachback_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _make_resp(tb_rows)

        elif name == "session_events":
            tbl.select.return_value.eq.return_value.limit.return_value.execute.return_value = _make_resp(event_rows)

        elif name == "learner_dna":
            # Read side — maybe_single
            (tbl.select.return_value.eq.return_value.maybe_single.return_value.execute
             .return_value) = _make_resp(dna_row)
            # Write side — upsert
            if capture_upsert is not None:
                def _spy_upsert(payload: dict[str, Any], **kwargs: Any) -> MagicMock:
                    capture_upsert.append(dict(payload))  # list prevents silent overwrite on retry
                    m = MagicMock()
                    m.execute.return_value = _make_resp([])
                    return m
                tbl.upsert.side_effect = _spy_upsert
            else:
                tbl.upsert.return_value.execute.return_value = _make_resp([])

        return tbl

    mock.table.side_effect = _table
    return mock


def _ended_session(user_id: str = _USER_UUID) -> dict[str, Any]:
    return {"session_id": _SESSION_UUID, "user_id": user_id, "ended_at": "2026-08-13T10:00:00"}


def _base_dna_row(session_count: int = 2) -> dict[str, Any]:
    return {
        "user_id": _USER_UUID,
        "session_count": session_count,
        "pattern_recognition": 80.0,
        "logical_deduction": 70.0,
        "processing_speed": 60.0,
        "frustration_tolerance": 75.0,
        "persistence": 50.0,
        "help_seeking": 30.0,
        "goal_orientation": 65.0,
        "curiosity_index": 40.0,
        "study_independence": 70.0,
    }


# ── asyncio.to_thread shim ────────────────────────────────────────────────────


@pytest.fixture
def mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shim asyncio.to_thread so synchronous MagicMock chains work in async tests."""

    async def _sync_shim(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.dna_fusion.asyncio.to_thread", _sync_shim)


# ── record_dna_growth autouse patch ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def _patch_record_dna_growth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppress Step 6 record_dna_growth DB call across all T19 tests."""
    monkeypatch.setattr(
        "app.modules.assessment.dna_growth.record_dna_growth",
        AsyncMock(return_value=None),
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — Intermediate curiosity_index: 2 jargon_hover → (2/5)*100 = 40.0
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_signals_intermediate_jargon_hover_curiosity() -> None:
    """AC1: 2 jargon_hover events (not at cap of 5) → curiosity_index=40.0.
    Validates /cap denominator at intermediate count — off-by-one (cap=4) produces 50.0."""
    from app.modules.assessment.dna_fusion import _JARGON_CAP, _compute_signals

    sigs = _compute_signals(
        quiz_rows=[],
        tb_rows=[],
        event_counts={"jargon_hover": 2},
    )

    expected_curiosity = (2 / _JARGON_CAP) * 100
    assert sigs["curiosity_index"] == pytest.approx(expected_curiosity, rel=1e-3), (
        f"2 jargon_hover / _JARGON_CAP({_JARGON_CAP}) * 100 = {expected_curiosity}; "
        f"got {sigs['curiosity_index']}"
    )
    # P6: also pin the literal 40.0 from the spec so a _JARGON_CAP constant change is caught
    assert sigs["curiosity_index"] == pytest.approx(40.0, rel=1e-3), (
        "Spec pins 40.0 (2/5*100); dynamic assertion alone cannot catch _JARGON_CAP value change"
    )
    assert sigs["study_independence"] == pytest.approx(100.0, rel=1e-3), (
        "No help_seeking events → help_signal=0 → study_independence=100.0; "
        f"got {sigs['study_independence']}"
    )
    assert 0.0 <= sigs["curiosity_index"] <= 100.0
    assert 0.0 <= sigs["study_independence"] <= 100.0


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — Mixed real-session: all 4 event types + quiz + teachback simultaneously
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_signals_mixed_real_session_all_nine_dims() -> None:
    """AC2: realistic session with all 4 event types + quiz + teachback.
    Verifies all 9 signals with formula-derived expected values simultaneously."""
    from app.modules.assessment.dna_fusion import (
        _FAST_RESPONSE_MS,
        _HELP_CAP,
        _INTERVENTION_CAP,
        _JARGON_CAP,
        _SKIP_CAP,
        _compute_signals,
    )

    quiz_rows = [
        {"is_correct": True, "response_time_ms": 10_000},
        {"is_correct": True, "response_time_ms": 10_000},
        {"is_correct": True, "response_time_ms": 10_000},
        {"is_correct": False, "response_time_ms": 10_000},
    ]
    event_counts = {
        "jargon_hover": 3,
        "help_seeking": 1,
        "skip_segment": 1,
        "intervention_triggered": 1,
    }
    tb_rows = [
        {"score": 40, "attempt_number": 1, "segment_id": "seg-B"},  # low
        {"score": 72, "attempt_number": 2, "segment_id": "seg-B"},  # retry
    ]

    sigs = _compute_signals(quiz_rows=quiz_rows, tb_rows=tb_rows, event_counts=event_counts)

    assert sigs["pattern_recognition"] == pytest.approx(75.0, rel=1e-3), (
        f"3/4 correct → 75.0; got {sigs['pattern_recognition']}"
    )
    assert sigs["logical_deduction"] == pytest.approx(75.0, rel=1e-3), (
        f"same as pattern_recognition; got {sigs['logical_deduction']}"
    )
    # P12: use rel=1e-3 consistently (1e-2 would accept 99.0 for a 100.0 expected value)
    # All responses at 10_000ms < _FAST_RESPONSE_MS=15_000 → raw_speed > 100 → clamped 100.0
    assert sigs["processing_speed"] == pytest.approx(100.0, rel=1e-3), (
        f"10_000ms < _FAST_RESPONSE_MS({_FAST_RESPONSE_MS}) → clamped 100.0; "
        f"got {sigs['processing_speed']}"
    )
    # P7: pin spec's concrete values (66.67, 25.0, 75.0, 75.0, 60.0) so cap constant changes are caught
    assert sigs["frustration_tolerance"] == pytest.approx(66.67, rel=1e-2), (
        f"1 intervention / cap({_INTERVENTION_CAP}) = (1-1/3)*100 = 66.67; "
        f"got {sigs['frustration_tolerance']}"
    )
    assert sigs["persistence"] == pytest.approx(100.0, rel=1e-3), (
        f"retry after low score → 100.0; got {sigs['persistence']}"
    )
    assert sigs["help_seeking"] == pytest.approx(25.0, rel=1e-3), (
        f"1 help_seeking / cap({_HELP_CAP}) = (1/4)*100 = 25.0; got {sigs['help_seeking']}"
    )
    assert sigs["study_independence"] == pytest.approx(75.0, rel=1e-3), (
        f"100 - 25.0 = 75.0; got {sigs['study_independence']}"
    )
    assert sigs["goal_orientation"] == pytest.approx(75.0, rel=1e-3), (
        f"1 skip / cap({_SKIP_CAP}) = (1-1/4)*100 = 75.0; got {sigs['goal_orientation']}"
    )
    assert sigs["curiosity_index"] == pytest.approx(60.0, rel=1e-3), (
        f"3 jargon / cap({_JARGON_CAP}) = (3/5)*100 = 60.0; got {sigs['curiosity_index']}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — Concrete EMA values in upsert payload
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_fuse_learner_dna_upsert_payload_contains_exact_ema_values(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC3: upsert payload has exact EMA-computed float values, not just [0,100] range.
    Closes gap in test_async_happy_path_returns_9_dimension_dict (range-only assertion)."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    from app.config import Settings

    settings = Settings(
        supabase_url="http://x", supabase_anon_key="x",
        supabase_service_role_key="x", supabase_jwt_secret="x",
        openai_api_key="x", sarvam_api_key="x", heygen_api_key="x",
        langfuse_public_key="x", langfuse_secret_key="x",
        dna_ema_retain=0.7,
    )

    # All-correct quiz → accuracy=1.0 → pattern_recognition signal = 100.0
    quiz_rows = [
        {"is_correct": True, "response_time_ms": 10_000},
        {"is_correct": True, "response_time_ms": 10_000},
    ]
    dna_row = _base_dna_row(session_count=2)  # pattern=80.0, logical=70.0
    # P2: list-based capture so a retry upsert would be caught (dict.update silently overwrites)
    captured_calls: list[dict[str, Any]] = []

    supabase = _supabase_mock(
        session_row=_ended_session(),
        quiz_rows=quiz_rows,
        tb_rows=[],
        event_rows=[],
        dna_row=dna_row,
        capture_upsert=captured_calls,
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=settings,
    )

    assert result is not None
    assert len(captured_calls) == 1, (
        f"Expected exactly 1 upsert call; got {len(captured_calls)}. "
        "Multiple calls would indicate a retry bug corrupting EMA values."
    )
    captured_upsert = captured_calls[0]

    # EMA: round(0.7*old + 0.3*signal, 4)
    expected_pattern = round(0.7 * 80.0 + 0.3 * 100.0, 4)  # = 86.0
    expected_logical = round(0.7 * 70.0 + 0.3 * 100.0, 4)  # = 79.0

    assert captured_upsert.get("pattern_recognition") == pytest.approx(
        expected_pattern, rel=1e-4
    ), (
        f"EMA(80.0, signal=100.0, retain=0.7)=86.0; "
        f"got {captured_upsert.get('pattern_recognition')}"
    )
    assert captured_upsert.get("logical_deduction") == pytest.approx(
        expected_logical, rel=1e-4
    ), (
        f"EMA(70.0, signal=100.0, retain=0.7)=79.0; "
        f"got {captured_upsert.get('logical_deduction')}"
    )
    assert captured_upsert.get("user_id") == _USER_UUID, (
        f"user_id missing from upsert payload; got {captured_upsert.get('user_id')!r}"
    )
    assert "session_count" not in captured_upsert, (
        f"session_count must NOT be in upsert payload (D74: atomic RPC handles increment); "
        f"got {captured_upsert.get('session_count')!r}"
    )
    for dim in (
        "pattern_recognition", "logical_deduction", "processing_speed",
        "frustration_tolerance", "persistence", "help_seeking",
        "goal_orientation", "curiosity_index", "study_independence",
    ):
        val = captured_upsert.get(dim)
        assert isinstance(val, float), f"{dim} in upsert payload is not float: {val!r}"


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — Two-segment teachback: persistence = 100.0 when any segment has retry
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_signals_two_segment_teachback_persistence() -> None:
    """AC4: seg-A low score + no retry; seg-B low score + retry → persistence=100.0.
    Validates multi-segment defaultdict grouping: any segment with retry wins."""
    from app.modules.assessment.dna_fusion import _compute_signals

    tb_rows = [
        {"score": 45, "attempt_number": 1, "segment_id": "seg-A"},  # low, no retry
        {"score": 50, "attempt_number": 1, "segment_id": "seg-B"},  # low
        {"score": 72, "attempt_number": 2, "segment_id": "seg-B"},  # retry on seg-B
    ]

    sigs = _compute_signals(quiz_rows=[], tb_rows=tb_rows, event_counts={})

    assert sigs["persistence"] == pytest.approx(100.0, rel=1e-3), (
        "seg-B retried after low score → had_retry_after_low=True → persistence=100.0; "
        f"got {sigs['persistence']}"
    )
    # P11: spot-check unrelated dims to catch multi-segment logic corrupting other signals
    assert sigs["curiosity_index"] == pytest.approx(0.0, abs=1e-3), (
        f"No events → curiosity_index=0.0; got {sigs['curiosity_index']}"
    )
    assert sigs["study_independence"] == pytest.approx(100.0, rel=1e-3), (
        f"No help_seeking → study_independence=100.0; got {sigs['study_independence']}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC5 — ended_at=None returns None and triggers no upsert
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_fuse_learner_dna_ended_at_none_no_upsert(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5: ended_at=None → returns None; learner_dna upsert must NOT be called.
    Strengthens AC14 from test_dna_fusion.py — existing test only checks return value."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    from app.config import Settings

    settings = Settings(
        supabase_url="http://x", supabase_anon_key="x",
        supabase_service_role_key="x", supabase_jwt_secret="x",
        openai_api_key="x", sarvam_api_key="x", heygen_api_key="x",
        langfuse_public_key="x", langfuse_secret_key="x",
    )

    session_row = {"session_id": _SESSION_UUID, "user_id": _USER_UUID, "ended_at": None}
    # P8: track ALL table accesses so we can verify early-return skips data-read tables too
    tables_accessed: list[str] = []
    upsert_called = False

    def _table(name: str) -> MagicMock:
        tables_accessed.append(name)
        tbl = MagicMock()
        if name == "sessions":
            (tbl.select.return_value.eq.return_value.maybe_single.return_value.execute
             .return_value) = _make_resp(session_row)
        elif name == "learner_dna":
            def _spy_upsert(*args: Any, **kwargs: Any) -> MagicMock:
                nonlocal upsert_called
                upsert_called = True
                m = MagicMock()
                m.execute.return_value = _make_resp([])
                return m
            tbl.upsert.side_effect = _spy_upsert
        return tbl

    supabase = MagicMock()
    supabase.table.side_effect = _table

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=settings,
    )

    assert result is None, f"Expected None for ended_at=None; got {result}"
    assert not upsert_called, (
        "learner_dna upsert should NOT be called when ended_at is None"
    )
    # AC5 spec: "supabase.table called at most once (sessions read only)"
    assert "quiz_attempts" not in tables_accessed, (
        "ended_at=None must early-exit before reading quiz_attempts; "
        f"tables accessed: {tables_accessed}"
    )
    assert "teachback_attempts" not in tables_accessed, (
        f"ended_at=None must early-exit before reading teachback_attempts; "
        f"tables accessed: {tables_accessed}"
    )
    assert "session_events" not in tables_accessed, (
        f"ended_at=None must early-exit before reading session_events; "
        f"tables accessed: {tables_accessed}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — No-quiz cognitive signal policy divergence
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_compute_signals_no_quiz_cognitive_policy_divergence() -> None:
    """AC6: no quiz rows → pattern=logical=0.0 (pessimistic) but processing_speed=50.0 (neutral).
    Documents intentional policy divergence — different no-data behaviour per dimension."""
    from app.modules.assessment.dna_fusion import _NEUTRAL, _compute_signals

    sigs = _compute_signals(quiz_rows=[], tb_rows=[], event_counts={})

    assert sigs["pattern_recognition"] == 0.0, (
        f"No quiz → pessimistic signal: pattern_recognition=0.0; got {sigs['pattern_recognition']}"
    )
    assert sigs["logical_deduction"] == 0.0, (
        f"No quiz → pessimistic signal: logical_deduction=0.0; got {sigs['logical_deduction']}"
    )
    assert sigs["processing_speed"] == pytest.approx(_NEUTRAL, rel=1e-3), (
        f"No response times → neutral signal: processing_speed={_NEUTRAL}; "
        f"got {sigs['processing_speed']}"
    )
    assert sigs["frustration_tolerance"] == pytest.approx(100.0, rel=1e-3), (
        f"0 interventions → frustration_tolerance=100.0; got {sigs['frustration_tolerance']}"
    )
    assert sigs["goal_orientation"] == pytest.approx(100.0, rel=1e-3), (
        f"0 skips → goal_orientation=100.0; got {sigs['goal_orientation']}"
    )
    assert sigs["curiosity_index"] == pytest.approx(0.0, abs=1e-3), (
        f"0 jargon_hover → curiosity_index=0.0; got {sigs['curiosity_index']}"
    )
    # P9: AC6 specifies 6 dims; L1 finding F1.1 — also assert the 3 remaining to catch
    # policy-unification bugs (e.g. accidentally making persistence pessimistic like cognitive dims)
    assert sigs["persistence"] == pytest.approx(_NEUTRAL, rel=1e-3), (
        f"No teachback → persistence=_NEUTRAL={_NEUTRAL}; got {sigs['persistence']}"
    )
    assert sigs["help_seeking"] == pytest.approx(0.0, abs=1e-3), (
        f"No help_seeking events → help_seeking=0.0; got {sigs['help_seeking']}"
    )
    assert sigs["study_independence"] == pytest.approx(100.0, rel=1e-3), (
        f"0 help_seeking → study_independence=100.0; got {sigs['study_independence']}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC7 — IDOR: session belonging to user_B raises 404 for user_A (SEC-006)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_fuse_learner_dna_idor_raises_404(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7: session.user_id != caller's user_id → HTTPException 404, not 403.
    403 would be an existence oracle for session IDs (SEC-006 pattern)."""
    from fastapi import HTTPException

    from app.modules.assessment.dna_fusion import fuse_learner_dna
    from app.config import Settings

    settings = Settings(
        supabase_url="http://x", supabase_anon_key="x",
        supabase_service_role_key="x", supabase_jwt_secret="x",
        openai_api_key="x", sarvam_api_key="x", heygen_api_key="x",
        langfuse_public_key="x", langfuse_secret_key="x",
    )

    # Session belongs to user_B, but we call with user_A
    session_row = {
        "session_id": _SESSION_UUID,
        "user_id": _USER_B_UUID,
        "ended_at": "2026-08-13T10:00:00",
    }
    # P1: dna_row must be populated so only the ownership check — not a missing-DNA 404 —
    # produces the 404. With dna_row=None the function could 404 before reaching the IDOR guard.
    supabase = _supabase_mock(
        session_row=session_row,
        quiz_rows=[],
        tb_rows=[],
        event_rows=[],
        dna_row=_base_dna_row(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await fuse_learner_dna(
            user_id=_USER_UUID,
            session_id=_SESSION_UUID,
            supabase=supabase,
            settings=settings,
        )

    assert exc_info.value.status_code == 404, (
        f"IDOR must return 404, not {exc_info.value.status_code}. "
        "A 403 reveals that the session exists — existence oracle (SEC-006)."
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC8 — Redis reassessment flag set at session 10
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_fuse_learner_dna_redis_reassessment_flag_at_session_10(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8: old_session_count=9 → new_count=10 → Redis set called with reassessment key.
    _REASSESSMENT_INTERVAL=10 was completely untested before T19."""
    from app.modules.assessment.dna_fusion import _REASSESSMENT_INTERVAL, fuse_learner_dna
    from app.config import Settings

    assert _REASSESSMENT_INTERVAL == 10, (
        f"Test assumes _REASSESSMENT_INTERVAL=10; actual={_REASSESSMENT_INTERVAL}. "
        "Update test if the constant is intentionally changed."
    )

    settings = Settings(
        supabase_url="http://x", supabase_anon_key="x",
        supabase_service_role_key="x", supabase_jwt_secret="x",
        openai_api_key="x", sarvam_api_key="x", heygen_api_key="x",
        langfuse_public_key="x", langfuse_secret_key="x",
    )

    dna_row = _base_dna_row(session_count=9)  # new_count will be 10
    supabase = _supabase_mock(
        session_row=_ended_session(),
        quiz_rows=[],
        tb_rows=[],
        event_rows=[],
        dna_row=dna_row,
    )

    mock_redis = AsyncMock()

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=settings,
        redis=mock_redis,
    )

    assert result is not None, "fuse_learner_dna should return 9 dims even at session 10"
    # P4: spec says "returns 9 dims" — assert exact key set, not just non-None
    assert set(result.keys()) == {
        "pattern_recognition", "logical_deduction", "processing_speed",
        "frustration_tolerance", "persistence", "help_seeking",
        "goal_orientation", "curiosity_index", "study_independence",
    }, f"Expected 9 dimension keys; got {set(result.keys())}"

    expected_key = f"user:{_USER_UUID}:reassessment_due"
    # P10: plain assert_called_once_with (no trailing comma-tuple — failure message was silently dropped)
    mock_redis.set.assert_called_once_with(expected_key, "1")

    # P3: verify periodic recurrence — session_count=19→20 also fires the flag.
    # Guards against `% _REASSESSMENT_INTERVAL` being refactored to `== _REASSESSMENT_INTERVAL`
    # (which would fire only at session 10; sessions 20, 30, 40 would silently never flag).
    dna_row_20 = _base_dna_row(session_count=19)
    supabase_20 = _supabase_mock(
        session_row=_ended_session(),
        quiz_rows=[],
        tb_rows=[],
        event_rows=[],
        dna_row=dna_row_20,
    )
    mock_redis_20 = AsyncMock()
    result_20 = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase_20,
        settings=settings,
        redis=mock_redis_20,
    )
    assert result_20 is not None
    mock_redis_20.set.assert_called_once_with(expected_key, "1")


# ══════════════════════════════════════════════════════════════════════════════
# AC9 — Redis failure is non-fatal: fusion returns result despite ConnectionError
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_fuse_learner_dna_redis_failure_is_non_fatal(
    mock_to_thread: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9: Redis.set raises ConnectionError at session 10 → function returns 9 dims.
    The try/except in Step 7 is correct but untested — a future refactor could re-raise."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna
    from app.config import Settings

    settings = Settings(
        supabase_url="http://x", supabase_anon_key="x",
        supabase_service_role_key="x", supabase_jwt_secret="x",
        openai_api_key="x", sarvam_api_key="x", heygen_api_key="x",
        langfuse_public_key="x", langfuse_secret_key="x",
    )

    dna_row = _base_dna_row(session_count=9)  # triggers reassessment path
    supabase = _supabase_mock(
        session_row=_ended_session(),
        quiz_rows=[],
        tb_rows=[],
        event_rows=[],
        dna_row=dna_row,
    )

    mock_redis = AsyncMock()
    mock_redis.set.side_effect = ConnectionError("Redis unavailable")

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=settings,
        redis=mock_redis,
    )

    assert result is not None, (
        "Redis ConnectionError in Step 7 must not propagate — fusion must return 9 dims"
    )
    assert set(result.keys()) == {
        "pattern_recognition", "logical_deduction", "processing_speed",
        "frustration_tolerance", "persistence", "help_seeking",
        "goal_orientation", "curiosity_index", "study_independence",
    }, f"Expected 9 dimension keys in result; got {set(result.keys())}"
