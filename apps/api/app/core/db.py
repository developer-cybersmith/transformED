"""
Supabase client singleton.

IMPORTANT: We use the httpx transport (supabase-py's default since v2) which
bypasses PgBouncer.  Do NOT switch to asyncpg-direct connections — the
architecture requires going through Supabase's REST/PostgREST layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from supabase import Client, create_client

if TYPE_CHECKING:
    pass

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
