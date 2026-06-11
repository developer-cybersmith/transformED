"""
ARQ worker entry point.

Run with:
    python -m arq app.workers.main.WorkerSettings

Or via the Makefile target:
    make worker

NOTE: Celery is BANNED per PRD §24.  This codebase uses ARQ exclusively.

WorkerSettings is read by the ARQ CLI to configure the worker process.
All job functions must be async coroutines that accept (ctx, *args, **kwargs).
"""

from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import get_settings
from app.workers.jobs.content_pipeline import content_pipeline_job

logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:  # type: ignore[type-arg]
    """Initialise shared resources for ARQ worker processes."""
    from app.core.db import init_supabase
    from app.core.redis import init_redis

    settings = get_settings()

    # Initialise Redis connection pool (separate from the arq pool)
    await init_redis(settings.redis_url)

    # Initialise Supabase client
    init_supabase(settings)

    logger.info("ARQ worker started — ready to process jobs")
    ctx["settings"] = settings


async def shutdown(ctx: dict) -> None:  # type: ignore[type-arg]
    """Cleanly close shared resources when the worker shuts down."""
    from app.core.redis import close_redis

    await close_redis()
    logger.info("ARQ worker shutdown complete")


def _build_redis_settings() -> RedisSettings:
    """Parse the REDIS_URL into an ARQ RedisSettings object."""
    settings = get_settings()
    url = settings.redis_url

    # arq requires explicit host/port rather than a URL string in some versions
    # We parse the URL and construct RedisSettings accordingly
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password or None,
        database=int(parsed.path.lstrip("/") or "0"),
    )


class WorkerSettings:
    """ARQ worker configuration class.

    ARQ reads this class (not an instance) to configure the worker.
    All class attributes are ARQ worker settings.
    """

    # ── Job registry ──────────────────────────────────────────────────────────
    functions = [
        content_pipeline_job,
        # Add future jobs here:
        # quiz_generation_job,
        # teachback_evaluation_job,
    ]

    # ── Redis connection ──────────────────────────────────────────────────────
    redis_settings = _build_redis_settings()

    # ── Worker tuning ─────────────────────────────────────────────────────────
    max_jobs: int = 5
    """Maximum number of concurrent jobs per worker process.
    Content pipeline is CPU/IO intensive — keep low to avoid OOM."""

    job_timeout: int = 600
    """Maximum wall-clock seconds a job may run before ARQ kills it (10 min)."""

    keep_result_seconds: int = 86_400
    """How long to keep job results in Redis (24 h)."""

    retry_jobs: bool = True
    """Allow failed jobs to be retried (ARQ's built-in retry mechanism)."""

    max_tries: int = 3
    """Maximum retry attempts per job (matches PRD §14 critical node rule)."""

    # ── Lifecycle hooks ───────────────────────────────────────────────────────
    on_startup = startup
    on_shutdown = shutdown

    # ── Queue names ───────────────────────────────────────────────────────────
    queue_name: str = "transformED:pipeline"
