"""
Per-user rate limiter for the content API.

The app-wide limiter in main.py keys on IP address (fine for most routes).
This module provides a JWT-sub-keyed limiter used by upload_lesson so that
the 5/minute upload cap is enforced per authenticated user, not per IP
(proxies and NAT would otherwise share the limit across many users).

Import from here in both main.py (to register the exception handler) and
content/router.py (to decorate the route). Never import from main.py into
router.py — circular import.
"""

from __future__ import annotations

import logging
import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def _get_user_key(request: Request) -> str:
    """Rate-limit key: JWT sub when present, IP address as fallback."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt as pyjwt

            from app.config import get_settings
            from app.dependencies import _get_jwks_client

            token = auth[7:]
            settings = get_settings()
            # Same options rationale on both branches below: both verifications
            # are already done by `get_current_user` before any handler runs,
            # so this decode exists ONLY to read `sub` for the bucket key.
            #
            # D52 — load-bearing, do not remove. Every Supabase token carries
            # `aud: "authenticated"`, and PyJWT raises InvalidAudienceError when
            # a token HAS an `aud` claim and no `audience=` is supplied. That
            # exception was swallowed by the `except` below, so this function
            # fell through to `get_remote_address` for EVERY authenticated
            # request: every user shared one IP-keyed bucket, and one caller
            # could exhaust the limit for everyone behind the same egress IP.
            # Silent, and invisible at anything above DEBUG.
            #
            # D59 — branch on `alg` exactly like `dependencies.get_current_user`
            # (a second, independent HS256-only decode drifted out of sync with
            # that function's dual HS256/JWKS support when Supabase projects
            # migrated to asymmetric "JWT Signing Keys" — every ES256/RS256
            # token raised InvalidAlgorithmError here and silently fell back to
            # IP-keying, reopening exactly the bucket-sharing gap D52 closed).
            unverified_header = pyjwt.get_unverified_header(token)
            if unverified_header.get("alg") == "HS256":
                payload = pyjwt.decode(
                    token,
                    settings.supabase_jwt_secret,
                    algorithms=["HS256"],
                    options={"verify_exp": False, "verify_aud": False},
                )
            else:
                jwks_client = _get_jwks_client(settings)
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                payload = pyjwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["ES256", "RS256"],
                    options={"verify_exp": False, "verify_aud": False},
                )
            sub: str | None = payload.get("sub")
            if sub:
                return f"user:{sub}"
            logger.warning("rate-limit key: token carried no `sub`; falling back to IP")
        except Exception:  # noqa: BLE001
            # WARNING, not DEBUG: reaching here means the limit is no longer
            # per-user, which is a security posture change, not a detail.
            logger.warning("rate-limit key JWT decode failed; falling back to IP", exc_info=True)
    return get_remote_address(request)


limiter = Limiter(
    key_func=_get_user_key,
    storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URL", "memory://"),
    headers_enabled=True,
    retry_after="delta-seconds",
)
