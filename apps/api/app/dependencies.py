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
    "AdminUser",
    "ApprovedUser",
    "ArqRedis",
    "CurrentUser",
    "get_arq_redis",
    "get_current_user",
    "require_admin",
    "require_approved_user",
    "get_redis",
    "get_settings",
]

_bearer_scheme = HTTPBearer(auto_error=False)

# Cached across requests — PyJWKClient fetches + caches Supabase's public signing
# keys itself (keyed by `kid`), so this is still zero remote calls per request in
# the steady state, only an occasional background refetch on key rotation.
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client(settings: Settings) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Verify a Supabase JWT locally — never makes a remote auth call per request.

    Supabase projects sign access tokens one of two ways depending on whether
    the project has migrated to asymmetric "JWT Signing Keys":
    - Legacy projects: HS256, verified against the static SUPABASE_JWT_SECRET.
    - Migrated projects (this one, confirmed via its JWKS endpoint returning an
      ES256 key): asymmetric, verified against Supabase's published public key
      set, fetched once and cached by PyJWKClient (not a per-request remote call).

    Branches on the token's own (unverified) `alg` header so both key types work
    without needing to know in advance which one a given project uses.

    Raises HTTP 401 on any validation failure (including missing Authorization header).
    Returns the decoded JWT payload (includes sub, email, role, app_metadata, etc.).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise credentials_exception from None

    try:
        if unverified_header.get("alg") == "HS256":
            payload: dict[str, Any] = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["sub", "exp", "iat"]},
            )
        else:
            jwks_client = _get_jwks_client(settings)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
                options={"require": ["sub", "exp", "iat"]},
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except (jwt.InvalidTokenError, jwt.PyJWKClientError):
        raise credentials_exception from None

    # Supabase encodes the user id in "sub"
    if not payload.get("sub"):
        raise credentials_exception

    return payload


async def require_admin(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Gate a route to admin users only.

    Admin check is a static email allowlist (`ADMIN_EMAILS` env var), not a
    DB flag — the minimal viable mechanism today (see Story 2-25 Dev Notes).
    The caller is already authenticated (get_current_user ran first); a
    non-admin gets 403, not 404/401, since they're a real authenticated user
    who is simply not authorized for this route.
    """
    email = current_user.get("email")
    if not email or email.lower() not in settings.admin_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_approved_user(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Gate a route to beta-approved users only.

    Self-serve signup is open, but the routes this guards (upload, onboarding
    diagnostic, teach-back) all trigger real OpenAI spend with no cost gate of
    their own — an unapproved signup could otherwise run up real API cost.

    Same minimal-viable static-allowlist mechanism as require_admin (see
    APPROVED_EMAILS in config.py) — deliberately not DB-backed: a boolean
    column on `users` would be writable by the user themselves under that
    table's existing "update own row" RLS policy (id = auth.uid(), no column
    restriction), which would let anyone self-approve. A static env-var
    allowlist has no such client-reachable write path at all.

    The caller is already authenticated (get_current_user ran first); a
    non-approved user gets 403, not 404/401, since they're a real
    authenticated user who is simply not yet approved for this route.
    """
    email = current_user.get("email")
    if not email or email.lower() not in settings.approved_emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account does not have access yet — contact the team for beta access.",
        )
    return current_user


async def get_arq_redis(request: Request) -> ArqRedisType:
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

AdminUser = Annotated[dict[str, Any], Depends(require_admin)]
"""Type alias: inject the current user's JWT payload, 403 if not an admin."""

ApprovedUser = Annotated[dict[str, Any], Depends(require_approved_user)]
"""Type alias: inject the current user's JWT payload, 403 if not beta-approved."""

ArqRedis = Annotated["ArqRedisType", Depends(get_arq_redis)]
"""Type alias: inject the ARQ job-enqueue pool."""
