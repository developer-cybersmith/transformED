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
import re
import sys
from unittest.mock import MagicMock

import langfuse
import pytest
from langfuse import Langfuse, LangfuseGeneration, propagate_attributes


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
# Event-observation surface (Story 3-40 -- tutor FSM dispatch tracing)
# ---------------------------------------------------------------------------
#
# Not `start_observation(as_type="event")` -- this pinned SDK version's
# real Literal does not include "event" (confirmed below), even though
# the live Langfuse docs describe it as a capability of a newer version.
# The tutor FSM uses `create_event()` instead -- the dedicated method this
# version actually exposes for a discrete, instantaneous observation.


@pytest.mark.unit
def test_start_observation_as_type_does_not_accept_event_on_this_pinned_version() -> None:
    """Documents WHY create_event() is used instead of start_observation(as_type="event"):
    this pinned SDK's real overload does not include "event" as a valid as_type literal.
    If this ever starts failing, the SDK has gained "event" support and
    modules/tutor/state_machine/graph.py's _trace_dispatch could be simplified
    back to start_observation -- re-verify before doing so, don't assume."""
    params = inspect.signature(Langfuse.start_observation).parameters
    assert "event" not in str(params["as_type"].annotation)


@pytest.mark.unit
def test_client_has_create_event_with_provider_kwargs() -> None:
    """The tutor FSM's _trace_dispatch calls
    client.create_event(name=, input=, output=, metadata=, trace_context=)."""
    assert hasattr(Langfuse, "create_event")
    params = inspect.signature(Langfuse.create_event).parameters
    for kwarg in ("name", "input", "output", "metadata", "trace_context"):
        assert kwarg in params, f"Langfuse.create_event lost kwarg '{kwarg}'"


@pytest.mark.unit
def test_create_event_docstring_example_does_not_call_end() -> None:
    """create_event's returned LangfuseEvent DOES inherit an end() method (it's
    shared across all observation-wrapper types), but the SDK's own docstring
    example never calls it -- `event = langfuse.create_event(name=...)`, full
    stop. That's why _trace_dispatch has no `finally: observation.end()`, unlike
    every provider's generation-tracing code. This test pins the SDK's own
    documented usage pattern, not the type's attribute shape (which does have
    `.end`, contrary to an earlier, incorrect version of this test)."""
    doc = Langfuse.create_event.__doc__ or ""
    assert ".end(" not in doc, (
        "create_event's own docstring now shows an .end() call in its example -- "
        "re-check whether _trace_dispatch needs one too"
    )


# ---------------------------------------------------------------------------
# propagate_attributes() -- session_id grouping (Story 3-40 -- tutor FSM)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_propagate_attributes_is_a_top_level_import() -> None:
    """The tutor FSM imports `from langfuse import propagate_attributes` (a
    module-level function, not a Langfuse client method) -- confirmed importable."""
    assert callable(propagate_attributes)


@pytest.mark.unit
def test_propagate_attributes_accepts_session_id() -> None:
    """This is the ONLY documented mechanism for setting the first-class
    session_id trace attribute -- neither start_observation nor create_event
    take session_id directly. If this kwarg disappears, _trace_dispatch's
    session-grouping breaks silently (every dispatch would still trace, just
    ungrouped)."""
    params = inspect.signature(propagate_attributes).parameters
    assert "session_id" in params, "propagate_attributes lost kwarg 'session_id'"


# ---------------------------------------------------------------------------
# Provider modules import cleanly against the real SDK
# ---------------------------------------------------------------------------


_TRACED_PROVIDER_MODULES = [
    "app.providers.embeddings.openai",
    "app.providers.llm.openai",
    "app.providers.tts.sarvam",
    "app.providers.tts.azure",
    "app.providers.image.openai_image",
    "app.providers.image.imagen",
]


@pytest.mark.unit
@pytest.mark.parametrize("module_path", _TRACED_PROVIDER_MODULES)
def test_provider_module_imports_cleanly(module_path: str) -> None:
    """Every traced provider must import with no AttributeError at import time."""
    _ensure_openai_submodule_stubs()
    module = importlib.import_module(module_path)
    assert module is not None


@pytest.mark.unit
@pytest.mark.parametrize("module_path", _TRACED_PROVIDER_MODULES)
def test_provider_source_has_no_v2_calls(module_path: str) -> None:
    """Zero calls to removed v2 methods (.trace(...) / .generation(...)) in providers."""
    _ensure_openai_submodule_stubs()
    module = importlib.import_module(module_path)
    source = inspect.getsource(module)
    assert ".trace(" not in source, f"{module_path} still calls the dead v2 .trace() API"
    assert ".generation(" not in source, f"{module_path} still calls the dead v2 .generation() API"
    assert "start_observation(" in source, f"{module_path} does not use v4 start_observation"


@pytest.mark.unit
def test_tutor_state_machine_module_imports_cleanly() -> None:
    """The tutor FSM's tracing (create_event/propagate_attributes) must import
    with no AttributeError at import time -- separate from the provider list
    above since it isn't an ImageProvider/TTSProvider/LLMProvider."""
    module = importlib.import_module("app.modules.tutor.state_machine.graph")
    assert module is not None


@pytest.mark.unit
def test_tutor_state_machine_source_has_no_v2_calls_and_uses_create_event() -> None:
    """D64: this module called the dead v2 .trace() method for every dispatch,
    silently no-op since the 4.x upgrade, swallowed at DEBUG level. Guards
    against exactly that regression -- zero *executable* `.trace(` calls
    (the docstring's own historical explanation legitimately quotes
    "`.trace()` method" in prose, so this strips docstrings/comments before
    scanning rather than a bare substring check, which would false-positive
    on that exact sentence), and the create_event/propagate_attributes
    replacement is actually present in real code."""
    module = importlib.import_module("app.modules.tutor.state_machine.graph")
    source = inspect.getsource(module)

    # Strip triple-quoted docstrings and '#'-comments before scanning for a
    # real call -- a naive substring check on the raw source false-positives
    # on this module's own docstring, which explains the D64 bug in prose.
    code_only = re.sub(r'"""(?:[^"]|"(?!""))*"""', "", source, flags=re.DOTALL)
    code_only = re.sub(r"#.*", "", code_only)

    assert ".trace(" not in code_only, (
        "tutor state machine calls the dead v2 .trace() API outside a docstring/comment"
    )
    assert "create_event(" in code_only, (
        "tutor state machine no longer calls create_event() -- D64's fix may have "
        "regressed back to a silently-broken tracing call"
    )
    assert "propagate_attributes(" in code_only, (
        "tutor state machine no longer calls propagate_attributes() -- session_id "
        "grouping for tutor dispatches may have silently regressed"
    )
