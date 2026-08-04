"""
FastAPI application factory.

Usage:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arq.connections import RedisSettings

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.core.langfuse import get_langfuse
from app.core.rate_limit import limiter
from app.core.redis import close_redis, init_redis
from app.core.websocket import ws_router
from app.modules.admin.router import router as admin_router
from app.modules.analytics.router import router as analytics_router
from app.modules.assessment.router import router as assessment_router
from app.modules.auth.router import router as auth_router
from app.modules.content.router import router as content_router
from app.modules.media.router import router as media_router
from app.modules.tutor.router import router as tutor_router

logger = logging.getLogger(__name__)


def _build_arq_redis_settings() -> RedisSettings:
    from urllib.parse import urlparse

    from arq.connections import RedisSettings

    parsed = urlparse(get_settings().redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password or None,
        database=int(parsed.path.lstrip("/") or "0"),
        ssl=parsed.scheme == "rediss",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup / shutdown of shared resources."""
    settings = get_settings()

    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting HIE API...")

    # Redis (app-level redis-py pool)
    await init_redis(settings.redis_url)
    logger.info("Redis connection pool initialised")

    # ARQ pool (separate ArqRedis client — used only for job enqueue).
    # default_queue_name MUST match WorkerSettings.queue_name — both sides
    # import PIPELINE_QUEUE so the names cannot drift (AC-1, Story 2-0).
    from arq import create_pool

    from app.core.queues import PIPELINE_QUEUE

    app.state.arq_redis = await create_pool(
        _build_arq_redis_settings(),
        default_queue_name=PIPELINE_QUEUE,
    )
    logger.info("ARQ Redis pool initialised (queue=%s)", PIPELINE_QUEUE)

    # Supabase client + storage-bucket assertion (AC-7, Story 2-0 + D1).
    # Buckets are provisioned by migration 20260710000000_storage_buckets.sql;
    # a missing or public bucket must fail the deploy here, not the first upload.
    from app.core.db import init_supabase
    from app.core.storage import assert_required_buckets

    sb = init_supabase(settings)
    await asyncio.to_thread(assert_required_buckets, sb)

    # lesson_ready pub/sub listener (bridges ARQ worker -> WebSocket clients)
    from app.core.pubsub import start_lesson_ready_listener
    from app.core.websocket import manager as ws_manager

    _pubsub_task = await start_lesson_ready_listener(ws_manager)
    logger.info("lesson_ready pub/sub listener started")

    # Langfuse — initialise singleton so the first trace isn't delayed
    get_langfuse()
    logger.info("Langfuse host: %s", settings.langfuse_host)

    # Sentry (no-op when DSN is absent)
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
            environment="development" if settings.debug else "production",
        )
        logger.info("Sentry initialised")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down HIE API...")

    # Cancel pub/sub listener before closing the shared Redis pool
    _pubsub_task.cancel()
    try:
        await _pubsub_task
    except asyncio.CancelledError:
        pass
    logger.info("lesson_ready pub/sub listener stopped")

    if hasattr(app.state, "arq_redis"):
        await app.state.arq_redis.close()
        logger.info("ARQ Redis pool closed")

    try:
        await close_redis()
        logger.info("Redis connections closed")
    finally:
        try:
            await asyncio.to_thread(get_langfuse().flush)
            logger.info("Langfuse traces flushed")
        except Exception:
            logger.warning("Langfuse flush failed - some traces may be lost", exc_info=True)


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="HIE API",
        description="Human Intelligence Engine platform - Sprint 0",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # ── Module routers ────────────────────────────────────────────────────────
    app.include_router(auth_router, prefix="/api/auth")
    app.include_router(content_router, prefix="/api/content")
    app.include_router(media_router, prefix="/api/media")
    app.include_router(assessment_router, prefix="/api/assessment")
    app.include_router(analytics_router, prefix="/api/analytics")
    app.include_router(tutor_router, prefix="/api/tutor")
    app.include_router(admin_router, prefix="/api/admin")

    # ── WebSocket router ──────────────────────────────────────────────────────
    app.include_router(ws_router)

    # ── Health endpoint ───────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"], summary="Liveness probe")
    async def health(request: Request) -> dict[str, str]:  # noqa: RUF029
        return {"status": "ok", "version": app.version}

    return app


# Module-level app instance consumed by uvicorn
app = create_app()
