"""D49 — a rate limiter running on unshared per-process storage outside
debug mode must fail the deploy at startup, not silently multiply every
configured ceiling by replica count.

`RATE_LIMIT_STORAGE_URL` defaulting to `memory://` (`core/rate_limit.py:87`)
means each live API process keeps its own independent counter. fly.toml's
`api` process group runs with `auto_start_machines = true` and no fixed
replica count (ADR-001 §2: "bursty and request-scaled") — more than one live
machine is the expected case. `assert_rate_limit_storage_configured` closes
this the same way `assert_required_buckets` (Story 2-0, D1) closes a missing
storage bucket: loud, at boot, not a log line nobody reads.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import assert_rate_limit_storage_configured


@pytest.mark.unit
def test_raises_when_storage_is_memory_and_not_debug() -> None:
    """The D49 case: memory:// storage outside debug is the exact
    silently-per-process-multiplied ceiling this guard exists to catch."""
    with pytest.raises(RuntimeError, match=r"RATE_LIMIT_STORAGE_URL"):
        assert_rate_limit_storage_configured(debug=False, storage_uri="memory://")


@pytest.mark.unit
def test_raises_when_storage_url_env_var_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real production shape: nobody passes storage_uri explicitly — the
    function reads RATE_LIMIT_STORAGE_URL itself, exactly like the real
    `limiter = Limiter(..., storage_uri=os.environ.get(...))` construction."""
    monkeypatch.delenv("RATE_LIMIT_STORAGE_URL", raising=False)
    with pytest.raises(RuntimeError, match=r"RATE_LIMIT_STORAGE_URL"):
        assert_rate_limit_storage_configured(debug=False)


@pytest.mark.unit
def test_does_not_raise_in_debug_mode_even_with_memory_storage() -> None:
    """Local single-process dev is the one legitimate memory:// use — must
    not be blocked from starting."""
    assert_rate_limit_storage_configured(debug=True, storage_uri="memory://")


@pytest.mark.unit
def test_does_not_raise_when_storage_url_is_a_real_redis_uri() -> None:
    """A correctly configured deployment must start cleanly."""
    assert_rate_limit_storage_configured(debug=False, storage_uri="redis://redis.internal:6379/0")


@pytest.mark.unit
def test_does_not_raise_when_env_var_is_set_to_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URL", "redis://redis.internal:6379/0")
    assert_rate_limit_storage_configured(debug=False)


@pytest.mark.unit
def test_error_message_names_d49_and_the_adr_for_actionability() -> None:
    """A deploy-time crash with no pointer to the fix is barely better than
    the silent bug it replaces — the message must tell whoever sees it in
    Fly/Railway logs exactly what to set and where to read why."""
    with pytest.raises(RuntimeError) as exc_info:
        assert_rate_limit_storage_configured(debug=False, storage_uri="memory://")
    message = str(exc_info.value)
    assert "D49" in message
    assert "ADR-001" in message
