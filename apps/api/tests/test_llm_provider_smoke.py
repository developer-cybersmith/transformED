"""
Smoke tests for OpenAILLMProvider.

These tests make real calls to the OpenAI API.
Marked `integration` — skipped in CI unless explicitly selected with -m integration.

What these tests prove:
- complete() returns text from the model named by settings.llm_mini
- complete_structured() works via beta.chat.completions.parse()
  This specifically validates that openai>=1.40.0 is correctly installed.
  If this test fails with AttributeError, the version pin is wrong.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.config import Settings as _Settings

# Skip entire module when OPENAI_API_KEY is absent — keeps CI green
if not os.getenv("OPENAI_API_KEY"):
    pytest.skip("OPENAI_API_KEY not set", allow_module_level=True)

pytestmark = pytest.mark.integration

# Read model name from class metadata — no env vars required, no hardcoded strings
_LLM_MINI = _Settings.model_fields["llm_mini"].default


class _SmallResponse(BaseModel):
    """Minimal Pydantic model for smoke-testing complete_structured()."""

    reply: str


@pytest.fixture()
def settings_mock() -> MagicMock:
    """Minimal settings — only OpenAI + Langfuse stubs needed for smoke tests."""
    m = MagicMock()
    m.openai_api_key = os.environ["OPENAI_API_KEY"]
    m.llm_mini = _LLM_MINI  # sourced from Settings.model_fields — never hardcoded
    m.langfuse_public_key = "test-pk"
    m.langfuse_secret_key = "test-sk"
    m.langfuse_host = "https://cloud.langfuse.com"
    m.max_lesson_cost_usd = 3.0
    return m


@pytest.fixture()
def provider(settings_mock: MagicMock):  # type: ignore[return]
    """OpenAILLMProvider with Redis/Langfuse mocked — only OpenAI is real."""
    import app.providers.llm.openai  # noqa: F401 — must be in sys.modules before patch() resolves target

    with (
        patch("app.providers.llm.openai.get_settings", return_value=settings_mock),
        patch("app.providers.llm.openai.Langfuse", return_value=MagicMock()),
        patch("app.providers.llm.openai.is_circuit_open", new=AsyncMock(return_value=False)),
        patch("app.providers.llm.openai.record_success", new=AsyncMock()),
        patch("app.providers.llm.openai.record_failure", new=AsyncMock()),
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0001)),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
    ):
        from app.providers.llm.openai import OpenAILLMProvider

        yield OpenAILLMProvider(lesson_id="smoke-test-lesson-001")


@pytest.mark.integration
async def test_complete_returns_text(provider, settings_mock: MagicMock) -> None:
    """complete() returns a non-empty string from settings.llm_mini."""
    result = await provider.complete(
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        model=settings_mock.llm_mini,
    )

    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert result.strip(), "complete() returned an empty response"


@pytest.mark.integration
async def test_complete_structured_parses_pydantic(
    provider,
    settings_mock: MagicMock,
) -> None:
    """complete_structured() returns a Pydantic model via beta.chat.completions.parse().

    If this raises AttributeError: 'Completions' has no attribute 'parse',
    openai>=1.40.0 is NOT installed. Fix: pip install 'openai>=1.40.0'.
    """
    result = await provider.complete_structured(
        messages=[{"role": "user", "content": "Give a one-word reply."}],
        model=settings_mock.llm_mini,
        response_format=_SmallResponse,
    )

    assert isinstance(result, _SmallResponse), (
        f"Expected _SmallResponse instance, got {type(result)}. "
        "This likely means beta.chat.completions.parse() failed."
    )
    assert result.reply.strip(), "Parsed Pydantic model has an empty reply field"
