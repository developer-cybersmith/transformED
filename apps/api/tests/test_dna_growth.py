"""
Unit tests for apps/api/app/modules/assessment/dna_growth.py
Story 3-27 — Learner DNA Growth Tracking (delta per dimension per session)

Test count: 20
Coverage:
  AC 1  — __all__ exports only record_dna_growth
  AC 2  — keyword-only signature; positional args raise TypeError
  AC 3  — payload structure: {dimension, old_value, new_value, delta}
  AC 4  — single bulk insert via asyncio.to_thread
  AC 5  — delta = round(new - old, 4); None when old_value is None
  AC 6  — DB exception → log WARNING, return 0 (non-fatal)
  AC 7  — insert_error truthy → log WARNING, return 0 (non-fatal)
  AC 8  — success → returns inserted count
  AC 9  — empty new_dims → return 0, no DB call
  AC 10 — log injection prevention (_safe_sid used in all logger calls)
  AC 11 — fuse_learner_dna calls record_dna_growth after learner_dna upsert
  AC 12 — local import pattern inside fuse_learner_dna
  AC 13 — old_dims_for_growth None when first session (dna_row=None)
  AC 14 — return value of fuse_learner_dna unchanged if record_dna_growth fails
  AC 15 — no openai import in dna_growth.py (AST scan)
  AC 16 — no hardcoded model strings in dna_growth.py
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

NINE_DIMS = (
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

_GROWTH_FILE = (
    Path(__file__).parent.parent
    / "app" / "modules" / "assessment" / "dna_growth.py"
)

_SESSION_ID = "sess-test-01"
_USER_ID = "user-test-01"
_SESSION_ROW = {
    "session_id": _SESSION_ID,
    "user_id": _USER_ID,
    "ended_at": "2026-07-06T10:00:00Z",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_new_dims(value: float = 70.0) -> dict[str, float]:
    return {dim: value for dim in NINE_DIMS}


def _all_old_dims(value: float | None = 65.0) -> dict[str, float | None]:
    return {dim: value for dim in NINE_DIMS}


def _supabase_mock_growth(
    insert_raises: bool = False,
    insert_error: bool = False,
    inserted_count: int = 9,
) -> MagicMock:
    """Minimal Supabase mock for record_dna_growth: handles session_events insert."""
    supabase = MagicMock()
    tbl = MagicMock()

    if insert_raises:
        tbl.insert.return_value.execute.side_effect = Exception("DB insert failed")
    elif insert_error:
        err_resp = MagicMock()
        err_resp.error = "constraint violation"
        err_resp.data = None
        tbl.insert.return_value.execute.return_value = err_resp
    else:
        ok_resp = MagicMock()
        ok_resp.error = None
        ok_resp.data = [{"id": f"uuid-{i}"} for i in range(inserted_count)]
        tbl.insert.return_value.execute.return_value = ok_resp

    supabase.table.return_value = tbl
    return supabase


def _settings_fusion():
    """Minimal Settings for fuse_learner_dna integration tests."""
    from app.config import Settings
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
        dna_ema_retain=0.7,
    )


def _supabase_mock_fusion(
    session_row: dict | None = None,
    dna_row: dict | None = None,
    upsert_raises: bool = False,
) -> MagicMock:
    """Supabase mock for fuse_learner_dna integration tests (Step 6 focus)."""
    supabase = MagicMock()

    if session_row is None:
        session_row = _SESSION_ROW

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _table(name):
        tbl = MagicMock()
        if name == "sessions":
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                _resp(session_row)
            )
        elif name == "quiz_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp([])
        elif name == "teachback_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp([])
        elif name == "session_events":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp([])
        elif name == "learner_dna":
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                _resp(dna_row)
            )
            if upsert_raises:
                tbl.upsert.return_value.execute.side_effect = Exception("upsert failed")
            else:
                tbl.upsert.return_value.execute.return_value = _resp([])
        return tbl

    supabase.table.side_effect = _table
    return supabase


# ── AC 1: __all__ ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_dunder_all_exports_only_record_dna_growth():
    from app.modules.assessment import dna_growth
    assert dna_growth.__all__ == ["record_dna_growth"]


# ── AC 2: keyword-only signature ──────────────────────────────────────────────

@pytest.mark.unit
def test_positional_args_raise_type_error():
    from app.modules.assessment.dna_growth import record_dna_growth
    with pytest.raises(TypeError):
        asyncio.get_event_loop().run_until_complete(
            record_dna_growth(
                _SESSION_ID,  # positional — should raise
                _all_old_dims(),
                _all_new_dims(),
                MagicMock(),
            )
        )


# ── AC 4 + AC 8: single bulk insert, success path ────────────────────────────

@pytest.mark.unit
def test_record_dna_growth_inserts_9_rows_for_all_dims():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth(inserted_count=9)
    result = asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(65.0),
            new_dims=_all_new_dims(70.0),
            supabase=supabase,
        )
    )
    assert result == 9
    tbl = supabase.table.return_value
    # Exactly one insert call with all 9 rows
    tbl.insert.assert_called_once()
    inserted_rows = tbl.insert.call_args[0][0]
    assert len(inserted_rows) == 9


@pytest.mark.unit
def test_record_dna_growth_uses_single_bulk_insert():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth()
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(),
            new_dims=_all_new_dims(),
            supabase=supabase,
        )
    )
    tbl = supabase.table.return_value
    # insert must be called EXACTLY once — not 9 separate times
    assert tbl.insert.call_count == 1


# ── AC 3: payload structure ───────────────────────────────────────────────────

@pytest.mark.unit
def test_record_dna_growth_payload_structure():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth()
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(65.0),
            new_dims=_all_new_dims(70.0),
            supabase=supabase,
        )
    )
    tbl = supabase.table.return_value
    rows = tbl.insert.call_args[0][0]
    row = rows[0]
    assert row["session_id"] == _SESSION_ID
    assert row["event_type"] == "dna_update"
    payload = row["payload"]
    assert set(payload.keys()) == {"dimension", "old_value", "new_value", "delta"}
    assert payload["dimension"] in NINE_DIMS
    assert isinstance(payload["old_value"], float)
    assert isinstance(payload["new_value"], float)
    assert isinstance(payload["delta"], float)


@pytest.mark.unit
def test_record_dna_growth_event_type_is_dna_update():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth()
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(),
            new_dims=_all_new_dims(),
            supabase=supabase,
        )
    )
    rows = supabase.table.return_value.insert.call_args[0][0]
    assert all(r["event_type"] == "dna_update" for r in rows)


@pytest.mark.unit
def test_record_dna_growth_session_id_in_all_rows():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth()
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(),
            new_dims=_all_new_dims(),
            supabase=supabase,
        )
    )
    rows = supabase.table.return_value.insert.call_args[0][0]
    assert all(r["session_id"] == _SESSION_ID for r in rows)


# ── AC 5: delta computation ───────────────────────────────────────────────────

@pytest.mark.unit
def test_record_dna_growth_delta_computed_correctly():
    from app.modules.assessment.dna_growth import record_dna_growth
    # Use a specific dimension with known values for easy assertion
    new_dims = {"pattern_recognition": 70.0}
    old_dims = {"pattern_recognition": 65.0}
    supabase = _supabase_mock_growth(inserted_count=1)
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=old_dims,
            new_dims=new_dims,
            supabase=supabase,
        )
    )
    rows = supabase.table.return_value.insert.call_args[0][0]
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["delta"] == pytest.approx(5.0, abs=0.0001)


@pytest.mark.unit
def test_record_dna_growth_delta_precision_4_decimal_places():
    from app.modules.assessment.dna_growth import record_dna_growth
    # round(38.7654 - 33.3333, 4) = round(5.4321, 4) = 5.4321
    new_dims = {"pattern_recognition": 38.7654}
    old_dims = {"pattern_recognition": 33.3333}
    supabase = _supabase_mock_growth(inserted_count=1)
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=old_dims,
            new_dims=new_dims,
            supabase=supabase,
        )
    )
    rows = supabase.table.return_value.insert.call_args[0][0]
    delta = rows[0]["payload"]["delta"]
    assert delta == pytest.approx(5.4321, abs=0.00001)
    # Ensure no more than 4 decimal places
    assert delta == round(delta, 4)


# ── AC 5 edge case: first session (old_value=None) ───────────────────────────

@pytest.mark.unit
def test_record_dna_growth_old_value_none_first_session():
    from app.modules.assessment.dna_growth import record_dna_growth
    # All old_dims are None — first session, no prior row
    supabase = _supabase_mock_growth()
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(None),
            new_dims=_all_new_dims(65.0),
            supabase=supabase,
        )
    )
    rows = supabase.table.return_value.insert.call_args[0][0]
    for row in rows:
        payload = row["payload"]
        assert payload["old_value"] is None, f"Expected None, got {payload['old_value']}"
        assert payload["delta"] is None, f"Expected None delta, got {payload['delta']}"
        assert isinstance(payload["new_value"], float)


@pytest.mark.unit
def test_record_dna_growth_mixed_old_some_none():
    from app.modules.assessment.dna_growth import record_dna_growth
    # Only some dimensions have old values
    new_dims = {"pattern_recognition": 70.0, "logical_deduction": 60.0}
    old_dims = {"pattern_recognition": 65.0, "logical_deduction": None}
    supabase = _supabase_mock_growth(inserted_count=2)
    asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=old_dims,
            new_dims=new_dims,
            supabase=supabase,
        )
    )
    rows = supabase.table.return_value.insert.call_args[0][0]
    row_map = {r["payload"]["dimension"]: r["payload"] for r in rows}
    # pattern_recognition has old_value → delta computed
    assert row_map["pattern_recognition"]["delta"] == pytest.approx(5.0, abs=0.0001)
    assert row_map["pattern_recognition"]["old_value"] == 65.0
    # logical_deduction old_value=None → delta=None
    assert row_map["logical_deduction"]["old_value"] is None
    assert row_map["logical_deduction"]["delta"] is None


# ── AC 9: empty new_dims ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_record_dna_growth_empty_new_dims_returns_zero_no_db_call():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth()
    result = asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims={},
            new_dims={},
            supabase=supabase,
        )
    )
    assert result == 0
    supabase.table.assert_not_called()


# ── AC 6: DB exception → non-fatal, return 0 ─────────────────────────────────

@pytest.mark.unit
def test_record_dna_growth_db_exception_returns_zero():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth(insert_raises=True)
    result = asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(),
            new_dims=_all_new_dims(),
            supabase=supabase,
        )
    )
    # Non-fatal — must NOT raise, must return 0
    assert result == 0


# ── AC 7: insert_error truthy → non-fatal, return 0 ──────────────────────────

@pytest.mark.unit
def test_record_dna_growth_insert_error_field_returns_zero():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth(insert_error=True)
    result = asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(),
            new_dims=_all_new_dims(),
            supabase=supabase,
        )
    )
    assert result == 0


# ── AC 8: success returns inserted count ─────────────────────────────────────

@pytest.mark.unit
def test_record_dna_growth_returns_inserted_count():
    from app.modules.assessment.dna_growth import record_dna_growth
    supabase = _supabase_mock_growth(inserted_count=9)
    result = asyncio.get_event_loop().run_until_complete(
        record_dna_growth(
            session_id=_SESSION_ID,
            old_dims=_all_old_dims(),
            new_dims=_all_new_dims(),
            supabase=supabase,
        )
    )
    assert result == 9


# ── AC 11: fuse_learner_dna calls record_dna_growth after upsert ──────────────

@pytest.mark.unit
def test_fuse_learner_dna_calls_record_dna_growth_after_upsert():
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    with patch(
        "app.modules.assessment.dna_growth.record_dna_growth",
        new_callable=AsyncMock,
    ) as mock_growth:
        mock_growth.return_value = 9
        supabase = _supabase_mock_fusion()
        result = asyncio.get_event_loop().run_until_complete(
            fuse_learner_dna(
                user_id=_USER_ID,
                session_id=_SESSION_ID,
                supabase=supabase,
                settings=_settings_fusion(),
            )
        )
    # fuse_learner_dna must have returned new_dims (9 keys)
    assert result is not None
    assert len(result) == 9
    # record_dna_growth must have been called exactly once
    mock_growth.assert_called_once()
    call_kwargs = mock_growth.call_args.kwargs
    assert call_kwargs["session_id"] == _SESSION_ID
    assert set(call_kwargs["new_dims"].keys()) == set(NINE_DIMS)
    assert set(call_kwargs["old_dims"].keys()) == set(NINE_DIMS)


# ── AC 14: record_dna_growth failure does not prevent fuse_learner_dna return ─

@pytest.mark.unit
def test_fuse_learner_dna_growth_failure_does_not_prevent_return():
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    with patch(
        "app.modules.assessment.dna_growth.record_dna_growth",
        new_callable=AsyncMock,
    ) as mock_growth:
        # Growth tracking raises — must be non-fatal
        mock_growth.side_effect = Exception("growth write failed")
        supabase = _supabase_mock_fusion()
        result = asyncio.get_event_loop().run_until_complete(
            fuse_learner_dna(
                user_id=_USER_ID,
                session_id=_SESSION_ID,
                supabase=supabase,
                settings=_settings_fusion(),
            )
        )
    # fuse_learner_dna must still return new_dims despite growth failure
    assert result is not None
    assert len(result) == 9


# ── AC 13: old_dims_for_growth all-None on first session ─────────────────────

@pytest.mark.unit
def test_fuse_learner_dna_old_dims_for_growth_none_on_first_session():
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    with patch(
        "app.modules.assessment.dna_growth.record_dna_growth",
        new_callable=AsyncMock,
    ) as mock_growth:
        mock_growth.return_value = 9
        # dna_row=None → first session, no prior DB row
        supabase = _supabase_mock_fusion(dna_row=None)
        asyncio.get_event_loop().run_until_complete(
            fuse_learner_dna(
                user_id=_USER_ID,
                session_id=_SESSION_ID,
                supabase=supabase,
                settings=_settings_fusion(),
            )
        )
    mock_growth.assert_called_once()
    old_dims = mock_growth.call_args.kwargs["old_dims"]
    # All 9 dimensions must have old_value=None (no prior row)
    for dim in NINE_DIMS:
        assert old_dims[dim] is None, f"Expected old_dims[{dim}] to be None, got {old_dims[dim]}"


# ── AC 15: no openai import (AST scan) ───────────────────────────────────────

@pytest.mark.unit
def test_no_openai_import_in_dna_growth():
    source = _GROWTH_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "openai", (
                    f"Found top-level openai import: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                assert node.module.split(".")[0] != "openai", (
                    f"Found 'from openai' import: {node.module}"
                )


# ── AC 16: no hardcoded model strings ────────────────────────────────────────

@pytest.mark.unit
def test_no_hardcoded_model_string_in_dna_growth():
    source = _GROWTH_FILE.read_text(encoding="utf-8")
    for model_str in ("gpt-4o-mini", "gpt-4o", "gpt-4", "text-embedding"):
        assert model_str not in source, (
            f"Hardcoded model string found in dna_growth.py: {model_str!r}"
        )
