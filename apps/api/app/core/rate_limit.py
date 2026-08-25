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
from limits.storage import storage_from_string
from limits.storage.memory import MemoryStorage
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
            # D64 — branch on `alg` exactly like `dependencies.get_current_user`
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


# Single source of truth for the resolved storage target, read once at import
# time — `limiter` below and `assert_rate_limit_storage_configured` both read
# THIS constant (never `os.environ` independently a second time), so the two
# can never diverge if either is ever refactored (Review Finding, Story 5-4).
_RATE_LIMIT_STORAGE_URI = os.environ.get("RATE_LIMIT_STORAGE_URL", "memory://")

limiter = Limiter(
    key_func=_get_user_key,
    storage_uri=_RATE_LIMIT_STORAGE_URI,
    headers_enabled=True,
    retry_after="delta-seconds",
)


def assert_rate_limit_storage_configured(*, debug: bool, storage_uri: str | None = None) -> None:
    """D49 — fail fast if the shared rate limiter is running on unshared,
    per-process storage outside local/dev use.

    Resolves `storage_uri` through the SAME factory `limits`/`slowapi` use to
    build the real `Limiter` (`limits.storage.storage_from_string`) and checks
    the resulting object's real type, rather than string-matching the literal
    default `"memory://"` — a plain equality check misses non-canonical
    variants (empty string, case, leading/trailing whitespace, a URI suffix
    like `"memory://foo"`) that all still resolve to a real, unshared
    `MemoryStorage` (Review Finding, Story 5-4: empirically confirmed every
    one of those variants builds `MemoryStorage` via this exact factory,
    silently bypassing a naive string check).

    fly.toml's `api` process group runs with `auto_start_machines = true` and
    no fixed replica count (ADR-001 §2 calls the API "bursty and
    request-scaled") — more than one live machine is the expected case, not
    an edge case — so any input that resolves to in-process storage silently
    turns the configured "5/minute" (or "3/minute;20/hour") ceiling into N
    times looser, with no error and no log line above whatever level the
    process happens to run at. `debug=True` (local, single-process
    development) is the only exemption — mirrors the existing
    `assert_required_buckets` startup-assertion pattern
    (`apps/api/app/core/storage.py`, AC-7/Story 2-0/D1).
    """
    if storage_uri is None:
        storage_uri = _RATE_LIMIT_STORAGE_URI
    if debug:
        return
    resolved = storage_from_string(storage_uri or "memory://")
    if isinstance(resolved, MemoryStorage):
        raise RuntimeError(
            f"RATE_LIMIT_STORAGE_URL resolves to in-process 'memory://' "
            f"rate-limit storage (got {storage_uri!r}) outside debug mode -- "
            "refusing to start. Each API process would enforce its own "
            "independent counter, silently multiplying every configured "
            "rate-limit ceiling by however many processes/replicas are "
            "running (D49, docs/DEFECT-REGISTER.md). Set "
            "RATE_LIMIT_STORAGE_URL to a shared Redis URL (see "
            "docs/decisions/ADR-001-india-region-migration-topology.md §4 "
            "for the current Redis-location decision), or set DEBUG=true "
            "for local single-process development only."
        )
