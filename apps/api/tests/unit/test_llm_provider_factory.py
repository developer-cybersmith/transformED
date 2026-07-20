"""
Unit tests for Story 2-15 (S2-15): LLM provider factory.

Covers docs/stories/2-15-llm-provider-factory.md's ACs:
- AC-1: get_llm_provider() dispatches by model-name prefix; unknown prefix
  raises ValueError with the offending model string in the message.
- AC-2: the factory's per-branch import is lazy (inside the function, at
  call time) — this is what keeps every existing node test's
  patch("app.providers.llm.openai.OpenAILLMProvider", ...) working
  unmodified once nodes call the factory instead of importing the class
  directly.

2026-07-16 code review patches (Edge Case Hunter):
- "o1-mini" (a real, config.py-documented eval candidate for
  LLM_LESSON_PLANNER/LLM_SLIDE_GENERATOR) must resolve to OpenAILLMProvider,
  not raise ValueError, despite not starting with "gpt-".
- None/non-string/empty model must raise a clear ValueError, not an
  unrelated-looking AttributeError from model.startswith(...).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Force the submodule into sys.modules so patch("app.providers.llm.openai.OpenAILLMProvider", ...)
# can resolve it — same convention as test_lesson_planner_node.py /
# test_phase1_economy_nodes.py.
import app.providers.llm.openai as openai_provider_module  # noqa: E402,F401


@pytest.mark.unit
def test_get_llm_provider_dispatches_gpt_prefix_to_openai_provider() -> None:
    from app.providers.llm.factory import get_llm_provider
    from app.providers.llm.openai import OpenAILLMProvider

    provider = get_llm_provider("gpt-4o-mini", lesson_id="lesson-1")

    assert isinstance(provider, OpenAILLMProvider)


@pytest.mark.unit
def test_get_llm_provider_accepts_none_lesson_id() -> None:
    from app.providers.llm.factory import get_llm_provider

    provider = get_llm_provider("gpt-4o")

    assert provider._lesson_id is None


@pytest.mark.unit
def test_get_llm_provider_unknown_prefix_raises_value_error_with_model_string() -> None:
    from app.providers.llm.factory import get_llm_provider

    with pytest.raises(ValueError, match="gemini-2.0-flash"):
        get_llm_provider("gemini-2.0-flash", lesson_id="lesson-1")


@pytest.mark.unit
def test_get_llm_provider_resolves_patched_openai_provider_lazily() -> None:
    """AC-2 regression guard: the factory's import must be lazy (inside the
    function body), not a module-level import bound at factory-module import
    time — otherwise patching app.providers.llm.openai.OpenAILLMProvider
    after factory.py has already been imported would have no effect, and
    every existing node test's patch target would silently stop working."""
    from app.providers.llm.factory import get_llm_provider

    mock_provider = MagicMock()
    with patch(
        "app.providers.llm.openai.OpenAILLMProvider", return_value=mock_provider
    ) as mock_cls:
        result = get_llm_provider("gpt-4o-mini", lesson_id="lesson-1")

    mock_cls.assert_called_once_with("lesson-1")
    assert result is mock_provider


@pytest.mark.unit
def test_get_llm_provider_dispatches_o1_mini_to_openai_provider() -> None:
    """config.py documents 'o1-mini' as a real eval candidate for
    LLM_LESSON_PLANNER/LLM_SLIDE_GENERATOR — it must resolve to
    OpenAILLMProvider like any other OpenAI model, not raise ValueError just
    because it doesn't start with 'gpt-'."""
    from app.providers.llm.factory import get_llm_provider
    from app.providers.llm.openai import OpenAILLMProvider

    provider = get_llm_provider("o1-mini", lesson_id="lesson-1")

    assert isinstance(provider, OpenAILLMProvider)


@pytest.mark.unit
@pytest.mark.parametrize("bad_model", [None, "", 42, ["gpt-4o"]])
def test_get_llm_provider_rejects_non_string_or_empty_model_with_value_error(
    bad_model: object,
) -> None:
    """A None/empty/non-string model must raise the documented ValueError,
    never an unrelated AttributeError from model.startswith(...)."""
    from app.providers.llm.factory import get_llm_provider

    with pytest.raises(ValueError):
        get_llm_provider(bad_model, lesson_id="lesson-1")  # type: ignore[arg-type]
