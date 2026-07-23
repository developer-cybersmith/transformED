"""
Supabase client singleton.

IMPORTANT: We use the httpx transport (supabase-py's default since v2) which
bypasses PgBouncer.  Do NOT switch to asyncpg-direct connections — the
architecture requires going through Supabase's REST/PostgREST layer.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from supabase import Client, create_client

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def init_supabase(settings: Settings | None = None) -> Client:
    """Initialise the Supabase client with an explicit httpx transport.

    Uses service-role key so server-side operations bypass Row Level Security
    where needed.  The httpx transport is the default in supabase-py >=2.4 and
    must NOT be replaced with asyncpg — PgBouncer incompatibility.
    """
    global _supabase_client  # noqa: PLW0603

    if _supabase_client is not None:
        return _supabase_client

    if settings is None:
        settings = get_settings()

    # supabase-py v2 uses httpx internally; we surface it explicitly so
    # future maintainers understand the transport choice is deliberate.
    _supabase_client = create_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_service_role_key,
        # httpx transport is the default — explicit for clarity
    )

    logger.info("Supabase client initialised (httpx transport, service-role key)")
    return _supabase_client


def get_supabase() -> Client:
    """Return the singleton Supabase client.

    Initialises on first call.  Safe to call from any coroutine —
    supabase-py v2 client is thread/async-safe for reads.
    """
    global _supabase_client  # noqa: PLW0603

    if _supabase_client is None:
        _supabase_client = init_supabase()

    return _supabase_client


# ── Typed response-boundary helpers ───────────────────────────────────────────
# postgrest types a response's `.data` as a recursive JSON union and a
# `.single()`/`.maybe_single()` execute() as `... | None`, so any `.data`,
# `.get(...)`, or `[key]` access trips mypy's union-attr/index/call-overload
# even though the code is correct at runtime. These helpers narrow that boundary
# in ONE place. They are pure narrowing — `cast` has ZERO runtime effect; the
# returned value is exactly `resp.data` (or None/[] when there is no data).


def single_row(resp: Any) -> dict[str, Any] | None:  # noqa: ANN401 — postgrest response type varies
    """Return a single-row response's `.data` as a typed dict, or None.

    Zero behavior change: equivalent to `resp.data` — `cast` only informs the
    type checker of the shape postgrest's recursive JSON return type obscures.
    """
    if resp is None:
        return None
    return cast("dict[str, Any] | None", resp.data)


def rows(resp: Any) -> list[dict[str, Any]]:  # noqa: ANN401 — postgrest response type varies
    """Return a multi-row response's `.data` as a typed list of dicts (or []).

    Zero behavior change beyond treating a missing/None payload as an empty
    list (a select's `.data` is a list at runtime); `cast` is a no-op.
    """
    if resp is None:
        return []
    data = resp.data
    return cast("list[dict[str, Any]]", data) if data is not None else []
