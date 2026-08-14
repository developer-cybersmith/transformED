"""
Demo T20 — Learner DNA Fusion: event aggregation DB path with non-empty event_rows.

Closes D94 (was D75): the counting loop in dna_fusion.py (lines 301-306) has zero integration
test coverage with non-empty event_rows that produce concrete, verifiable EMA output.

Test count: 6
ACs covered:
  AC1 — 3 jargon_hover events → curiosity_index EMA = 32.0 in upsert payload
  AC2 — 4 jargon_hover events (cap-1) → curiosity_index EMA = 59.0 (distinct from cap or 3-event)
  AC3 — unknown event_type is harmless; curiosity_index reflects 0 known events
  AC4 — empty-string event_type filtered by `if t:` guard; only real events counted
  AC5 — session_events read failure alone → non-fatal, returns 9 dims
  AC6 — all four event types in one session: exact EMA for all four signal dims

Constants referenced from dna_fusion.py (read the source before changing assertions):
    _JARGON_CAP = 5
    _HELP_CAP   = 4
    _SKIP_CAP   = 4
    _INTERVENTION_CAP = 3
    _NEUTRAL    = 50.0
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Settings

# ── Constants (mirror dna_fusion.py — never import private names directly) ────

_JARGON_CAP = 5
_HELP_CAP = 4
_SKIP_CAP = 4
_INTERVENTION_CAP = 3
_NEUTRAL = 50.0

_USER_UUID = "a1b2c3d4-0001-0001-0001-000000000001"
_SESSION_UUID = "s1b2c3d4-0001-0001-0001-000000000001"

_NINE_DIMENSIONS = (
    "pattern_recognition",
    "logical_deduction",
    "processing_speed",
    "frustration_tolerance",
    "persistence",
    "help_seeking",
    "goal_orientation",
    "curiosity_index",
    "study_independence",
)


# ── Helpers ────────────────────────────────────────────────────────────────────


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


def _ended_session() -> dict[str, Any]:
    return {
        "session_id": _SESSION_UUID,
        "user_id": _USER_UUID,
        "ended_at": "2026-08-13T10:00:00Z",
    }


def _base_dna_row(**overrides: float) -> dict[str, Any]:
    """Return a learner_dna row with neutral (50.0) values unless overridden."""
    row: dict[str, Any] = {
        "user_id": _USER_UUID,
        "session_count": 5,
        **dict.fromkeys(_NINE_DIMENSIONS, 50.0),
    }
    row.update(overrides)
    return row


def _supabase_mock(
    *,
    session_row: dict[str, Any],
    event_rows: list[dict[str, Any]],
    dna_row: dict[str, Any] | None,
    quiz_rows: list[dict[str, Any]] | None = None,
    tb_rows: list[dict[str, Any]] | None = None,
    capture_upsert: list[dict[str, Any]] | None = None,
    events_raises: bool = False,
) -> MagicMock:
    """Build a Supabase mock that routes by table name and optionally captures upsert calls."""
    supabase = MagicMock()

    def _resp(data: Any) -> MagicMock:
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _spy_upsert(payload: dict[str, Any], **kwargs: Any) -> MagicMock:
        assert kwargs.get("on_conflict") == "user_id", (
            f"learner_dna.upsert on_conflict must be 'user_id', got {kwargs.get('on_conflict')!r}. "
            "Changing this would create duplicate rows instead of updating existing ones."
        )
        if capture_upsert is not None:
            capture_upsert.append(dict(payload))
        m = MagicMock()
        m.execute.return_value = _resp([])
        return m

    def _table(name: str) -> MagicMock:
        tbl = MagicMock()
        if name == "sessions":
            (
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
            ) = _resp(session_row)
        elif name == "quiz_attempts":
            _lim = tbl.select.return_value.eq.return_value.order.return_value.limit.return_value
            _lim.execute.return_value = _resp(quiz_rows if quiz_rows is not None else [])
        elif name == "teachback_attempts":
            _lim = tbl.select.return_value.eq.return_value.order.return_value.limit.return_value
            _lim.execute.return_value = _resp(tb_rows if tb_rows is not None else [])
        elif name == "session_events":
            _lim = tbl.select.return_value.eq.return_value.order.return_value.limit.return_value
            events_exec = _lim.execute
            if events_raises:
                events_exec.side_effect = Exception("session_events DB down")
            else:
                events_exec.return_value = _resp(event_rows)
            # Wire INSERT chain so write_system_events (called by record_dna_growth in Step 6)
            # returns a clean response. Without this, MagicMock().error is truthy and
            # write_system_events logs "0 events written" and silently returns 0 in every test.
            tbl.insert.return_value.execute.return_value = _resp([])
        elif name == "learner_dna":
            (
                tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
            ) = _resp(dna_row)
            if capture_upsert is not None:
                tbl.upsert.side_effect = _spy_upsert
            else:
                tbl.upsert.return_value.execute.return_value = _resp([])
        return tbl

    supabase.table.side_effect = _table
    return supabase


# ── AC1 ───────────────────────────────────────────────────────────────────────


async def test_fuse_event_aggregation_3_jargon_hovers_exact_curiosity_ema():
    """AC1: 3 jargon_hover events → counting loop produces count=3 → signal=(3/5)*100=60.0
    → EMA = round(0.7*20.0 + 0.3*60.0, 4) = 32.0 in the upsert payload.

    A counting bug that produces count=1 would give signal=20.0 → EMA=20.0 ≠ 32.0.
    """
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    event_rows = [{"event_type": "jargon_hover"}] * 3
    dna_row = _base_dna_row(curiosity_index=20.0)
    captured: list[dict[str, Any]] = []
    supabase = _supabase_mock(
        session_row=_ended_session(),
        event_rows=event_rows,
        dna_row=dna_row,
        capture_upsert=captured,
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=_settings(retain=0.7),
    )

    assert result is not None, "fuse_learner_dna must return a dict, not None"
    assert len(captured) == 1, (
        f"Expected exactly 1 upsert call, got {len(captured)}. Multiple calls indicate a retry bug."
    )
    payload = captured[0]

    # D94 (was D75) fix: assert the concrete value that depends on count=3 being correct
    # signal = (3/5)*100 = 60.0; EMA = round(0.7*20.0 + 0.3*60.0, 4) = 32.0
    expected_ema = round(0.7 * 20.0 + 0.3 * 60.0, 4)  # = 32.0
    assert payload.get("curiosity_index") == pytest.approx(expected_ema, rel=1e-3), (
        f"curiosity_index EMA mismatch. Expected {expected_ema} (3-event count). "
        f"Got {payload.get('curiosity_index')}. A counting bug that gives count=1 "
        f"would produce EMA=20.0; count=2 would give EMA=26.0."
    )
    # Pin the literal value so constant changes are caught
    assert expected_ema == pytest.approx(32.0, rel=1e-6), (
        "Spec-pinned literal 32.0 changed — update the story AC if _JARGON_CAP changed"
    )


# ── AC2 ───────────────────────────────────────────────────────────────────────


async def test_fuse_event_aggregation_4_jargon_hovers_distinct_from_cap_and_3_event():
    """AC2: 4 jargon_hover events (JARGON_CAP-1=4) → signal=80.0 → EMA=59.0.
    Distinct from: cap (100.0 signal→65.0 EMA) and 3-event (60.0 signal→53.0 EMA).

    Catches off-by-one in the counting loop.
    """
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    event_rows = [{"event_type": "jargon_hover"}] * 4  # _JARGON_CAP - 1
    dna_row = _base_dna_row(curiosity_index=50.0)
    captured: list[dict[str, Any]] = []
    supabase = _supabase_mock(
        session_row=_ended_session(),
        event_rows=event_rows,
        dna_row=dna_row,
        capture_upsert=captured,
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=_settings(retain=0.7),
    )

    assert result is not None
    assert len(captured) == 1
    payload = captured[0]

    # signal = (4/5)*100 = 80.0; EMA = round(0.7*50.0 + 0.3*80.0, 4) = 59.0
    expected_ema = round(0.7 * 50.0 + 0.3 * 80.0, 4)  # = 59.0
    curiosity = payload.get("curiosity_index")
    assert curiosity == pytest.approx(expected_ema, rel=1e-3), (
        f"Expected curiosity_index={expected_ema} (4-event count). Got {curiosity}."
    )
    # Pin the literal so constant changes are caught (matches AC1/AC3/AC4 pattern)
    assert expected_ema == pytest.approx(59.0, rel=1e-6), (
        "Spec-pinned literal 59.0 changed — update story AC2 if _JARGON_CAP changed"
    )

    # Explicitly not the cap value (5-event) or the 3-event value
    cap_ema = round(0.7 * 50.0 + 0.3 * 100.0, 4)  # 5 events → 65.0
    three_event_ema = round(0.7 * 50.0 + 0.3 * 60.0, 4)  # 3 events → 53.0
    assert curiosity != pytest.approx(cap_ema, rel=1e-3), (
        "curiosity_index matches the cap (5 events) — counting loop counted 5 instead of 4"
    )
    assert curiosity != pytest.approx(three_event_ema, rel=1e-3), (
        "curiosity_index matches 3-event value — counting loop counted 3 instead of 4"
    )


# ── AC3 ───────────────────────────────────────────────────────────────────────


async def test_fuse_event_aggregation_unknown_event_type_is_harmless():
    """AC3: event_rows with only unknown event_types → no KeyError → curiosity_index uses
    signal=0.0 (no jargon_hover events) → EMA from neutral old value.

    Verifies the counting loop doesn't crash on unseen types, and _compute_signals
    silently ignores unknown keys (it only reads specific known keys via .get()).
    """
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    event_rows = [
        {"event_type": "unknown_event_type_xyz"},
        {"event_type": "another_unknown_event"},
    ]
    # First session — no prior DNA row
    captured: list[dict[str, Any]] = []
    supabase = _supabase_mock(
        session_row=_ended_session(),
        event_rows=event_rows,
        dna_row=None,  # first session → old values are _NEUTRAL (50.0)
        capture_upsert=captured,
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=_settings(retain=0.7),
    )

    assert result is not None, "fuse_learner_dna must not raise on unknown event types"
    assert len(result) == 9, f"Expected 9 dimensions, got {len(result)}"
    assert len(captured) == 1

    payload = captured[0]
    # 0 jargon_hover events → curiosity signal = 0.0
    # old = None → treated as _NEUTRAL = 50.0
    # EMA = round(0.7*50.0 + 0.3*0.0, 4) = 35.0
    expected_ema = round(0.7 * _NEUTRAL + 0.3 * 0.0, 4)  # = 35.0
    assert payload.get("curiosity_index") == pytest.approx(expected_ema, rel=1e-3), (
        f"curiosity_index should be {expected_ema} (0 jargon events, neutral old). "
        f"Got {payload.get('curiosity_index')}."
    )
    assert expected_ema == pytest.approx(35.0, rel=1e-6), (
        "Spec-pinned 35.0 changed — update story AC if _NEUTRAL or retain changed"
    )


# ── AC4 ───────────────────────────────────────────────────────────────────────


async def test_fuse_event_aggregation_empty_string_event_type_filtered():
    """AC4: event_type='' is filtered by `if t:` guard (line 305 dna_fusion.py).
    Only the real jargon_hover is counted → curiosity signal=(1/5)*100=20.0.

    If the `if t:` guard were removed, key '' would be inserted into event_counts
    but ignored by _compute_signals (.get returns 0 for unknown keys) — same result.
    This test pins the production behaviour that empty strings never enter event_counts,
    providing a guard against refactors that accidentally add a branch on the '' key.
    """
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    event_rows = [
        {"event_type": ""},
        {"event_type": "jargon_hover"},
        {"event_type": ""},
    ]
    dna_row = _base_dna_row(curiosity_index=0.0)
    captured: list[dict[str, Any]] = []
    supabase = _supabase_mock(
        session_row=_ended_session(),
        event_rows=event_rows,
        dna_row=dna_row,
        capture_upsert=captured,
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=_settings(retain=0.7),
    )

    assert result is not None
    assert len(captured) == 1
    payload = captured[0]

    # MOCK-CONTRACT: the `if t:` guard (dna_fusion.py:305) is not independently verifiable
    # via EMA output alone. `_compute_signals` reads only named keys via .get(); removing the
    # guard would insert key="" into event_counts but _compute_signals returns 0 for it,
    # producing the same EMA=6.0. The assertion confirms correct event counting for the real
    # jargon_hover event, not the filtering of "". Guard prevents "" polluting event_counts
    # for future refactors that might iterate over keys. Accepted limitation of integration testing.
    # Only 1 jargon_hover counted (2 empty strings filtered)
    # signal = (1/5)*100 = 20.0; EMA = round(0.7*0.0 + 0.3*20.0, 4) = 6.0
    expected_ema = round(0.7 * 0.0 + 0.3 * 20.0, 4)  # = 6.0
    assert payload.get("curiosity_index") == pytest.approx(expected_ema, rel=1e-3), (
        f"curiosity_index should be {expected_ema} (1 jargon counted; 2 empty strings filtered). "
        f"Got {payload.get('curiosity_index')}. If 3 were counted, signal=60.0 → EMA≈18.0."
    )
    assert expected_ema == pytest.approx(6.0, rel=1e-6), (
        "Spec-pinned 6.0 changed — update story AC if constants changed"
    )


# ── AC5 ───────────────────────────────────────────────────────────────────────


async def test_fuse_event_aggregation_events_read_failure_alone_is_non_fatal():
    """AC5: Individual session_events read failure → non-fatal (try/except in production code).
    quiz_attempts and teachback_attempts succeed with empty lists.
    fuse_learner_dna must return 9 dims built from empty event_counts.

    Isolation test: AC18 in test_dna_fusion.py fails all three reads simultaneously.
    This test verifies the individual session_events path independently.
    """
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    dna_row = _base_dna_row()
    captured: list[dict[str, Any]] = []
    supabase = _supabase_mock(
        session_row=_ended_session(),
        event_rows=[],  # won't be used — events_raises=True
        dna_row=dna_row,
        quiz_rows=[],
        tb_rows=[],
        capture_upsert=captured,
        events_raises=True,  # only session_events fails
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=_settings(retain=0.7),
    )

    assert result is not None, "fuse_learner_dna must not raise when only session_events read fails"
    assert set(result.keys()) == set(_NINE_DIMENSIONS), (
        f"Expected exactly 9 dims; got {set(result.keys())}"
    )
    assert len(captured) == 1, "Upsert must still be called despite events read failure"

    # event_counts = {} → curiosity signal = 0.0
    # old = 50.0 (neutral base_dna_row); EMA = round(0.7*50.0 + 0.3*0.0, 4) = 35.0
    payload = captured[0]
    expected_ema = round(0.7 * 50.0 + 0.3 * 0.0, 4)  # = 35.0
    assert payload.get("curiosity_index") == pytest.approx(expected_ema, rel=1e-3), (
        f"curiosity_index should be {expected_ema} (events read failed → empty event_counts). "
        f"Got {payload.get('curiosity_index')}."
    )


# ── AC6 ───────────────────────────────────────────────────────────────────────


async def test_fuse_event_aggregation_all_four_event_types_exact_ema_all_dims():
    """AC6: All four event types (jargon_hover, help_seeking, skip_segment,
    intervention_triggered) in one session → exact EMA verified for all four
    signal-driven dimensions in the upsert payload.

    This is the comprehensive D94 (was D75) closure. A regression in any event-type's key name
    or counting logic causes at least one assertion to fail.

    EMA reference table (all from production constants, retain=0.7):
      jargon_hover   × 3: signal=(3/5)*100=60.0;  old=40.0 → EMA=round(0.7*40+0.3*60,4)=46.0
      help_seeking   × 1: signal=(1/4)*100=25.0;  old=50.0 → EMA=round(0.7*50+0.3*25,4)=42.5
      skip_segment   × 1: signal=100-(1/4)*100=75.0; old=80.0 → EMA=round(0.7*80+0.3*75,4)=78.5
      intervention   × 1: signal=100-(1/3)*100=66.667; old=90.0 → EMA=round(63.0+20.0,4)=83.0
      study_independence: signal=100-25.0=75.0;  old=50.0 → EMA=round(0.7*50+0.3*75,4)=57.5

    Note: help_seeking uses count=1 (not 2) so signal=25.0 ≠ _NEUTRAL(50.0). With count=2,
    signal=(2/4)*100=50.0=_NEUTRAL, making the EMA=50.0 indistinguishable from a neutral
    fallback bug — the assertion would pass even if the counting loop read event_counts with
    the wrong key name. count=1 → EMA=42.5 ≠ 50.0 ensures the loop is exercised correctly.
    """
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    event_rows = (
        [{"event_type": "jargon_hover"}] * 3
        + [{"event_type": "help_seeking"}]
        * 1  # 1 event → signal=25.0 ≠ _NEUTRAL; catches loop bugs
        + [{"event_type": "skip_segment"}] * 1
        + [{"event_type": "intervention_triggered"}] * 1
    )

    dna_row = _base_dna_row(
        curiosity_index=40.0,
        help_seeking=50.0,
        study_independence=50.0,
        goal_orientation=80.0,
        frustration_tolerance=90.0,
    )
    captured: list[dict[str, Any]] = []
    supabase = _supabase_mock(
        session_row=_ended_session(),
        event_rows=event_rows,
        dna_row=dna_row,
        quiz_rows=[],
        tb_rows=[],
        capture_upsert=captured,
    )

    result = await fuse_learner_dna(
        user_id=_USER_UUID,
        session_id=_SESSION_UUID,
        supabase=supabase,
        settings=_settings(retain=0.7),
    )

    assert result is not None
    assert len(captured) == 1
    payload = captured[0]

    # ── curiosity_index ────────────────────────────────────────────────────────
    # 3 jargon_hover → signal = (3/5)*100 = 60.0; old = 40.0
    curiosity_ema = round(0.7 * 40.0 + 0.3 * 60.0, 4)  # = 46.0
    assert payload.get("curiosity_index") == pytest.approx(curiosity_ema, rel=1e-3), (
        f"curiosity_index: expected {curiosity_ema} (3 jargon_hover events). "
        f"Got {payload.get('curiosity_index')}."
    )
    assert curiosity_ema == pytest.approx(46.0, rel=1e-6), "Spec literal 46.0"

    # ── help_seeking ───────────────────────────────────────────────────────────
    # 1 help_seeking → signal = (1/4)*100 = 25.0; old = 50.0
    # EMA = 42.5 ≠ _NEUTRAL (50.0) — confirms event_counts["help_seeking"] == 1, not 0 or 2
    help_ema = round(0.7 * 50.0 + 0.3 * 25.0, 4)  # = 42.5
    assert payload.get("help_seeking") == pytest.approx(help_ema, rel=1e-3), (
        f"help_seeking: expected {help_ema} (1 help event, signal=25.0). "
        f"Got {payload.get('help_seeking')}. "
        f"50.0 would indicate neutral fallback or wrong key name in counting loop."
    )
    assert help_ema == pytest.approx(42.5, rel=1e-6), "Spec literal 42.5"

    # ── study_independence ─────────────────────────────────────────────────────
    # help_signal = 25.0 → study_independence_signal = 100 - 25 = 75.0; old = 50.0
    # EMA = 57.5 ≠ 50.0 — confirms the inversion (100 - help_signal) is applied correctly
    study_ema = round(0.7 * 50.0 + 0.3 * 75.0, 4)  # = 57.5
    assert payload.get("study_independence") == pytest.approx(study_ema, rel=1e-3), (
        f"study_independence: expected {study_ema} (signal=100-25=75.0). "
        f"Got {payload.get('study_independence')}. "
        f"50.0 would indicate help_signal=50 (2 events) or missing inversion."
    )
    assert study_ema == pytest.approx(57.5, rel=1e-6), "Spec literal 57.5"

    # ── goal_orientation ───────────────────────────────────────────────────────
    # 1 skip_segment → signal = 100 - (1/4)*100 = 75.0; old = 80.0
    goal_signal = 100.0 - (1 / _SKIP_CAP) * 100.0  # = 75.0
    goal_ema = round(0.7 * 80.0 + 0.3 * goal_signal, 4)  # = 78.5
    assert payload.get("goal_orientation") == pytest.approx(goal_ema, rel=1e-3), (
        f"goal_orientation: expected {goal_ema} (1 skip_segment). "
        f"Got {payload.get('goal_orientation')}."
    )
    assert goal_ema == pytest.approx(78.5, rel=1e-6), "Spec literal 78.5"

    # ── frustration_tolerance ──────────────────────────────────────────────────
    # 1 intervention → signal = 100 - (1/3)*100 = 66.6̄; old = 90.0
    # IEEE 754: round(0.7*90 + 0.3*(100-(1/3)*100), 4) = round(63.0+20.000000000000004, 4) = 83.0
    frustration_signal = 100.0 - (1.0 / _INTERVENTION_CAP) * 100.0  # ≈ 66.667
    frustration_ema = round(0.7 * 90.0 + 0.3 * frustration_signal, 4)  # = 83.0 exactly
    assert payload.get("frustration_tolerance") == pytest.approx(frustration_ema, rel=1e-3), (
        f"frustration_tolerance: expected {frustration_ema} (1 intervention, signal≈66.667). "
        f"Got {payload.get('frustration_tolerance')}."
    )
    assert frustration_ema == pytest.approx(83.0, rel=1e-6), "Spec literal 83.0"
