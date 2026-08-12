"""
Unit tests: app/core/langfuse.py — global Langfuse singleton.

AC coverage:
- Single Langfuse instance per process (singleton)
- Langfuse constructed with settings values (public_key, secret_key, host)
- flush() reachable on the returned singleton (lifespan contract)
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

import app.core.langfuse as langfuse_module
from app.core.langfuse import get_langfuse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings(
    pub: str = "pk-test",
    sec: str = "sk-test",
    host: str = "https://host.test",
    environment: str = "test",
) -> MagicMock:
    s = MagicMock()
    s.langfuse_public_key = pub
    s.langfuse_secret_key = sec
    s.langfuse_host = host
    s.langfuse_environment = environment
    return s


@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None, None, None]:
    """Reset module-level singleton before and after every test."""
    langfuse_module._langfuse = None
    yield
    langfuse_module._langfuse = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@patch("app.core.langfuse.get_settings")
@patch("app.core.langfuse.Langfuse")
def test_get_langfuse_returns_langfuse_instance(
    mock_cls: MagicMock, mock_settings: MagicMock
) -> None:
    """get_langfuse() returns the object produced by Langfuse()."""
    mock_settings.return_value = _mock_settings()

    result = get_langfuse()

    assert result is mock_cls.return_value


@pytest.mark.unit
@patch("app.core.langfuse.get_settings")
@patch("app.core.langfuse.Langfuse")
def test_get_langfuse_is_singleton(mock_cls: MagicMock, mock_settings: MagicMock) -> None:
    """Repeated calls return the same instance; Langfuse() constructed exactly once."""
    mock_settings.return_value = _mock_settings()

    first = get_langfuse()
    second = get_langfuse()
    third = get_langfuse()

    assert first is second
    assert second is third
    mock_cls.assert_called_once()


@pytest.mark.unit
@patch("app.core.langfuse.get_settings")
@patch("app.core.langfuse.Langfuse")
def test_get_langfuse_uses_settings(mock_cls: MagicMock, mock_settings: MagicMock) -> None:
    """Langfuse() is called with the values from app.config.get_settings()."""
    mock_settings.return_value = _mock_settings(
        pub="pub-abc",
        sec="sec-xyz",
        host="https://custom.langfuse.io",
        environment="staging",
    )

    get_langfuse()

    mock_cls.assert_called_once_with(
        public_key="pub-abc",
        secret_key="sec-xyz",
        host="https://custom.langfuse.io",
        environment="staging",
    )


@pytest.mark.unit
@patch("app.core.langfuse.get_settings")
@patch("app.core.langfuse.Langfuse")
def test_get_langfuse_flush_callable(mock_cls: MagicMock, mock_settings: MagicMock) -> None:
    """Singleton exposes flush() — required by the lifespan shutdown handler."""
    mock_settings.return_value = _mock_settings()
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    lf = get_langfuse()
    lf.flush()

    mock_instance.flush.assert_called_once_with()


# ---------------------------------------------------------------------------
# safe_trace() -- best-effort wrapper (Story 3-40)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_safe_trace_returns_call_result_on_success() -> None:
    """The whole point of safe_trace: a successful call's return value passes through."""
    result = langfuse_module.safe_trace(lambda: "real-value")
    assert result == "real-value"


@pytest.mark.unit
def test_safe_trace_swallows_exception_and_returns_none() -> None:
    """A raising Langfuse call must never propagate -- tracing is best-effort and
    must never fail the pipeline it's observing."""

    def _boom() -> None:
        raise RuntimeError("langfuse is down")

    result = langfuse_module.safe_trace(_boom)
    assert result is None


@pytest.mark.unit
def test_safe_trace_logs_at_warning_not_debug(caplog: pytest.LogCaptureFixture) -> None:
    """An observability outage must stay visible in prod logs even though it
    never fails the pipeline -- WARNING, not DEBUG (this project's established
    convention; a prior version of similar code used DEBUG and the resulting
    silent failure went unnoticed for a full SDK major-version upgrade)."""

    def _boom() -> None:
        raise RuntimeError("langfuse is down")

    with caplog.at_level("WARNING", logger="app.core.langfuse"):
        langfuse_module.safe_trace(_boom)

    assert any(r.levelname == "WARNING" for r in caplog.records)


# ---------------------------------------------------------------------------
# deterministic_trace_context() -- lesson/session-scoped trace grouping (Story 3-40)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_deterministic_trace_context_returns_none_for_none_seed() -> None:
    """A provider constructed outside a pipeline/session run (no lesson_id, no
    session_id) has nothing to group under -- must degrade to a random trace_id,
    not a broken/partial context."""
    mock_lf = MagicMock()
    result = langfuse_module.deterministic_trace_context(mock_lf, None)
    assert result is None
    mock_lf.create_trace_id.assert_not_called()


@pytest.mark.unit
def test_deterministic_trace_context_calls_create_trace_id_with_seed() -> None:
    mock_lf = MagicMock()
    mock_lf.create_trace_id.return_value = "abc123"

    result = langfuse_module.deterministic_trace_context(mock_lf, "lesson-42")

    mock_lf.create_trace_id.assert_called_once_with(seed="lesson-42")
    assert result == {"trace_id": "abc123"}


@pytest.mark.unit
def test_deterministic_trace_context_same_seed_same_trace_id() -> None:
    """The entire reason this function exists: two independent calls sharing a
    seed must land under the SAME trace_id, so every provider call for one
    lesson (or one tutor session) groups together instead of each starting an
    unrelated top-level trace."""
    mock_lf = MagicMock()
    mock_lf.create_trace_id.side_effect = lambda seed: f"trace-for-{seed}"

    first = langfuse_module.deterministic_trace_context(mock_lf, "lesson-99")
    second = langfuse_module.deterministic_trace_context(mock_lf, "lesson-99")

    assert first == second == {"trace_id": "trace-for-lesson-99"}


@pytest.mark.unit
def test_deterministic_trace_context_returns_none_when_langfuse_errors() -> None:
    """create_trace_id raising must degrade to None (random trace_id), not
    propagate -- same best-effort contract as every other tracing call."""
    mock_lf = MagicMock()
    mock_lf.create_trace_id.side_effect = RuntimeError("langfuse down")

    result = langfuse_module.deterministic_trace_context(mock_lf, "lesson-1")

    assert result is None
