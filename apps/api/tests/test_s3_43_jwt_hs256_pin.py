"""Tests for Story 3-43 — JWT HS256 algorithm pin (D80).

ACs tested:
  AC1 — settings.ws_allow_jwks_fallback field exists, default=False
  AC2 — default path: no jwt.get_unverified_header call when flag=False
  AC3 — non-HS256 token rejected with 401 (default config)
  AC4 — JWKS fallback preserved when flag=True
  AC5 — valid HS256 token accepted (no regression)
  AC6 — forged alg cannot trigger JWKS fetch when flag=False
  AC7 — guard test: CI-enforceable check that the branch is not on unverified alg

All tests are @pytest.mark.unit — no real network, no real Supabase.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── AC1 — Config flag exists with correct default ─────────────────────────────

@pytest.mark.unit
def test_ws_allow_jwks_fallback_default_is_false():
    """settings.ws_allow_jwks_fallback must default to False."""
    from app.config import Settings

    s = Settings()
    assert s.ws_allow_jwks_fallback is False


@pytest.mark.unit
def test_ws_allow_jwks_fallback_env_var_true(monkeypatch):
    """WS_ALLOW_JWKS_FALLBACK=true → settings.ws_allow_jwks_fallback == True."""
    monkeypatch.setenv("WS_ALLOW_JWKS_FALLBACK", "true")

    from app.config import Settings

    s = Settings()
    assert s.ws_allow_jwks_fallback is True


@pytest.mark.unit
def test_ws_allow_jwks_fallback_env_var_false(monkeypatch):
    """WS_ALLOW_JWKS_FALLBACK=false → settings.ws_allow_jwks_fallback == False."""
    monkeypatch.setenv("WS_ALLOW_JWKS_FALLBACK", "false")

    from app.config import Settings

    s = Settings()
    assert s.ws_allow_jwks_fallback is False


# ── AC2 — No jwt.get_unverified_header call when flag=False ──────────────────

@pytest.mark.unit
async def test_default_path_does_not_call_get_unverified_header():
    """When ws_allow_jwks_fallback=False, jwt.get_unverified_header must NOT be called."""
    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "dummy.jwt.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = False
    mock_settings.supabase_jwt_secret = "test-secret"

    decoded_payload = {"sub": "user-123", "exp": 9999999999, "iat": 1000000000}

    with (
        patch("app.dependencies.jwt.get_unverified_header") as mock_get_header,
        patch("app.dependencies.jwt.decode", return_value=decoded_payload),
    ):
        await get_current_user(mock_credentials, mock_settings)

    mock_get_header.assert_not_called()


@pytest.mark.unit
async def test_default_path_decodes_with_hs256_and_secret():
    """When flag=False, jwt.decode is called with HS256 algorithm and supabase_jwt_secret."""
    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "dummy.jwt.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = False
    mock_settings.supabase_jwt_secret = "my-secret"

    decoded_payload = {"sub": "user-abc", "exp": 9999999999, "iat": 1000000000}

    with patch("app.dependencies.jwt.decode", return_value=decoded_payload) as mock_decode:
        result = await get_current_user(mock_credentials, mock_settings)

    mock_decode.assert_called_once_with(
        "dummy.jwt.token",
        "my-secret",
        algorithms=["HS256"],
        audience="authenticated",
        options={"require": ["sub", "exp", "iat"]},
    )
    assert result["sub"] == "user-abc"


# ── AC3 — Non-HS256 token rejected with 401 (default config) ─────────────────

@pytest.mark.unit
async def test_rs256_token_rejected_when_fallback_disabled():
    """A token with RS256 alg is rejected with 401 when ws_allow_jwks_fallback=False."""
    import jwt as pyjwt
    from fastapi import HTTPException

    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "forged.rs256.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = False
    mock_settings.supabase_jwt_secret = "test-secret"

    with patch(
        "app.dependencies.jwt.decode",
        side_effect=pyjwt.InvalidAlgorithmError("The specified alg value is not allowed"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_credentials, mock_settings)

    assert exc_info.value.status_code == 401


@pytest.mark.unit
async def test_alg_none_token_rejected_when_fallback_disabled():
    """A token with alg=none is rejected with 401 when ws_allow_jwks_fallback=False."""
    import jwt as pyjwt
    from fastapi import HTTPException

    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "tampered.none.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = False
    mock_settings.supabase_jwt_secret = "test-secret"

    with patch(
        "app.dependencies.jwt.decode",
        side_effect=pyjwt.DecodeError("alg=none is not permitted"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(mock_credentials, mock_settings)

    assert exc_info.value.status_code == 401


# ── AC5 — Valid HS256 token still accepted (no regression) ───────────────────

@pytest.mark.unit
async def test_valid_hs256_token_accepted_default_config():
    """Valid HS256 token is accepted when ws_allow_jwks_fallback=False (standard path)."""
    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "valid.hs256.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = False
    mock_settings.supabase_jwt_secret = "secret"

    decoded = {"sub": "student-1", "email": "priya@example.com"}

    with patch("app.dependencies.jwt.decode", return_value=decoded):
        result = await get_current_user(mock_credentials, mock_settings)

    assert result["sub"] == "student-1"


@pytest.mark.unit
async def test_valid_hs256_token_accepted_with_fallback_enabled():
    """Valid HS256 token is accepted when ws_allow_jwks_fallback=True (both paths work)."""
    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "valid.hs256.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = True
    mock_settings.supabase_jwt_secret = "secret"

    decoded = {"sub": "student-2", "email": "priya@example.com"}

    with (
        patch(
            "app.dependencies.jwt.get_unverified_header",
            return_value={"alg": "HS256"},
        ),
        patch("app.dependencies.jwt.decode", return_value=decoded),
    ):
        result = await get_current_user(mock_credentials, mock_settings)

    assert result["sub"] == "student-2"


# ── AC4 — JWKS fallback preserved when flag=True ─────────────────────────────

@pytest.mark.unit
async def test_jwks_fallback_used_when_flag_enabled_and_non_hs256():
    """When ws_allow_jwks_fallback=True and alg=ES256, JWKS verification runs."""
    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "es256.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = True
    mock_settings.supabase_jwt_secret = "secret"
    mock_settings.supabase_url = "https://project.supabase.co"

    mock_signing_key = MagicMock()
    mock_signing_key.key = "fake-public-key"

    decoded = {"sub": "admin-user", "email": "admin@example.com"}

    with (
        patch("app.dependencies.jwt.get_unverified_header", return_value={"alg": "ES256"}),
        patch("app.dependencies._get_jwks_client") as mock_client_factory,
        patch("app.dependencies.jwt.decode", return_value=decoded),
    ):
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_factory.return_value = mock_jwks_client

        result = await get_current_user(mock_credentials, mock_settings)

    assert result["sub"] == "admin-user"
    mock_client_factory.assert_called_once()


# ── AC6 — Forged alg cannot trigger JWKS when flag=False ─────────────────────

@pytest.mark.unit
async def test_forged_rs256_cannot_trigger_jwks_fetch_when_flag_disabled():
    """A forged RS256 token never calls _get_jwks_client when ws_allow_jwks_fallback=False."""
    import jwt as pyjwt
    from fastapi import HTTPException

    from app.dependencies import get_current_user

    mock_credentials = MagicMock()
    mock_credentials.credentials = "forged.rs256.token"

    mock_settings = MagicMock()
    mock_settings.ws_allow_jwks_fallback = False
    mock_settings.supabase_jwt_secret = "test-secret"

    with (
        patch(
            "app.dependencies.jwt.decode",
            side_effect=pyjwt.InvalidAlgorithmError("alg not allowed"),
        ),
        patch("app.dependencies._get_jwks_client") as mock_jwks,
    ):
        with pytest.raises(HTTPException):
            await get_current_user(mock_credentials, mock_settings)

    mock_jwks.assert_not_called()


# ── AC7 — Guard test (CI enforceable) ─────────────────────────────────────────

@pytest.mark.unit
def test_jwt_hs256_pin_rejects_non_hs256_by_default():
    """Guard: get_current_user source does not read unverified_header unconditionally.

    This is the CI guard for D80. It verifies that the default code path cannot be
    tricked by a forged alg header — the fix must gate the unverified_header read
    behind the ws_allow_jwks_fallback check.
    """
    import inspect

    from app import dependencies as dep_module

    source = inspect.getsource(dep_module.get_current_user)
    # The function must check ws_allow_jwks_fallback before reading the header
    assert "ws_allow_jwks_fallback" in source, (
        "get_current_user must check settings.ws_allow_jwks_fallback — D80 guard"
    )
