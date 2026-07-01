"""
FastAPI dependency injection helpers.

Re-export everything a route handler might need so routes only ever
import from this single module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.core.redis import get_redis

if TYPE_CHECKING:
    from arq.connections import ArqRedis as ArqRedisType

# Re-export for use in route type annotations
__all__ = [
    "ArqRedis",
    "CurrentUser",
    "get_arq_redis",
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


async def get_arq_redis(request: Request) -> "ArqRedisType":
    """Inject the ARQ Redis pool from app state (for job enqueue only).

    Distinct from get_redis() which returns redis.asyncio.Redis.
    Only ArqRedis has .enqueue_job().
    """
    if not hasattr(request.app.state, "arq_redis"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue unavailable",
        )
    return request.app.state.arq_redis  # type: ignore[no-any-return]


# ── Annotated shorthands ──────────────────────────────────────────────────────

CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
"""Type alias: inject the current user's decoded JWT payload."""

ArqRedis = Annotated["ArqRedisType", Depends(get_arq_redis)]
"""Type alias: inject the ARQ job-enqueue pool."""
