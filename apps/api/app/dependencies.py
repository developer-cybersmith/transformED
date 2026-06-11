"""
FastAPI dependency injection helpers.

Re-export everything a route handler might need so routes only ever
import from this single module.
"""

from __future__ import annotations

from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.core.redis import get_redis

# Re-export for use in route type annotations
__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_redis",
    "get_settings",
]

_bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Verify Supabase JWT locally using PyJWT + SUPABASE_JWT_SECRET.

    Never makes a remote auth call.  Raises HTTP 401 on any validation failure.

    Returns the decoded JWT payload (includes sub, email, role, app_metadata, etc.).
    """
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
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
