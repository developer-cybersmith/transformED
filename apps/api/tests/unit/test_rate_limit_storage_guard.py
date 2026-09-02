"""D49 — a rate limiter running on unshared per-process storage outside
debug mode must fail the deploy at startup, not silently multiply every
configured ceiling by replica count.

`RATE_LIMIT_STORAGE_URL` defaulting to `memory://` (`core/rate_limit.py`'s
`_RATE_LIMIT_STORAGE_URI`) means each live API process keeps its own
independent counter. fly.toml's
`api` process group runs with `auto_start_machines = true` and no fixed
replica count (ADR-001 §2: "bursty and request-scaled") — more than one live
machine is the expected case. `assert_rate_limit_storage_configured` closes
this the same way `assert_required_buckets` (Story 2-0, D1) closes a missing
storage bucket: loud, at boot, not a log line nobody reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.rate_limit import assert_rate_limit_storage_configured

_MAIN_PY = Path(__file__).resolve().parents[2] / "app" / "main.py"


@pytest.mark.unit
def test_raises_when_storage_is_memory_and_not_debug() -> None:
    """The D49 case: memory:// storage outside debug is the exact
    silently-per-process-multiplied ceiling this guard exists to catch."""
    with pytest.raises(RuntimeError, match=r"RATE_LIMIT_STORAGE_URL"):
        assert_rate_limit_storage_configured(debug=False, storage_uri="memory://")


@pytest.mark.unit
def test_raises_using_the_module_default_when_no_storage_uri_is_passed() -> None:
    """The real production shape: nobody passes storage_uri explicitly — the
    function falls back to `_RATE_LIMIT_STORAGE_URI`, resolved ONCE at import
    time from `RATE_LIMIT_STORAGE_URL` (Review Finding, Story 5-4: this is a
    single source of truth shared with `limiter` itself now, not a second,
    independent `os.environ` read that could silently diverge from it — env
    vars are resolved once at process startup in the real deployment anyway,
    so re-reading them per-call was never buying anything). This test
    environment never sets `RATE_LIMIT_STORAGE_URL` (`conftest.py`'s stub env
    vars don't include it), so the resolved default must be `memory://`."""
    from app.core.rate_limit import _RATE_LIMIT_STORAGE_URI

    assert _RATE_LIMIT_STORAGE_URI == "memory://", (
        "test precondition failed: this test proves the memory:// default "
        "raises; if RATE_LIMIT_STORAGE_URL is ever set in the test "
        "environment this assumption breaks and the test needs updating, "
        "not to silently keep passing for a different reason"
    )
    with pytest.raises(RuntimeError, match=r"RATE_LIMIT_STORAGE_URL"):
        assert_rate_limit_storage_configured(debug=False)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "storage_uri"),
    [
        ("empty string", ""),
        ("uppercase scheme", "MEMORY://"),
        ("leading whitespace", " memory://"),
        ("trailing whitespace", "memory:// "),
        ("uri suffix", "memory://foo"),
    ],
)
def test_raises_on_non_canonical_memory_variants(label: str, storage_uri: str) -> None:
    """Review Finding (Story 5-4, Scale & Load Hunter): the original guard
    only string-matched the exact literal "memory://" and silently let every
    one of these variants through, even though each one empirically resolves
    to a real, unshared `MemoryStorage` via `limits.storage.storage_from_string`
    — the same factory `Limiter` itself uses. Reproduces D49's failure mode
    through an input class the original guard never checked."""
    with pytest.raises(RuntimeError, match=r"RATE_LIMIT_STORAGE_URL"):
        assert_rate_limit_storage_configured(debug=False, storage_uri=storage_uri)


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
def test_guard_default_is_the_same_value_limiter_was_built_with() -> None:
    """Review Finding (Story 5-4, Blind Hunter + Edge Case Hunter + Test
    Coverage): the guard used to independently re-read `os.environ`, so a
    future refactor to one call site without the other could silently
    diverge from what `limiter` actually uses. Proves the fix's real
    invariant directly — both read the exact same module-level constant —
    rather than simulating a live env-var change after the module has
    already been imported, which the real deployment never does either."""
    from app.core.rate_limit import _RATE_LIMIT_STORAGE_URI, limiter

    assert limiter._storage_uri == _RATE_LIMIT_STORAGE_URI


@pytest.mark.unit
def test_lifespan_actually_calls_the_guard() -> None:
    """Review Finding (Story 5-4): every other test here calls
    `assert_rate_limit_storage_configured` directly, so none would notice if
    a future refactor silently dropped the call from `main.py`'s `lifespan()`
    entirely — deleting that one line reddened zero tests before this one
    existed. Mirrors `test_bucket_manifest.py::test_startup_paths_call_shared_assertion`,
    the same source-scan pattern that already guards `assert_required_buckets`'s
    own wiring."""
    source = _MAIN_PY.read_text(encoding="utf-8")
    assert "from app.core.rate_limit import assert_rate_limit_storage_configured" in source, (
        "main.py must import assert_rate_limit_storage_configured from app.core.rate_limit"
    )
    assert re.search(r"assert_rate_limit_storage_configured\(\s*debug=", source), (
        "main.py's lifespan() must call assert_rate_limit_storage_configured(debug=...) at startup"
    )


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
