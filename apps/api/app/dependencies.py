"""
FastAPI dependency injection helpers.

Re-export everything a route handler might need so routes only ever
import from this single module.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import get_settings
from app.core.redis import get_redis

# Re-export for use in route type annotations
__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_jwks_client",
    "get_redis",
    "get_settings",
]

_bearer_scheme = HTTPBearer(auto_error=True)


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    """Return a process-wide cached PyJWKClient for this Supabase project's signing keys.

    Story 4-17: Supabase projects on asymmetric JWT signing keys (ES256) invalidate the
    old "decode with a static shared secret" approach — the legacy SUPABASE_JWT_SECRET no
    longer signs tokens once a project has migrated. This resolves the current signing
    key from the project's public JWKS endpoint instead.

    Two layers of caching keep this "local" in the sense CLAUDE.md/Epic 4's DoD require
    (no remote call per request, <5ms after warmup):
    - @lru_cache here means the SAME PyJWKClient instance is reused for the life of the
      process — it is never rebuilt per request.
    - cache_keys=True on the client itself caches the fetched public key by `kid`, so only
      the first verification after a cold start touches the network.
    """
    settings = get_settings()
    return PyJWKClient(
        f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    jwks_client: Annotated[PyJWKClient, Depends(get_jwks_client)],
) -> dict[str, Any]:
    """Verify a Supabase-issued JWT locally against the project's published signing keys.

    Never makes a remote *auth* call (no call to Supabase's /auth/v1/user endpoint) — the
    JWKS public-key lookup is cached (see get_jwks_client) so this stays a fast, local
    check after the first request. Raises HTTP 401 on any validation failure.

    Returns the decoded JWT payload (includes sub, email, role, app_metadata, etc.).
    """
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
    except jwt.PyJWKClientError:
        # Unrecognized `kid`, or the JWKS endpoint was unreachable — never a 500; a
        # client presenting a token we can't resolve a key for is indistinguishable
        # from an invalid token.
        raise credentials_exception from None

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=[signing_key.algorithm_name],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError:
        raise credentials_exception from None

    # Supabase encodes the user id in "sub"
    if not payload.get("sub"):
        raise credentials_exception

    return payload


# ── Annotated shorthands ──────────────────────────────────────────────────────

CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
"""Type alias: inject the current user's decoded JWT payload."""
