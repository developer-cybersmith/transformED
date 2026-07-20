"""
LLM provider factory — model-agnostic dispatch (Story 2-15, S2-15).

Responsibilities
----------------
- Single point where a model string (e.g. ``settings.llm_mini``) is turned
  into a concrete ``LLMProvider`` instance. Pipeline nodes call
  ``get_llm_provider()`` instead of importing a concrete provider class
  directly, so adding a new vendor is a pure addition here (one new branch +
  one new provider file) with zero node-code changes.
- Dispatches by model-name prefix. Each branch's provider import is
  deliberately LAZY (inside this function, at call time) — this mirrors
  every pipeline node's existing ``from app.providers.llm.openai import
  OpenAILLMProvider`` pattern and is what keeps every existing test's
  ``patch("app.providers.llm.openai.OpenAILLMProvider", ...)`` working
  unmodified now that nodes call this factory instead of importing the class
  directly: the lazy import resolves whatever the (possibly patched)
  attribute on ``app.providers.llm.openai`` is at call time, exactly like
  each node's own lazy import used to.
- Adding a real second provider (e.g. Gemini) later means adding a branch
  here, e.g.::

      if model.startswith("gemini-"):
          from app.providers.llm.gemini import GeminiLLMProvider
          return GeminiLLMProvider(lesson_id)

  No node in ``graph.py`` needs to change — every node already only knows
  about a ``settings.llm_*`` model string and this factory, never a concrete
  provider class.
- Prefix set for ``OpenAILLMProvider`` covers every OpenAI model family
  actually documented as a valid config value in ``config.py`` — not just
  ``gpt-*``. ``o1-mini`` is a real, documented eval candidate for
  ``LLM_LESSON_PLANNER``/``LLM_SLIDE_GENERATOR`` (see ``config.py``'s field
  descriptions) that does not start with ``"gpt-"``; a ``"gpt-"``-only check
  would raise a confusing ``ValueError`` for a model OpenAILLMProvider can
  actually serve (2026-07-16 review finding, Edge Case Hunter).
"""

from __future__ import annotations

from app.providers.base import LLMProvider

# OpenAI model-name prefixes routed to OpenAILLMProvider. Kept to prefixes
# actually documented as valid settings.llm_* values in config.py — add a new
# prefix here only when config.py documents it, don't speculate ahead of it.
_OPENAI_MODEL_PREFIXES: tuple[str, ...] = ("gpt-", "o1-")


def get_llm_provider(model: str, lesson_id: str | None = None) -> LLMProvider:
    """Return the ``LLMProvider`` implementation for *model*.

    Args:
        model:     Model identifier string (e.g. ``"gpt-4o-mini"``).
        lesson_id: Optional lesson ID, forwarded to the provider's
                   constructor for cost tracking.

    Returns:
        A concrete ``LLMProvider`` instance.

    Raises:
        ValueError: if *model* isn't a non-empty string, or no provider is
            registered for its prefix.
    """
    if not isinstance(model, str) or not model:
        raise ValueError(f"model must be a non-empty string, got {model!r}")

    if model.startswith(_OPENAI_MODEL_PREFIXES):
        from app.providers.llm.openai import OpenAILLMProvider

        return OpenAILLMProvider(lesson_id)

    raise ValueError(f"No LLMProvider registered for model {model!r}")
