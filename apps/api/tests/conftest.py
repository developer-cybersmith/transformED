"""
Shared pytest configuration.

Sets all required environment variables so Settings() can be instantiated
without a real .env file or deployed secrets. These are test stubs only.

IMPORTANT: env vars are set at MODULE LEVEL (not just inside a fixture) so that
test files can safely call get_settings() / compute_ces() at module scope without
crashing during pytest collection. The autouse fixture below is kept for legacy
compatibility but is no longer the primary mechanism.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Set stub env vars before any test module is collected ─────────────────────
# Module-level code in conftest.py runs during the collection phase, before test
# modules are imported. This ensures Settings() instantiation inside imported
# symbols (e.g. _EXPECTED_CES = compute_ces(...) at module scope) succeeds.
_STUB_ENV_VARS = {
    "SUPABASE_URL": "http://localhost:54321",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "SUPABASE_JWT_SECRET": "test-jwt-secret-that-is-long-enough-32-bytes",
    "OPENAI_API_KEY": "sk-test-openai-key",
    "SARVAM_API_KEY": "test-sarvam-key",
    "LANGFUSE_PUBLIC_KEY": "test-langfuse-public",
    "LANGFUSE_SECRET_KEY": "test-langfuse-secret",
    "REDIS_URL": "redis://localhost:6379",
}
for _key, _val in _STUB_ENV_VARS.items():
    os.environ.setdefault(_key, _val)


@pytest.fixture(autouse=True, scope="session")
def _stub_openai_package() -> None:
    """Stub the openai pip package so provider modules import without a real install.

    Stubs all submodules referenced at import time in app/providers/llm/openai.py
    and app/providers/embeddings/openai.py so the unit test suite runs without
    a live OpenAI SDK (or if setdefault replaces the real package on a fresh run).

    Story 2-32: this now DEFERS to the real SDK when it is importable. `openai`
    is a declared hard dependency (`pyproject.toml`: `openai>=1.40.0`), so in
    every supported environment the real package is present and stubbing it made
    the suite weaker for no benefit — provider tests were asserting against a
    MagicMock rather than the real exception hierarchy. Story 2-32 needs real
    `openai.APIStatusError` instances to prove `with_retry`'s classification, and
    those cannot be constructed from a MagicMock. The stub is kept only as a
    fallback for a stripped environment where the SDK genuinely is not installed.
    """
    try:
        import openai  # noqa: F401

        return  # Real SDK present — do not shadow it.
    except ImportError:
        pass

    stub = MagicMock()
    sys.modules.setdefault("openai", stub)
    sys.modules.setdefault("openai.types", stub.types)
    sys.modules.setdefault("openai.types.chat", stub.types.chat)
    sys.modules.setdefault("openai._models", stub._models)
    sys.modules.setdefault("openai.AsyncOpenAI", stub.AsyncOpenAI)
    sys.modules.setdefault("openai.types", stub.types)
    sys.modules.setdefault("openai.types.chat", stub.types.chat)


@contextmanager
def sixtydb_unconfigured_default():
    """Story 232: default SixtyDbTTSProvider to "not configured" (raises
    SixtyDbNotConfiguredError) wherever `_synthesize_with_fallback`/`tts_node`
    runs.

    60db is tried FIRST in the TTS fallback chain, ahead of Sarvam. Every
    pre-Story-232 test that exercises that chain mocks only
    SarvamTTSProvider/AzureTTSProvider directly — without this default, each
    would exercise the REAL SixtyDbTTSProvider (no SIXTYDB_API_KEY test stub
    exists, by design: the setting is optional so an unconfigured deployment
    degrades gracefully). Kept as an explicit, deliberate default (not relied
    on implicitly) so these tests stay correct regardless of ambient test env
    state, and so every test in files using it constructs the SAME mock
    rather than each incidentally hitting the real provider's __init__ (a
    real Langfuse-init attempt) and raising ValueError by coincidence of
    unset env vars. (Independent PR review, 2026-09-22: an earlier version of
    this docstring claimed the missing-config ValueError would reach
    guard_breaker and attempt a real Redis connection — stale, since the
    config-precondition checks in `synthesize()` were already moved before
    `guard_breaker` is entered by the time this docstring was written;
    corrected here.)

    Shared here (review finding) rather than duplicated as a private fixture
    in both test_tts_node.py and test_audio_duration_s3_38.py — kept as a
    plain context manager, NOT an autouse fixture at this (conftest) level,
    so test_tts_providers_sixtydb.py's own dedicated tests (which import and
    exercise the REAL class directly) are unaffected. Each file that needs
    the default wraps this in its own local `@pytest.fixture(autouse=True)`.
    """
    from app.providers.tts.sixtydb import SixtyDbNotConfiguredError

    mock_sixtydb = AsyncMock()
    # PR #240 review finding: must raise the same SixtyDbNotConfiguredError
    # subclass the real provider raises, not bare ValueError — graph.py's
    # fallback chain now catches that specific subclass (not bare
    # ValueError, which also matches genuine json.JSONDecodeError/
    # binascii.Error corruption) to avoid mislabeling a real bug as
    # "not configured". A bare ValueError here would silently stop
    # exercising the "not configured" code path this fixture exists for.
    mock_sixtydb.synthesize.side_effect = SixtyDbNotConfiguredError(
        "sixtydb not configured in test"
    )
    with patch("app.providers.tts.sixtydb.SixtyDbTTSProvider", return_value=mock_sixtydb):
        yield


@pytest.fixture(autouse=True, scope="session")
def _set_test_env() -> None:
    """Ensure all required Settings fields have stub values for unit tests.

    Kept for legacy compatibility. Primary setup now happens at module level
    above so that Settings() instantiation during collection succeeds.
    """
    for key, value in _STUB_ENV_VARS.items():
        os.environ.setdefault(key, value)
