"""
Shared pytest configuration.

Sets all required environment variables so Settings() can be instantiated
without a real .env file or deployed secrets. These are test stubs only.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True, scope="session")
def _stub_openai_package() -> None:
    """Stub the openai pip package so provider modules import without a real install.

    Stubs all submodules referenced at import time in app/providers/llm/openai.py
    and app/providers/embeddings/openai.py so the unit test suite runs without
    a live OpenAI SDK (or if setdefault replaces the real package on a fresh run).
    """
    stub = MagicMock()
    sys.modules.setdefault("openai", stub)
    sys.modules.setdefault("openai.types", stub.types)
    sys.modules.setdefault("openai.types.chat", stub.types.chat)
    sys.modules.setdefault("openai._models", stub._models)
    sys.modules.setdefault("openai.AsyncOpenAI", stub.AsyncOpenAI)
    sys.modules.setdefault("openai.types", stub.types)
    sys.modules.setdefault("openai.types.chat", stub.types.chat)


@pytest.fixture(autouse=True, scope="session")
def _set_test_env() -> None:
    """Ensure all required Settings fields have stub values for unit tests."""
    stubs = {
        "SUPABASE_URL": "http://localhost:54321",
        "SUPABASE_ANON_KEY": "test-anon-key",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
        "SUPABASE_JWT_SECRET": "test-jwt-secret-that-is-long-enough-32-bytes",
        "OPENAI_API_KEY": "sk-test-openai-key",
        "SARVAM_API_KEY": "test-sarvam-key",
        "HEYGEN_API_KEY": "test-heygen-key",
        "LANGFUSE_PUBLIC_KEY": "test-langfuse-public",
        "LANGFUSE_SECRET_KEY": "test-langfuse-secret",
        "REDIS_URL": "redis://localhost:6379",
    }
    for key, value in stubs.items():
        os.environ.setdefault(key, value)
