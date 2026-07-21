"""
Redis Pub/Sub listener for lesson_ready events.

Bridges the ARQ worker process (publisher) to the FastAPI WebSocket manager
(subscriber) by listening on the ``lesson_ready:*`` pattern and forwarding
decoded messages to connected clients via ``manager.send()``.

ARCHITECT DECISIONS implemented here:
  1. Dedicated ``Redis.from_url()`` connection — never shares the pool used
     by routes/services (pub/sub blocks the connection).
  2. Task lifetime bound to FastAPI lifespan via ``asyncio.create_task()``.
  3. Exponential back-off restart on crash; ``CancelledError`` propagates
     cleanly so shutdown completes without logging a spurious error.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING

from redis.asyncio import Redis

if TYPE_CHECKING:
    from app.core.websocket import ConnectionManager

logger = logging.getLogger(__name__)


async def _run_lesson_subscriber(manager: ConnectionManager) -> None:
    """Inner supervision loop — subscribe, listen, forward, recover.

    Must only be cancelled from outside (lifespan shutdown).  Any other
    exception triggers an exponential back-off reconnect cycle.
    """
    from app.config import get_settings  # lazy — avoids circular at import time

    settings = get_settings()
    attempt: int = 0

    while True:
        _sub_conn: Redis | None = None
        try:
            # DECISION 1: dedicated connection, separate from the shared pool
            _sub_conn = Redis.from_url(settings.redis_url, decode_responses=True)
            pubsub = _sub_conn.pubsub()
            await pubsub.psubscribe("lesson_ready:*")
            logger.info("lesson_ready subscriber: psubscribed to lesson_ready:*")
            attempt = 0  # successful connect resets the back-off counter

            async for raw_msg in pubsub.listen():
                if raw_msg["type"] != "pmessage":
                    continue

                channel: str = raw_msg["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                data: str = raw_msg["data"]
                if isinstance(data, bytes):
                    data = data.decode()

                logger.info("lesson_ready subscriber: pmessage channel=%s", channel)

                session_id: str = channel.removeprefix("lesson_ready:")
                logger.info("lesson_ready subscriber: extracted session_id=%s", session_id)

                try:
                    message: dict = json.loads(data)
                except json.JSONDecodeError:
                    logger.error(
                        "lesson_ready subscriber: malformed JSON on channel=%s data=%r",
                        channel,
                        data,
                    )
                    continue

                await manager.send(session_id, message)
                logger.info(
                    "lesson_ready subscriber: manager.send called session_id=%s",
                    session_id,
                )

                # Caches payload.lesson — the REAL, schema-validated LessonPackage
                # produced by package_builder_node (Story 2-11, landed 2026-07-16),
                # not the old flat stub shape. Cache the lesson package so the
                # in-process intervention path can read the segment's
                # pre-generated messages with a single Redis GET (no DB at
                # intervention time). Best-effort — a cache failure must never
                # break message forwarding.
                try:
                    lesson = (message.get("payload") or {}).get("lesson")
                    if lesson is not None and _sub_conn is not None:
                        await _sub_conn.set(
                            f"lesson_package:{session_id}", json.dumps(lesson), ex=86_400
                        )
                except Exception:
                    logger.warning("lesson_package cache write failed for %s", session_id)

        except asyncio.CancelledError:
            raise  # DECISION 3: shutdown signal — do not restart
        except Exception:
            wait: float = min(2**attempt, 30)
            logger.exception("lesson subscriber crashed; reconnect in %.1fs", wait)
            if _sub_conn is not None:
                with contextlib.suppress(Exception):
                    await _sub_conn.aclose()
            await asyncio.sleep(wait)
            attempt += 1


async def start_lesson_ready_listener(manager: ConnectionManager) -> asyncio.Task:
    """Start the ``lesson_ready:*`` pub/sub listener as a background asyncio.Task.

    Called once during FastAPI lifespan startup (DECISION 2).  The returned
    task must be cancelled by the caller on shutdown.

    Args:
        manager: The ``ConnectionManager`` singleton to forward messages to.

    Returns:
        The running ``asyncio.Task`` — caller must ``task.cancel()`` on shutdown.
    """
    task: asyncio.Task = asyncio.create_task(
        _run_lesson_subscriber(manager),
        name="lesson_ready_subscriber",
    )
    logger.info("lesson_ready subscriber task started")
    return task
