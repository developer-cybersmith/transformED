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

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_user_key(request: Request) -> str:
    """Rate-limit key: JWT sub when present, IP address as fallback."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt as pyjwt

            from app.config import get_settings

            payload = pyjwt.decode(
                auth[7:],
                get_settings().supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": False},  # expiry already checked by get_current_user
            )
            sub: str | None = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:  # noqa: BLE001
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_get_user_key)
