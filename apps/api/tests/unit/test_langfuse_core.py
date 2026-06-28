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
    pub: str = "pk-test", sec: str = "sk-test", host: str = "https://host.test"
) -> MagicMock:
    s = MagicMock()
    s.langfuse_public_key = pub
    s.langfuse_secret_key = sec
    s.langfuse_host = host
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
    )

    get_langfuse()

    mock_cls.assert_called_once_with(
        public_key="pub-abc",
        secret_key="sec-xyz",
        host="https://custom.langfuse.io",
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
