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
from app.core.langfuse import get_langfuse, traced_node

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


# ---------------------------------------------------------------------------
# traced_node() -- per-node span wrapper (D69's node-level half, D123)
# ---------------------------------------------------------------------------


def _fake_langfuse(trace_id: str = "trace-1") -> MagicMock:
    lf = MagicMock()
    lf.create_trace_id.side_effect = lambda seed: f"trace-for-{seed}"
    lf.start_observation.return_value = MagicMock()
    return lf


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_shares_the_pipelines_deterministic_trace_id() -> None:
    """The entire point of D123: a node's span must land under the SAME
    trace_id as every provider call for that lesson, not a second,
    disconnected trace -- so it must be seeded by the same `lesson_id` via
    the same deterministic_trace_context() every provider already uses."""
    fake_lf = _fake_langfuse()

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("structure_node")
        async def structure_node(state: dict) -> dict:
            return state

        await structure_node({"lesson_id": "lesson-XYZ"})

    provider_ctx = langfuse_module.deterministic_trace_context(fake_lf, "lesson-XYZ")
    _, kwargs = fake_lf.start_observation.call_args
    assert kwargs["trace_context"] == provider_ctx
    assert kwargs["name"] == "structure_node"
    assert kwargs["as_type"] == "span"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_returns_the_wrapped_nodes_state() -> None:
    """The decorator must be transparent to the node's own return value --
    LangGraph reads specific state keys from whatever the node returns."""
    fake_lf = _fake_langfuse()

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("chunk_node")
        async def chunk_node(state: dict) -> dict:
            return {"chunks": ["a", "b"]}

        result = await chunk_node({"lesson_id": "lesson-1"})

    assert result == {"chunks": ["a", "b"]}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_propagates_the_nodes_exception() -> None:
    """A node failure must still fail the pipeline -- observability is
    additive, never a mask over a real error (this file's established
    safe_trace contract, applied here to the node span itself)."""
    fake_lf = _fake_langfuse()
    span = fake_lf.start_observation.return_value

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("embed_node")
        async def embed_node(state: dict) -> dict:
            raise ValueError("embedding provider is down")

        with pytest.raises(ValueError, match="embedding provider is down"):
            await embed_node({"lesson_id": "lesson-1"})

    span.update.assert_called_once_with(level="ERROR", status_message="embedding provider is down")
    span.end.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_ends_the_span_on_success() -> None:
    """The span must be closed on the success path too, not only on error --
    otherwise every successful node run leaks an open span."""
    fake_lf = _fake_langfuse()
    span = fake_lf.start_observation.return_value

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("tts_node")
        async def tts_node(state: dict) -> dict:
            return state

        await tts_node({"lesson_id": "lesson-1"})

    span.end.assert_called_once_with()
    span.update.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_degrades_gracefully_with_no_seed_in_state() -> None:
    """A state dict missing lesson_id (or the configured seed_key) must not
    crash the node -- degrades to a random trace_id, same as every other
    caller of deterministic_trace_context()."""
    fake_lf = _fake_langfuse()

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("slide_generator_node")
        async def slide_generator_node(state: dict) -> dict:
            return state

        result = await slide_generator_node({})

    assert result == {}
    fake_lf.create_trace_id.assert_not_called()
    _, kwargs = fake_lf.start_observation.call_args
    assert kwargs["trace_context"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_never_raises_when_langfuse_itself_is_down() -> None:
    """safe_trace's own contract, exercised through the decorator: a
    tracing-layer outage (start_observation raising) must never fail the
    node it wraps."""
    fake_lf = MagicMock()
    fake_lf.create_trace_id.side_effect = lambda seed: f"trace-for-{seed}"
    fake_lf.start_observation.side_effect = RuntimeError("langfuse is down")

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("package_builder_node")
        async def package_builder_node(state: dict) -> dict:
            return {"package": "built"}

        result = await package_builder_node({"lesson_id": "lesson-1"})

    assert result == {"package": "built"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traced_node_default_seed_key_is_lesson_id() -> None:
    """Content-pipeline nodes seed on lesson_id by default -- the tutor FSM
    deliberately does not use this decorator at all (see the decorator's own
    docstring), so no other seed_key is exercised by real callers today."""
    fake_lf = _fake_langfuse()

    with patch("app.core.langfuse.get_langfuse", return_value=fake_lf):

        @traced_node("lesson_planner_node")
        async def lesson_planner_node(state: dict) -> dict:
            return state

        await lesson_planner_node({"lesson_id": "lesson-42", "other_id": "ignored"})

    fake_lf.create_trace_id.assert_called_once_with(seed="lesson-42")
