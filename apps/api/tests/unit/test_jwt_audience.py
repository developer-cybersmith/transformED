"""
Unit tests for JWT audience verification in get_current_user (Story 2-0 AC-2).

Real Supabase access tokens carry aud="authenticated". These tests use the
REAL pyjwt package (no stubs) and call get_current_user directly with a
mocked HTTPAuthorizationCredentials object, so the actual
`jwt.decode(..., audience="authenticated")` path in app.dependencies runs.

Verified against pyjwt 2.13: when `audience=` is passed, a token with a wrong
aud raises InvalidAudienceError and a token with NO aud raises
MissingRequiredClaimError — both subclasses of InvalidTokenError, so the
existing handler maps both to HTTP 401.
"""

from __future__ import annotations

import asyncio
from typing import Any

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.dependencies import get_current_user

TEST_SECRET = "test-jwt-secret-that-is-long-enough-32-bytes"

FAKE_SUB = "550e8400-e29b-41d4-a716-446655440000"


class _StubSettings:
    """Minimal settings stand-in — get_current_user only reads the JWT secret."""

    supabase_jwt_secret = TEST_SECRET


def _encode(claims: dict[str, Any]) -> str:
    import time

    now = int(time.time())
    payload: dict[str, Any] = {"sub": FAKE_SUB, "exp": now + 3600, "iat": now, **claims}
    # Tests express "no aud" by passing aud=None
    if payload.get("aud") is None:
        payload.pop("aud", None)
    return pyjwt.encode(payload, TEST_SECRET, algorithm="HS256")


def _call_get_current_user(token: str) -> dict[str, Any]:
    """Invoke the real dependency with a mocked bearer-credentials object."""
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(get_current_user(credentials, _StubSettings()))  # type: ignore[arg-type]


# ── AC-2 (a): correct audience is accepted ────────────────────────────────────


@pytest.mark.unit
def test_token_with_authenticated_aud_accepted() -> None:
    """Token carrying aud='authenticated' + sub/exp/iat decodes to the payload."""
    token = _encode({"aud": "authenticated", "email": "test@example.com"})

    payload = _call_get_current_user(token)

    assert payload["sub"] == FAKE_SUB
    assert payload["aud"] == "authenticated"
    assert payload["email"] == "test@example.com"


# ── AC-2 (b): wrong audience is rejected ──────────────────────────────────────


@pytest.mark.unit
def test_token_with_wrong_aud_rejected_401() -> None:
    """Token with aud != 'authenticated' is rejected with HTTP 401."""
    token = _encode({"aud": "wrong"})

    with pytest.raises(HTTPException) as exc_info:
        _call_get_current_user(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


# ── AC-2 (c): missing audience is rejected ────────────────────────────────────


@pytest.mark.unit
def test_token_with_no_aud_rejected_401() -> None:
    """Token with NO aud claim is rejected with HTTP 401.

    PyJWT raises MissingRequiredClaimError('aud') when audience= is passed but
    the token carries no aud claim — a subclass of InvalidTokenError, so the
    existing handler maps it to 401.
    """
    token = _encode({"aud": None})

    # Sanity: the token really has no aud claim
    assert "aud" not in pyjwt.decode(
        token, TEST_SECRET, algorithms=["HS256"], options={"verify_aud": False}
    )

    with pytest.raises(HTTPException) as exc_info:
        _call_get_current_user(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


# ── Exception-hierarchy guard (documents why no new except branch is needed) ──


@pytest.mark.unit
def test_audience_errors_are_invalid_token_error_subclasses() -> None:
    """Both audience failure modes are caught by the jwt.InvalidTokenError handler."""
    assert issubclass(pyjwt.InvalidAudienceError, pyjwt.InvalidTokenError)
    assert issubclass(pyjwt.MissingRequiredClaimError, pyjwt.InvalidTokenError)
