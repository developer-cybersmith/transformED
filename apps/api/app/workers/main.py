"""
ARQ worker entry point.

Run with:
    python -m arq app.workers.main.WorkerSettings

Or via the Makefile target:
    make worker

NOTE: Celery is BANNED per PRD Â§24.  This codebase uses ARQ exclusively.

WorkerSettings is read by the ARQ CLI to configure the worker process.
All job functions must be async coroutines that accept (ctx, *args, **kwargs).
"""

from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import get_settings
from app.core.langfuse import get_langfuse
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

    # Initialise Langfuse singleton so the first pipeline trace isn't delayed
    get_langfuse()
    logger.info("Langfuse initialised (worker)")

    logger.info("ARQ worker started â€” ready to process jobs")
    ctx["settings"] = settings


async def shutdown(ctx: dict) -> None:  # type: ignore[type-arg]
    """Cleanly close shared resources when the worker shuts down."""
    from app.core.redis import close_redis

    try:
        await close_redis()
        logger.info("ARQ worker Redis connections closed")
    finally:
        try:
            get_langfuse().flush()
            logger.info("Langfuse traces flushed (worker)")
        except Exception:
            logger.warning("Langfuse flush failed on worker shutdown", exc_info=True)
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
        ssl=parsed.scheme == "rediss",
    )


class WorkerSettings:
    """ARQ worker configuration class.

    ARQ reads this class (not an instance) to configure the worker.
    All class attributes are ARQ worker settings.
    """

    # â”€â”€ Job registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    functions = [
        content_pipeline_job,
        # Add future jobs here:
        # quiz_generation_job,
        # teachback_evaluation_job,
    ]

    # â”€â”€ Redis connection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    redis_settings = _build_redis_settings()

    # â”€â”€ Worker tuning â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    max_jobs: int = 5
    """Maximum number of concurrent jobs per worker process.
    Content pipeline is CPU/IO intensive â€” keep low to avoid OOM."""

    job_timeout: int = 600
    """Maximum wall-clock seconds a job may run before ARQ kills it (10 min)."""

    keep_result_seconds: int = 86_400
    """How long to keep job results in Redis (24 h)."""

    retry_jobs: bool = True
    """Allow failed jobs to be retried (ARQ's built-in retry mechanism)."""

    max_tries: int = 3
    """Maximum retry attempts per job (matches PRD Â§14 critical node rule)."""

    # â”€â”€ Lifecycle hooks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    on_startup = startup
    on_shutdown = shutdown

    # â”€â”€ Queue names â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    queue_name: str = "hie:pipeline"

