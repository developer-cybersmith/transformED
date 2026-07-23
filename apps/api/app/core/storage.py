"""
Storage-bucket startup assertion shared by the FastAPI lifespan and the ARQ
worker (AC-7, Story 2-0 + review decision D1).

Buckets are provisioned by migration 20260710000000_storage_buckets.sql.
A missing OR misconfigured (public) bucket must fail the deploy at process
startup — API and worker alike — not on the first upload.

All four buckets are PRIVATE: lesson content is the paid deliverable and is
served exclusively via signed URLs (media router), never public CDN URLs.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_BUCKETS: frozenset[str] = frozenset(
    {"source-pdfs", "lesson-images", "lesson-audio", "avatar-clips"}
)
"""Every storage bucket referenced by apps/api code. Must stay in lockstep
with the 20260710000000_storage_buckets.sql migration (enforced by
tests/unit/test_bucket_manifest.py)."""

_MISSING = object()


def _bucket_field(bucket: Any, field: str) -> Any:  # noqa: ANN401
    """Read `field` from a bucket entry that may be an object or a dict."""
    value = getattr(bucket, field, _MISSING)
    if value is _MISSING and isinstance(bucket, dict):
        value = bucket.get(field, _MISSING)
    return value


def assert_required_buckets(client: Any) -> None:  # noqa: ANN401
    """Fail fast unless every required bucket exists AND is private.

    Raises RuntimeError (never KeyError/AttributeError) with an actionable
    message on: storage API failure, malformed list_buckets entries, missing
    buckets, or required buckets left public (D1: paid lesson content must
    never be unauthenticated-fetchable / CDN-cached).

    Synchronous — call via ``asyncio.to_thread`` from async startup code.
    """
    try:
        buckets = client.storage.list_buckets()
    except Exception as exc:  # fail fast — a broken storage API is a broken deploy
        raise RuntimeError(f"Could not list Supabase storage buckets: {exc}") from exc

    visibility: dict[str, Any] = {}
    for bucket in buckets:
        name = _bucket_field(bucket, "name")
        if name is _MISSING or name is None:
            raise RuntimeError(
                "Malformed storage bucket entry from list_buckets() — "
                f"no 'name' attribute or key: {bucket!r}"
            )
        visibility[name] = _bucket_field(bucket, "public")

    missing = REQUIRED_BUCKETS - visibility.keys()
    if missing:
        raise RuntimeError(f"Missing storage buckets: {sorted(missing)} — apply migrations")

    public = sorted(
        name
        for name in REQUIRED_BUCKETS
        if visibility[name] is not False  # missing/unknown visibility fails too
    )
    if public:
        raise RuntimeError(
            f"Storage buckets must be private (public=false): {public} — "
            "lesson content is served via signed URLs only (Story 2-0, D1); "
            "re-apply 20260710000000_storage_buckets.sql or fix the bucket "
            "in the dashboard"
        )

    logger.info("Storage buckets verified (all private): %s", sorted(REQUIRED_BUCKETS))


def sign_storage_path(
    client: Any,  # noqa: ANN401
    bucket: str,
    path: str,
    expires_in: int = 3600,
) -> str | None:
    """Return a signed URL for a storage object, or None on any failure.

    Shared by media/router.py (Story 3-6) and content/router.py (Story 1-6)
    so the fragile "call create_signed_url, pull the signedURL key" logic
    lives in exactly one place. "signedURL" is the one key storage3 actually
    returns (matches the established pattern at providers/avatar/heygen.py).
    A missing/None key, or the call itself raising, are both treated as the
    object not existing — callers decide how to surface that (404 vs a
    degrade-to-empty fallback), this helper only ever returns the URL or None.
    """
    try:
        signed = client.storage.from_(bucket).create_signed_url(path, expires_in)
        return signed["signedURL"] or None
    except Exception:
        logger.warning("Signing failed for %s/%s", bucket, path, exc_info=True)
        return None
