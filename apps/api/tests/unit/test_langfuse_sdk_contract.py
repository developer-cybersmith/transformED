"""
Unit tests: Langfuse 4.x SDK-surface contract (Story 2-0, AC-3).

Imports the REAL langfuse package (tests/conftest.py stubs only ``openai``)
and asserts that every client/observation method + kwarg the provider tracing
code calls actually exists on the installed SDK. If langfuse is ever upgraded
to an incompatible major, these tests fail loudly BEFORE a live pipeline run
crashes inside embed_node.

Provider call surface under contract (see app/providers/embeddings/openai.py
and app/providers/llm/openai.py):

- Langfuse(public_key=..., secret_key=..., host=...)          (core singleton)
- client.start_observation(name=..., as_type="generation",
      model=..., input=..., metadata=...) -> LangfuseGeneration
- generation.update(output=..., usage_details=..., level=..., status_message=...)
- generation.end()
- client.flush()                                              (lifespan shutdown)
"""

from __future__ import annotations

import importlib
import inspect
import sys
from unittest.mock import MagicMock

import langfuse
import pytest
from langfuse import Langfuse, LangfuseGeneration


def _ensure_openai_submodule_stubs() -> None:
    """Extend the conftest ``openai`` stub with the submodules providers import.

    tests/conftest.py stubs ``sys.modules['openai']`` with a MagicMock, which is
    not a package — ``from openai.types.chat import ChatCompletion`` would raise
    ModuleNotFoundError. Langfuse itself stays REAL; only openai is stubbed.
    """
    if isinstance(sys.modules.get("openai"), MagicMock):
        sys.modules.setdefault("openai.types", MagicMock())
        sys.modules.setdefault("openai.types.chat", MagicMock())


# ---------------------------------------------------------------------------
# Version pin
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_langfuse_major_version_is_4() -> None:
    """Providers are written against the langfuse 4.x OTel API.

    A different major means the tracing surface below is unverified — this
    test fails loudly so the providers get re-audited before deploy.
    """
    major = int(langfuse.__version__.split(".")[0])
    assert major == 4, (
        f"Installed langfuse {langfuse.__version__} — provider tracing code is "
        "written against 4.x. Re-verify start_observation/update/end and update "
        "this contract test before bumping the pyproject pin."
    )


# ---------------------------------------------------------------------------
# Client surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_client_constructor_accepts_settings_kwargs() -> None:
    """app/core/langfuse.py constructs Langfuse(public_key=, secret_key=, host=)."""
    params = inspect.signature(Langfuse.__init__).parameters
    for kwarg in ("public_key", "secret_key", "host"):
        assert kwarg in params, f"Langfuse.__init__ lost kwarg '{kwarg}'"


@pytest.mark.unit
def test_client_has_start_observation_with_provider_kwargs() -> None:
    """Providers call client.start_observation(name=, as_type=, model=, input=, metadata=)."""
    assert hasattr(Langfuse, "start_observation")
    params = inspect.signature(Langfuse.start_observation).parameters
    for kwarg in ("name", "as_type", "model", "input", "metadata"):
        assert kwarg in params, f"Langfuse.start_observation lost kwarg '{kwarg}'"


@pytest.mark.unit
def test_start_observation_as_type_accepts_generation() -> None:
    """Providers pass as_type='generation' — the Literal must still include it."""
    params = inspect.signature(Langfuse.start_observation).parameters
    assert "generation" in str(params["as_type"].annotation)


@pytest.mark.unit
def test_client_has_flush() -> None:
    """FastAPI lifespan shutdown calls get_langfuse().flush()."""
    assert hasattr(Langfuse, "flush")
    assert callable(Langfuse.flush)


@pytest.mark.unit
def test_dead_v2_api_is_absent() -> None:
    """Guard against a silent downgrade to the v2 SDK: .trace() must NOT exist.

    If .trace() reappears, the environment is running langfuse 2.x and the
    v4-only provider code below would be the broken side instead.
    """
    assert not hasattr(Langfuse, "trace")


# ---------------------------------------------------------------------------
# Generation-observation surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generation_has_update_with_provider_kwargs() -> None:
    """Providers call generation.update(output=, usage_details=, level=, status_message=)."""
    assert hasattr(LangfuseGeneration, "update")
    params = inspect.signature(LangfuseGeneration.update).parameters
    for kwarg in ("output", "usage_details", "level", "status_message"):
        assert kwarg in params, f"LangfuseGeneration.update lost kwarg '{kwarg}'"


@pytest.mark.unit
def test_generation_has_end() -> None:
    """Providers call generation.end() in a finally block on every path."""
    assert hasattr(LangfuseGeneration, "end")
    assert callable(LangfuseGeneration.end)


@pytest.mark.unit
def test_start_observation_returns_generation_type_for_generation() -> None:
    """The return annotation of start_observation must include LangfuseGeneration."""
    ret = inspect.signature(Langfuse.start_observation).return_annotation
    assert "LangfuseGeneration" in str(ret)


# ---------------------------------------------------------------------------
# Provider modules import cleanly against the real SDK
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_path",
    [
        "app.providers.embeddings.openai",
        "app.providers.llm.openai",
    ],
)
def test_provider_module_imports_cleanly(module_path: str) -> None:
    """Both providers must import with no AttributeError at import time."""
    _ensure_openai_submodule_stubs()
    module = importlib.import_module(module_path)
    assert module is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_path",
    [
        "app.providers.embeddings.openai",
        "app.providers.llm.openai",
    ],
)
def test_provider_source_has_no_v2_calls(module_path: str) -> None:
    """Zero calls to removed v2 methods (.trace(...) / .generation(...)) in providers."""
    _ensure_openai_submodule_stubs()
    module = importlib.import_module(module_path)
    source = inspect.getsource(module)
    assert ".trace(" not in source, f"{module_path} still calls the dead v2 .trace() API"
    assert ".generation(" not in source, f"{module_path} still calls the dead v2 .generation() API"
    assert "start_observation(" in source, f"{module_path} does not use v4 start_observation"
