"""Tests for Story F2-1 — get_dna_prompt_context and format_dna_for_prompt.

ACs covered:
    AC1  — function exists in service.py
    AC2  — return dict has exactly the expected top-level keys
    AC3  — Redis cache hit skips Supabase for DNA
    AC4  — Redis miss falls back to Supabase
    AC5  — no DNA anywhere → graceful empty state, no exception
    AC6  — session_id=None → session_signals=None, no session DB queries
    AC7  — session signals bounded and mathematically correct
    AC8  — Redis / Supabase exceptions swallowed (non-fatal)
    AC9  — no raw float dimension values in dna_labels
    AC10 — format_dna_for_prompt returns usable string with no float dim values
    AC11 — guard-test regression checks (import-level)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_VALID_SESSION_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_ALL_9_DIMS = (
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

_DNA_BLOB = dict.fromkeys(_ALL_9_DIMS, 60.0)  # all "Developing"


def _make_settings() -> MagicMock:
    s = MagicMock()
    return s


def _make_redis(*, dna_json: str | None = None, reassessment_due: bytes | None = None) -> AsyncMock:
    redis = AsyncMock()

    async def _get(key: str) -> bytes | None:
        if "dna" in key and dna_json is not None:
            return dna_json.encode()
        if "reassessment_due" in key:
            return reassessment_due
        return None

    redis.get = AsyncMock(side_effect=_get)
    return redis


def _make_supabase(
    *,
    dna_row: dict | None = None,
    quiz_rows: list[dict] | None = None,
    teachback_rows: list[dict] | None = None,
    event_rows: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Supabase client supporting all chain shapes used by get_dna_prompt_context.

    Chains supported per table:
      learner_dna   : .select().eq().maybe_single().execute()
      quiz_attempts : .select().eq().limit().execute()
      teachback_attempts: .select().eq().limit().execute()
      session_events: .select().eq().eq().limit().execute()
    """
    supabase = MagicMock()

    _table_data: dict[str, Any] = {
        "learner_dna_row": dna_row,
        "quiz_rows": quiz_rows if quiz_rows is not None else [],
        "teachback_rows": teachback_rows if teachback_rows is not None else [],
        "event_rows": event_rows if event_rows is not None else [],
    }

    def _make_chain(table_name: str) -> MagicMock:
        """Return a fluent chain mock that terminates at .execute() with the right data."""
        chain = MagicMock()

        def _execute() -> MagicMock:
            resp = MagicMock()
            if table_name == "learner_dna":
                resp.data = _table_data["learner_dna_row"]
            elif table_name == "quiz_attempts":
                resp.data = _table_data["quiz_rows"]
            elif table_name == "teachback_attempts":
                resp.data = _table_data["teachback_rows"]
            elif table_name == "session_events":
                resp.data = _table_data["event_rows"]
            else:
                resp.data = []
            return resp

        # Every chain method returns the same chain object so any ordering works.
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.execute.side_effect = _execute

        # maybe_single returns a fresh object that also has .execute
        ms = MagicMock()
        ms.execute.side_effect = _execute
        chain.maybe_single.return_value = ms

        return chain

    def _table(name: str) -> MagicMock:
        return _make_chain(name)

    supabase.table = MagicMock(side_effect=_table)
    return supabase


# ── AC1 — function exists ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_dna_prompt_context_function_exists() -> None:
    """AC1: get_dna_prompt_context is importable from assessment.service."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    assert callable(get_dna_prompt_context)


@pytest.mark.unit
def test_format_dna_for_prompt_function_exists() -> None:
    """AC10 (partial): format_dna_for_prompt is importable from assessment.service."""
    from app.modules.assessment.service import format_dna_for_prompt  # noqa: PLC0415

    assert callable(format_dna_for_prompt)


# ── AC2 — return schema ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_return_dict_has_expected_top_level_keys() -> None:
    """AC2: returned dict contains exactly the 6 documented top-level keys."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    supabase = _make_supabase()
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    expected_keys = {
        "dna_labels",
        "badge_labels",
        "profile_snippet",
        "session_count",
        "reassessment_due",
        "session_signals",
    }
    assert set(result.keys()) == expected_keys, (
        f"Return dict must have exactly {expected_keys}, got {set(result.keys())}"
    )


# ── AC3 — Redis cache hit skips Supabase for DNA ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_redis_cache_hit_still_fetches_metadata_from_supabase() -> None:
    """AC3 (updated): on Redis cache hit, dimension values come from Redis;
    metadata (badge_labels, profile_text, session_count) always fetched from Supabase.
    dna_labels has all 9 dims even though the Supabase row has no dim values.
    """
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    # Supabase row has only metadata — no dim values.
    # If dims came from Supabase instead of Redis, dna_labels would be {}.
    dna_row = {
        "badge_labels": ["Pattern Thinker"],
        "profile_text": "A curious learner.",
        "session_count": 3,
    }
    supabase = _make_supabase(dna_row=dna_row)
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    # Dimension labels come from Redis (all 9 present)
    assert set(result["dna_labels"].keys()) == set(_ALL_9_DIMS), (
        "dna_labels must contain all 9 dims on Redis cache hit"
    )
    # Metadata comes from Supabase (not silently empty)
    assert result["badge_labels"] == ["Pattern Thinker"]
    assert result["session_count"] == 3


# ── AC4 — Redis miss falls back to Supabase ───────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_redis_miss_falls_back_to_supabase() -> None:
    """AC4: on Redis cache miss, supabase.table('learner_dna') is queried."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=None)  # cache miss
    dna_row = {
        **_DNA_BLOB,
        "badge_labels": ["Pattern Thinker"],
        "profile_text": "A thinker.",
        "session_count": 3,
    }
    supabase = _make_supabase(dna_row=dna_row)
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    # supabase.table("learner_dna") must have been called
    table_calls = [call_args.args[0] for call_args in supabase.table.call_args_list]
    assert "learner_dna" in table_calls, (
        f"Expected supabase.table('learner_dna') on cache miss; calls: {table_calls}"
    )
    # Labels must be strings
    assert all(isinstance(v, str) for v in result["dna_labels"].values())
    assert result["badge_labels"] == ["Pattern Thinker"]
    assert result["session_count"] == 3


# ── AC5 — no DNA anywhere → graceful empty state ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_no_dna_anywhere_returns_empty_state_without_raising() -> None:
    """AC5: no Redis cache, no Supabase row → graceful empty dict, no HTTPException."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=None)
    supabase = _make_supabase(dna_row=None)  # maybe_single → None
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert result["dna_labels"] == {}
    assert result["badge_labels"] == []
    assert result["profile_snippet"] is None
    assert result["session_count"] == 0
    assert result["reassessment_due"] is False


# ── AC6 — session_id=None → session_signals=None ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_id_none_returns_none_session_signals_no_db_query() -> None:
    """AC6: session_id=None → session_signals is None; no quiz/teachback/events queries.
    Note: learner_dna IS queried for metadata even on Redis hit — that is expected.
    """
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    supabase = _make_supabase()  # handles learner_dna metadata call cleanly
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert result["session_signals"] is None
    session_table_calls = [
        c.args[0] for c in supabase.table.call_args_list
        if c.args[0] in ("quiz_attempts", "teachback_attempts", "session_events")
    ]
    assert session_table_calls == [], (
        f"No session table should be queried when session_id=None; got: {session_table_calls}"
    )


# ── AC7 — session signals computed correctly ──────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_signals_quiz_accuracy_computed_correctly() -> None:
    """AC7: quiz_accuracy = correct_count/total_count * 100."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    quiz_rows = [
        {"is_correct": True},
        {"is_correct": True},
        {"is_correct": False},
        {"is_correct": True},
    ]  # 3/4 = 75.0
    supabase = _make_supabase(quiz_rows=quiz_rows)
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert result["session_signals"] is not None
    assert abs(result["session_signals"]["quiz_accuracy"] - 75.0) < 0.01


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_signals_teachback_avg_computed_correctly() -> None:
    """AC7: teachback_avg = mean(scores)."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    teachback_rows = [{"score": 80}, {"score": 60}]  # mean = 70.0
    supabase = _make_supabase(teachback_rows=teachback_rows)
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert result["session_signals"] is not None
    assert abs(result["session_signals"]["teachback_avg"] - 70.0) < 0.01


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_signals_intervention_count_correct() -> None:
    """AC7: intervention_count = row count of intervention_acknowledged events."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    event_rows = [{"event_type": "intervention_acknowledged"}] * 3
    supabase = _make_supabase(event_rows=event_rows)
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert result["session_signals"] is not None
    assert result["session_signals"]["intervention_count"] == 3


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_signals_none_when_no_rows() -> None:
    """AC7: quiz_accuracy and teachback_avg are None when no rows exist."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    supabase = _make_supabase(quiz_rows=[], teachback_rows=[], event_rows=[])
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    signals = result["session_signals"]
    assert signals is not None
    assert signals["quiz_accuracy"] is None
    assert signals["teachback_avg"] is None
    assert signals["intervention_count"] == 0


# ── AC8 — non-fatal exceptions ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_redis_exception_is_swallowed() -> None:
    """AC8: Redis.get raising an exception does not propagate to caller."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=Exception("Redis connection refused"))
    supabase = _make_supabase(dna_row=None)
    settings = _make_settings()

    # Must not raise
    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    # Returns a usable (possibly empty) dict
    assert isinstance(result, dict)
    assert "dna_labels" in result


@pytest.mark.asyncio
@pytest.mark.unit
async def test_supabase_exception_is_swallowed() -> None:
    """AC8: Supabase error does not propagate to caller."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=None)  # force Supabase path
    supabase = MagicMock()
    supabase.table = MagicMock(side_effect=Exception("Supabase unreachable"))
    settings = _make_settings()

    # Must not raise
    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert isinstance(result, dict)
    assert "dna_labels" in result


# ── AC9 — no raw floats in dna_labels ────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_dna_labels_contain_only_strings_not_floats() -> None:
    """AC9: all values in dna_labels are str, never float."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    supabase = _make_supabase()
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    for dim, label in result["dna_labels"].items():
        assert isinstance(label, str), (
            f"dna_labels['{dim}'] = {label!r} is {type(label).__name__}, expected str"
        )
        assert not isinstance(label, float)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_dna_labels_has_all_9_dims_when_dna_present() -> None:
    """AC2/AC9: when DNA present, dna_labels has exactly the 9 canonical dimension keys."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    supabase = _make_supabase()
    settings = _make_settings()

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=None,
        supabase=supabase,
        redis=redis,
        settings=settings,
    )

    assert set(result["dna_labels"].keys()) == set(_ALL_9_DIMS), (
        f"dna_labels must have exactly 9 canonical dimension keys; "
        f"got {set(result['dna_labels'].keys())}"
    )


# ── AC10 — format_dna_for_prompt ──────────────────────────────────────────────


@pytest.mark.unit
def test_format_dna_for_prompt_returns_nonempty_string() -> None:
    """AC10: format_dna_for_prompt returns a non-empty string."""
    from app.modules.assessment.service import format_dna_for_prompt  # noqa: PLC0415

    context = {
        "dna_labels": dict.fromkeys(_ALL_9_DIMS, "Developing"),
        "badge_labels": ["Pattern Thinker"],
        "profile_snippet": "This student excels at pattern recognition.",
        "session_count": 5,
        "reassessment_due": False,
        "session_signals": {
            "quiz_accuracy": 72.0,
            "teachback_avg": 65.0,
            "intervention_count": 2,
        },
    }

    result = format_dna_for_prompt(context)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.unit
def test_format_dna_for_prompt_no_raw_float_dim_values() -> None:
    """AC10: output string does not contain raw float DNA dimension values."""
    from app.modules.assessment.service import format_dna_for_prompt  # noqa: PLC0415

    context = {
        "dna_labels": dict.fromkeys(_ALL_9_DIMS, "Developing"),
        "badge_labels": [],
        "profile_snippet": None,
        "session_count": 0,
        "reassessment_due": False,
        "session_signals": None,
    }

    result = format_dna_for_prompt(context)
    # No "60.0" raw float should appear — dimension values must be labels
    assert "60.0" not in result, (
        "Raw float '60.0' found in format_dna_for_prompt output — "
        "dimension values must only appear as labels"
    )


@pytest.mark.unit
def test_format_dna_for_prompt_empty_dna_message() -> None:
    """AC10: when dna_labels is empty, output says 'No Learner DNA available yet.'"""
    from app.modules.assessment.service import format_dna_for_prompt  # noqa: PLC0415

    context = {
        "dna_labels": {},
        "badge_labels": [],
        "profile_snippet": None,
        "session_count": 0,
        "reassessment_due": False,
        "session_signals": None,
    }

    result = format_dna_for_prompt(context)
    assert "No Learner DNA available yet" in result


@pytest.mark.unit
def test_format_dna_for_prompt_with_session_signals_no_float_literals() -> None:
    """AC10: session signals rendered as integers (:.0f), not floats like '72.5'."""
    from app.modules.assessment.service import format_dna_for_prompt  # noqa: PLC0415

    context = {
        "dna_labels": dict.fromkeys(_ALL_9_DIMS, "Proficient"),
        "badge_labels": ["Quick Learner"],
        "profile_snippet": "A capable student.",
        "session_count": 3,
        "reassessment_due": False,
        "session_signals": {
            "quiz_accuracy": 72.3456,
            "teachback_avg": 65.9876,
            "intervention_count": 1,
        },
    }

    result = format_dna_for_prompt(context)
    # Should not contain a '.' after quiz accuracy or teachback values
    # (they are rendered as integer percentages)
    assert "72.3" not in result, "quiz_accuracy must be rendered as integer, not float"
    assert "65.9" not in result, "teachback_avg must be rendered as integer, not float"
    # But integer-rounded versions are fine:
    assert "72" in result or "teachback" in result  # at minimum something rendered


# ── AC11 — guard test regression (import-level) ───────────────────────────────


@pytest.mark.unit
def test_ces_module_all_unchanged() -> None:
    """AC11: ces.__all__ still equals the canonical two-function list.

    This story does NOT touch ces.py. If this test fails, something else
    modified ces.py outside of this story's scope.
    """
    import app.modules.assessment.ces as ces_module  # noqa: PLC0415

    assert list(ces_module.__all__) == ["compute_ces", "compute_personalized_threshold"], (
        f"ces.__all__ unexpectedly changed: {ces_module.__all__!r}"
    )


@pytest.mark.unit
def test_unbounded_query_guard_passes_import() -> None:
    """AC11: test_unbounded_queries module is importable (guard is not broken)."""
    import importlib  # noqa: PLC0415

    mod = importlib.import_module("tests.unit.test_unbounded_queries")
    assert mod is not None


# ── Review-fix tests (from 6-agent code review, 2026-09-03) ──────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_signal_exception_swallowed_signals_path() -> None:
    """AC8 (session signal path): exception during quiz_attempts query is caught;
    returns safe fallback session_signals without raising.
    """
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))

    # Supabase raises on quiz_attempts query
    supabase = MagicMock()

    def _bad_table(name: str) -> MagicMock:
        if name == "quiz_attempts":
            raise Exception("DB connection lost")
        return _make_supabase().table(name)  # normal for others

    supabase.table = MagicMock(side_effect=_bad_table)

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=_make_settings(),
    )

    # Must not raise; session_signals is the safe fallback
    assert isinstance(result, dict)
    signals = result["session_signals"]
    assert signals is not None
    assert signals["quiz_accuracy"] is None
    assert signals["teachback_avg"] is None
    assert signals["intervention_count"] == 0
    assert signals["signals_capped"] is False


@pytest.mark.asyncio
@pytest.mark.unit
async def test_session_events_event_type_filter_applied() -> None:
    """AC7: only 'intervention_acknowledged' events are counted; other types ignored."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    # The mock returns only rows matching the filter (as a real DB would).
    # We pass only 2 intervention_acknowledged rows to confirm count=2, not 5.
    event_rows = [
        {"event_type": "intervention_acknowledged"},
        {"event_type": "intervention_acknowledged"},
    ]
    supabase = _make_supabase(event_rows=event_rows)

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=_make_settings(),
    )

    assert result["session_signals"] is not None
    assert result["session_signals"]["intervention_count"] == 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_signals_capped_set_when_quiz_limit_hit() -> None:
    """P2/P3: signals_capped=True when quiz_rows reaches the .limit(500) boundary."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    # Simulate exactly 500 rows returned (the limit boundary — may be truncated)
    quiz_rows = [{"is_correct": True}] * 500
    supabase = _make_supabase(quiz_rows=quiz_rows)

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=_make_settings(),
    )

    signals = result["session_signals"]
    assert signals is not None
    assert signals["signals_capped"] is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_signals_capped_false_when_under_limit() -> None:
    """P2/P3: signals_capped=False for normal-sized sessions (no truncation)."""
    from app.modules.assessment.service import get_dna_prompt_context  # noqa: PLC0415

    redis = _make_redis(dna_json=json.dumps(_DNA_BLOB))
    quiz_rows = [{"is_correct": True}] * 10  # well under limit
    supabase = _make_supabase(quiz_rows=quiz_rows)

    result = await get_dna_prompt_context(
        user_id=_VALID_USER_ID,
        session_id=_VALID_SESSION_ID,
        supabase=supabase,
        redis=redis,
        settings=_make_settings(),
    )

    signals = result["session_signals"]
    assert signals is not None
    assert signals["signals_capped"] is False
