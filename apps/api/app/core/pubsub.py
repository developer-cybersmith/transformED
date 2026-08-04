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
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis

if TYPE_CHECKING:
    from app.core.websocket import ConnectionManager

logger = logging.getLogger(__name__)


async def _sessions_awaiting(lesson_id: str) -> list[str]:
    """Session ids to push `lesson_ready:{lesson_id}` to (D34, Story 1-15).

    `sessions.lesson_id` is `uuid NOT NULL REFERENCES lessons(lesson_id)
    ON DELETE CASCADE` and is indexed (`20260611000000_initial_schema.sql:177`,
    `:300`), so Postgres already knows who is waiting. Two alternatives were
    rejected and should not be reintroduced:

    * a `lesson_waiters:{lesson_id}` Redis set — `content_pipeline.py:102,168`
      describes one as Dev 4's fan-out, but it **does not exist**: no writer, no
      reader, no key, only comments. Building it would put a second source of
      truth beside a column that is already correct and indexed.
    * re-keying the channel by session — D23 made it lesson-keyed deliberately,
      because the ARQ worker knows no session at publish time.

    Never raises. This runs inside the subscriber's listen loop, and a Supabase
    blip must not tear down the only path that delivers lesson-ready events; an
    empty list degrades to "nobody was waiting", which is already a normal
    outcome the caller handles.
    """
    try:
        from app.core.db import get_supabase, rows

        resp = (
            get_supabase()
            .table("sessions")
            .select("session_id")
            .eq("lesson_id", lesson_id)
            .execute()
        )
        return [str(r["session_id"]) for r in rows(resp) if r.get("session_id")]
    except Exception:
        logger.exception(
            "lesson_ready: could not resolve waiting sessions for lesson_id=%s — "
            "no push will be delivered for this lesson",
            lesson_id,
        )
        return []


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

                # D34 — this is a LESSON id, and calling it `session_id` was the
                # entire defect. The channel is lesson-keyed by design (D23): the
                # ARQ worker knows no session. `ConnectionManager` keys
                # `_connections` by the `/ws/{session_id}` path param, so passing
                # a lesson id to `manager.send()` matched nothing, iterated an
                # empty list and returned silently — no error, no failed-delivery
                # log, and a reassuring "manager.send called" line that named the
                # wrong id. A variable whose name lies is how this survived review.
                lesson_id: str = channel.removeprefix("lesson_ready:")

                try:
                    message: dict[str, Any] = json.loads(data)
                except json.JSONDecodeError:
                    logger.error(
                        "lesson_ready subscriber: malformed JSON on channel=%s data=%r",
                        channel,
                        data,
                    )
                    continue

                session_ids = await _sessions_awaiting(lesson_id)

                if not session_ids:
                    # NORMAL, not an error: a student who closed the tab before
                    # generation finished has no session row. Logged distinctly
                    # from a delivery failure — the old code could not tell those
                    # apart, which is precisely why a 100%-failure path looked
                    # healthy for weeks.
                    logger.info(
                        "lesson_ready: lesson_id=%s ready, 0 sessions waiting — nothing to push",
                        lesson_id,
                    )
                else:
                    for session_id in session_ids:
                        await manager.send(session_id, message)
                    logger.info(
                        "lesson_ready: lesson_id=%s delivered to %d session(s): %s",
                        lesson_id,
                        len(session_ids),
                        ",".join(session_ids),
                    )

                # Caches payload.lesson — the REAL, schema-validated LessonPackage
                # produced by package_builder_node (Story 2-11, landed 2026-07-16),
                # not the old flat stub shape. Cache the lesson package so the
                # in-process intervention path can read the segment's
                # pre-generated messages with a single Redis GET (no DB at
                # intervention time). Best-effort — a cache failure must never
                # break message forwarding.
                #
                # One entry PER WAITING SESSION. `_seed_learner_tier`
                # (`core/websocket.py:279`) and `_segment_intervention_messages`
                # (`modules/tutor/service.py:253`) both read
                # `lesson_package:{session_id}`, and their key shape is correct —
                # it was this writer that used a lesson id, so both consumers
                # missed on every lesson ever generated. Fix the writer, not the
                # readers (D34; they are Dev 3 / Dev 4 files).
                #
                # KNOWN LIMITATION (D55): written at publish time only, so a
                # session STARTED AFTER the lesson is already `ready` gets no
                # entry and `_seed_learner_tier` silently returns.
                try:
                    lesson = (message.get("payload") or {}).get("lesson")
                    if lesson is not None and _sub_conn is not None and session_ids:
                        blob = json.dumps(lesson)
                        for session_id in session_ids:
                            await _sub_conn.set(f"lesson_package:{session_id}", blob, ex=86_400)
                except Exception:
                    logger.warning("lesson_package cache write failed for lesson_id=%s", lesson_id)

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


async def start_lesson_ready_listener(manager: ConnectionManager) -> asyncio.Task[Any]:
    """Start the ``lesson_ready:*`` pub/sub listener as a background asyncio.Task.

    Called once during FastAPI lifespan startup (DECISION 2).  The returned
    task must be cancelled by the caller on shutdown.

    Args:
        manager: The ``ConnectionManager`` singleton to forward messages to.

    Returns:
        The running ``asyncio.Task`` — caller must ``task.cancel()`` on shutdown.
    """
    task: asyncio.Task[Any] = asyncio.create_task(
        _run_lesson_subscriber(manager),
        name="lesson_ready_subscriber",
    )
    logger.info("lesson_ready subscriber task started")
    return task
