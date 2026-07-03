"""Unit tests for CES per-learner baseline computation (Story 3-24).

Test count: 25
Coverage:
- AC 1:  ces_baseline.py importable (implicit — import failure cascades to all tests)
- AC 2:  __all__ contains only "compute_and_store_ces_baseline"
- AC 3:  keyword-only async signature (positional args raise TypeError)
- AC 4:  single session → baseline = that session's ces_final
- AC 5:  fewer sessions than window → average of all available
- AC 6:  more sessions than window → average of most recent window only
- AC 7:  NULL ces_final rows and NULL ended_at rows excluded from average
- AC 8:  no completed sessions → returns None, no Redis write
          (covers: empty rows, resp.data=None, all ended_at=None)
- AC 9:  baseline written to Redis key user:{user_id}:ces_baseline as STRING
- AC 10: Redis key has TTL = ces_baseline_ttl_seconds
- AC 13: Redis write failure → logged, does NOT raise, baseline still returned
- AC 14: DB failure → raises HTTPException(503)
- AC 15: no hardcoded window literal (5) in ces_baseline.py (AST)
- AC 16: no forbidden imports in ces_baseline.py (AST)
- AC 17: Supabase query bounded by window*3 rows (fetch_limit checked)
- AC 18: baseline rounded to 4 decimal places
- AC 19: Redis.set NOT called when baseline is None

All tests are @pytest.mark.unit — no DB, no network.
Redis and Supabase are mocked with unittest.mock.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest
import pytest_asyncio

from app.config import Settings

# ── Settings factory ──────────────────────────────────────────────────────────

def _settings(window: int = 5, ttl: int = 86400) -> Settings:
    """Build a Settings instance with known baseline config for deterministic tests."""
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
        ces_baseline_window=window,
        ces_baseline_ttl_seconds=ttl,
    )


# ── Supabase mock factory ─────────────────────────────────────────────────────

def _supabase_mock(rows: list[dict]) -> MagicMock:
    """Build a supabase MagicMock that returns the given rows from .execute()."""
    supabase = MagicMock()
    mock_resp = MagicMock()
    mock_resp.data = rows
    (
        supabase.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = mock_resp
    return supabase


def _supabase_error_mock() -> MagicMock:
    """Build a supabase MagicMock that raises RuntimeError when .execute() is called."""
    supabase = MagicMock()
    (
        supabase.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute
    ).side_effect = RuntimeError("DB connection refused")
    return supabase


# Lazy import so collection does not fail before ces_baseline.py is created.
def _import_module():
    from app.modules.assessment import ces_baseline
    return ces_baseline


def _import_func():
    from app.modules.assessment.ces_baseline import compute_and_store_ces_baseline
    return compute_and_store_ces_baseline


def _import_private():
    from app.modules.assessment.ces_baseline import _compute_baseline, _redis_key
    return _compute_baseline, _redis_key


# ── AC 2: __all__ ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_dunder_all_exports_only_compute_and_store():
    """AC 2: __all__ must contain only 'compute_and_store_ces_baseline'."""
    mod = _import_module()
    assert hasattr(mod, "__all__"), "__all__ must be defined"
    assert list(mod.__all__) == ["compute_and_store_ces_baseline"], (
        f"__all__ must contain only 'compute_and_store_ces_baseline', got {mod.__all__!r}"
    )


# ── AC 3: keyword-only signature ──────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_positional_args_raise_type_error():
    """AC 3: All parameters are keyword-only — positional call raises TypeError."""
    func = _import_func()
    with pytest.raises(TypeError):
        await func("user-1", MagicMock(), AsyncMock(), _settings())  # type: ignore[call-arg]


# ── Redis key format ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_redis_key_format():
    """AC 9: Redis key format is user:{user_id}:ces_baseline."""
    _, _redis_key = _import_private()
    user_id = "abc-123-def"
    assert _redis_key(user_id) == "user:abc-123-def:ces_baseline"


# ── Pure computation: _compute_baseline ──────────────────────────────────────

@pytest.mark.unit
def test_compute_baseline_single_score():
    """AC 4: Single score → baseline equals that score."""
    _compute_baseline, _ = _import_private()
    result = _compute_baseline([72.5])
    assert result == pytest.approx(72.5, abs=1e-4)


@pytest.mark.unit
def test_compute_baseline_fewer_than_window():
    """AC 5: Fewer scores than window → average of all available."""
    _compute_baseline, _ = _import_private()
    # 3 scores when window=5: average them all
    result = _compute_baseline([60.0, 70.0, 80.0])
    assert result == pytest.approx(70.0, abs=1e-4)


@pytest.mark.unit
def test_compute_baseline_exactly_window():
    """AC 6: Exactly window scores → correct average."""
    _compute_baseline, _ = _import_private()
    scores = [50.0, 60.0, 70.0, 80.0, 90.0]
    result = _compute_baseline(scores)
    assert result == pytest.approx(70.0, abs=1e-4)


@pytest.mark.unit
def test_compute_baseline_empty_returns_none():
    """AC 8: Empty score list → None."""
    _compute_baseline, _ = _import_private()
    assert _compute_baseline([]) is None


@pytest.mark.unit
def test_compute_baseline_rounded_to_4dp():
    """AC 18: Baseline rounded to exactly 4 decimal places."""
    _compute_baseline, _ = _import_private()
    # 1/3 = 0.333... — should be rounded to 4 d.p.
    result = _compute_baseline([100.0 / 3])
    assert result is not None
    assert result == pytest.approx(33.3333, abs=0.0001)
    # Verify it's a float, not an integer
    assert isinstance(result, float)


@pytest.mark.unit
def test_compute_baseline_all_zeros():
    """Edge case: all CES finals are 0.0 → baseline is 0.0."""
    _compute_baseline, _ = _import_private()
    result = _compute_baseline([0.0, 0.0, 0.0])
    assert result == pytest.approx(0.0, abs=1e-6)


# ── Async integration tests (Supabase + Redis mocked) ────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_returns_none_when_no_sessions():
    """AC 8: No sessions rows → returns None."""
    func = _import_func()
    supabase = _supabase_mock(rows=[])
    redis = AsyncMock()
    result = await func(
        user_id="user-1",
        supabase=supabase,
        redis=redis,
        settings=_settings(),
    )
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_no_redis_write_when_no_sessions():
    """AC 8 + AC 9: When baseline is None, Redis.set must NOT be called."""
    func = _import_func()
    supabase = _supabase_mock(rows=[])
    redis = AsyncMock()
    await func(user_id="user-1", supabase=supabase, redis=redis, settings=_settings())
    redis.set.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_single_session_baseline():
    """AC 4: Single completed session → baseline equals that ses_final."""
    func = _import_func()
    supabase = _supabase_mock(rows=[
        {"ces_final": 72.5, "ended_at": "2026-07-01T10:00:00"},
    ])
    redis = AsyncMock()
    result = await func(
        user_id="user-1",
        supabase=supabase,
        redis=redis,
        settings=_settings(),
    )
    assert result == pytest.approx(72.5, abs=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_rolling_window_uses_most_recent():
    """AC 6: window=3; 5 rows returned; average of most-recent 3 only."""
    func = _import_func()
    # Ordered DESC — the mock returns them in DESC order (newest first)
    rows = [
        {"ces_final": 80.0, "ended_at": "2026-07-05T10:00:00"},  # newest
        {"ces_final": 70.0, "ended_at": "2026-07-04T10:00:00"},
        {"ces_final": 60.0, "ended_at": "2026-07-03T10:00:00"},  # ← window boundary
        {"ces_final": 50.0, "ended_at": "2026-07-02T10:00:00"},  # excluded
        {"ces_final": 40.0, "ended_at": "2026-07-01T10:00:00"},  # excluded
    ]
    supabase = _supabase_mock(rows=rows)
    redis = AsyncMock()
    result = await func(
        user_id="user-1",
        supabase=supabase,
        redis=redis,
        settings=_settings(window=3),
    )
    # average of 80, 70, 60 = 70.0
    assert result == pytest.approx(70.0, abs=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_skips_null_ces_final_rows():
    """AC 7: Rows with ces_final=None are excluded; only non-NULL rows count."""
    func = _import_func()
    rows = [
        {"ces_final": None,  "ended_at": "2026-07-05T10:00:00"},  # skipped
        {"ces_final": 80.0,  "ended_at": "2026-07-04T10:00:00"},
        {"ces_final": None,  "ended_at": "2026-07-03T10:00:00"},  # skipped
        {"ces_final": 60.0,  "ended_at": "2026-07-02T10:00:00"},
    ]
    supabase = _supabase_mock(rows=rows)
    redis = AsyncMock()
    result = await func(
        user_id="user-1",
        supabase=supabase,
        redis=redis,
        settings=_settings(),
    )
    # only 80 and 60 count → average = 70.0
    assert result == pytest.approx(70.0, abs=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_skips_null_ended_at_rows():
    """AC 7: Rows with ended_at=None (session not yet complete) are excluded."""
    func = _import_func()
    rows = [
        {"ces_final": 90.0, "ended_at": None},          # in-progress session, skipped
        {"ces_final": 70.0, "ended_at": "2026-07-04T10:00:00"},
    ]
    supabase = _supabase_mock(rows=rows)
    redis = AsyncMock()
    result = await func(
        user_id="user-1",
        supabase=supabase,
        redis=redis,
        settings=_settings(),
    )
    assert result == pytest.approx(70.0, abs=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_writes_correct_redis_key():
    """AC 9: Redis.set is called with key='user:{user_id}:ces_baseline'."""
    func = _import_func()
    supabase = _supabase_mock(rows=[
        {"ces_final": 65.0, "ended_at": "2026-07-01T10:00:00"},
    ])
    redis = AsyncMock()
    await func(user_id="user-abc", supabase=supabase, redis=redis, settings=_settings())
    # First positional arg to redis.set must be the correct key
    assert redis.set.called
    called_key = redis.set.call_args[0][0] if redis.set.call_args[0] else redis.set.call_args[1].get("name")
    assert called_key == "user:user-abc:ces_baseline", (
        f"Expected 'user:user-abc:ces_baseline', got {called_key!r}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_sets_correct_ttl():
    """AC 10: Redis.set is called with ex=ces_baseline_ttl_seconds."""
    func = _import_func()
    supabase = _supabase_mock(rows=[
        {"ces_final": 65.0, "ended_at": "2026-07-01T10:00:00"},
    ])
    redis = AsyncMock()
    s = _settings(ttl=3600)
    await func(user_id="user-1", supabase=supabase, redis=redis, settings=s)
    redis.set.assert_called_once()
    # Verify TTL kwarg
    kwargs = redis.set.call_args[1] if redis.set.call_args[1] else {}
    args = redis.set.call_args[0] if redis.set.call_args[0] else ()
    ex_value = kwargs.get("ex") or (args[2] if len(args) > 2 else None)
    assert ex_value == 3600, f"Expected TTL=3600, got {ex_value!r}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_redis_failure_does_not_raise():
    """AC 13: Redis.set failure → logged, does NOT propagate; baseline still returned."""
    func = _import_func()
    supabase = _supabase_mock(rows=[
        {"ces_final": 75.0, "ended_at": "2026-07-01T10:00:00"},
    ])
    redis = AsyncMock()
    redis.set.side_effect = ConnectionError("Redis unreachable")
    # Must not raise — Redis failure is non-fatal
    result = await func(user_id="user-1", supabase=supabase, redis=redis, settings=_settings())
    assert result == pytest.approx(75.0, abs=1e-4)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_db_failure_raises_503():
    """AC 14: Supabase query failure raises HTTPException with status_code=503."""
    from fastapi import HTTPException
    func = _import_func()
    supabase = _supabase_error_mock()
    redis = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await func(user_id="user-1", supabase=supabase, redis=redis, settings=_settings())
    assert exc_info.value.status_code == 503
    assert "session history" in exc_info.value.detail.lower()


# ── AC 15: no hardcoded window literal ───────────────────────────────────────

@pytest.mark.unit
def test_no_hardcoded_window_literal():
    """AC 15: ces_baseline.py must not contain the hardcoded literal 5 (window default).

    The window must always come from settings.ces_baseline_window.
    Checked via AST scan of integer constants.
    """
    baseline_path = (
        Path(__file__).parent.parent
        / "app" / "modules" / "assessment" / "ces_baseline.py"
    )
    source = baseline_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    # 5 is the default window — it must not appear as a standalone integer literal
    # in business logic (it can appear in comments). We check AST nodes only.
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == 5 and isinstance(node.value, int):
            found.append(node.value)
    assert not found, (
        f"Hardcoded window literal 5 found in ces_baseline.py as an AST constant. "
        "Use settings.ces_baseline_window instead."
    )


# ── AC 16: no forbidden imports ──────────────────────────────────────────────

@pytest.mark.unit
def test_no_forbidden_imports():
    """AC 16: ces_baseline.py must not import forbidden modules."""
    baseline_path = (
        Path(__file__).parent.parent
        / "app" / "modules" / "assessment" / "ces_baseline.py"
    )
    source = baseline_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"supabase", "openai", "posthog", "httpx", "requests"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden:
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in forbidden:
                found.append(node.module)
    assert not found, f"Forbidden imports found in ces_baseline.py: {found}"


# ── BLOCKER fix 1: Redis value must be a STRING ───────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_redis_value_is_string():
    """AC 9: Value written to Redis must be a string, not a bare float.

    A future change from str(baseline) to baseline (float) would break Redis
    clients that expect decode_responses=True string values.
    """
    func = _import_func()
    supabase = _supabase_mock(rows=[
        {"ces_final": 72.5, "ended_at": "2026-07-01T10:00:00"},
    ])
    redis = AsyncMock()
    await func(user_id="user-1", supabase=supabase, redis=redis, settings=_settings())
    redis.set.assert_called_once()
    stored_value = redis.set.call_args[0][1]  # positional arg[1] = the value
    assert isinstance(stored_value, str), (
        f"Redis value must be a string, got {type(stored_value)}: {stored_value!r}"
    )
    assert stored_value == "72.5"


# ── BLOCKER fix 2: AC 17 fetch limit is bounded ───────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_fetch_limit_is_bounded():
    """AC 17: Supabase .limit() is called with window*3 — never unbounded."""
    func = _import_func()
    s = _settings(window=3)  # window=3 → fetch_limit should be 9
    supabase = _supabase_mock(rows=[])
    redis = AsyncMock()
    await func(user_id="user-1", supabase=supabase, redis=redis, settings=s)
    limit_mock = (
        supabase.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit
    )
    limit_mock.assert_called_once_with(9)  # 3 (window) × 3 (_OVERFETCH_FACTOR)


# ── IMPROVEMENT: resp.data = None path ───────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_resp_data_none():
    """AC 8: resp.data=None (not empty list) is handled correctly — returns None."""
    func = _import_func()
    supabase = MagicMock()
    mock_resp = MagicMock()
    mock_resp.data = None  # explicit None, not []
    (
        supabase.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = mock_resp
    redis = AsyncMock()
    result = await func(
        user_id="user-1", supabase=supabase, redis=redis, settings=_settings()
    )
    assert result is None
    redis.set.assert_not_called()


# ── IMPROVEMENT: all ended_at=None path ──────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_all_rows_ended_at_none_returns_none():
    """AC 8: All rows have ended_at=None (all sessions in-progress) → returns None."""
    func = _import_func()
    rows = [
        {"ces_final": 80.0, "ended_at": None},
        {"ces_final": 70.0, "ended_at": None},
        {"ces_final": 60.0, "ended_at": None},
    ]
    supabase = _supabase_mock(rows=rows)
    redis = AsyncMock()
    result = await func(
        user_id="user-1", supabase=supabase, redis=redis, settings=_settings()
    )
    assert result is None
    redis.set.assert_not_called()
