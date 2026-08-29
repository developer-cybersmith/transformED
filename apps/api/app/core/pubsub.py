"""
Redis Pub/Sub listeners bridging backend publishers to the FastAPI WebSocket
manager.

Two listeners share one generic forwarding loop (`_run_pubsub_forwarder`,
Story BR-1):

  * ``lesson_ready:*``        -- ARQ worker (publisher) -> connected clients.
  * ``generation_progress:*`` -- any pipeline node (future publisher, Dev 1's
    story) -> connected clients. Closes the Dev-4/transport half of W-D13:
    ``GenerationProgressMessage`` has existed in the frozen ``ws.ts`` union
    since Sprint 0 with no path anywhere that ever emitted it.

ARCHITECT DECISIONS implemented here (apply to BOTH listeners):
  1. Dedicated ``Redis.from_url()`` connection per listener -- never shares
     the pool used by routes/services (pub/sub blocks the connection), and
     never shares a connection between the two listeners either.
  2. Task lifetime bound to FastAPI lifespan via ``asyncio.create_task()``.
  3. Exponential back-off restart on crash; ``CancelledError`` propagates
     cleanly so shutdown completes without logging a spurious error.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis

if TYPE_CHECKING:
    from app.core.websocket import ConnectionManager

logger = logging.getLogger(__name__)

# Runs after a message has been forwarded: (message, session_ids, sub_conn, lesson_id) -> None.
# Must never raise -- a hook failure must not affect delivery, which has already happened.
OnMessageHook = Callable[[dict[str, Any], list[str], Redis, str], Awaitable[None]]


async def _sessions_awaiting(lesson_id: str) -> list[str]:
    """Session ids to push `{channel}:{lesson_id}` to (D34, Story 1-15).

    `sessions.lesson_id` is `uuid NOT NULL REFERENCES lessons(lesson_id)
    ON DELETE CASCADE` and is indexed (`20260611000000_initial_schema.sql:177`,
    `:300`), so Postgres already knows who is waiting. Two alternatives were
    rejected and should not be reintroduced:

    * a `lesson_waiters:{lesson_id}` Redis set — `content_pipeline.py:102,168`
      describes one as Dev 4's fan-out, but it **does not exist**: no writer, no
      reader, no key, only comments. Building it would put a second source of
      truth beside a column that is already correct and indexed.
    * re-keying the channel by session — D23 made it lesson-keyed deliberately,
      because the ARQ worker knows no session at publish time. Story BR-1's
      `generation_progress` listener reuses this same reasoning: a pipeline
      node knows the lesson it is generating, not any particular session.

    Never raises. This runs inside a subscriber's listen loop, and a Supabase
    blip must not tear down the only path that delivers events; an empty list
    degrades to "nobody was waiting", which is already a normal outcome the
    caller handles.
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
            "could not resolve waiting sessions for lesson_id=%s — no push will be delivered",
            lesson_id,
        )
        return []


async def _run_pubsub_forwarder(
    manager: ConnectionManager,
    *,
    channel_prefix: str,
    on_message: OnMessageHook | None = None,
) -> None:
    """Generic subscribe/decode/resolve/forward/back-off loop (Story BR-1).

    Extracted from what was originally `_run_lesson_subscriber`'s own loop
    body -- byte-identical behavior for that path (same log wording with
    `channel_prefix` substituted in, same back-off, same `_sessions_awaiting`
    call, same exception handling), verified by the full pre-existing
    `lesson_ready` test suite staying green after this extraction (Story
    BR-1, Task 1.7). `on_message` is an optional post-forward hook for a
    message-type-specific side effect -- `lesson_ready` uses it to cache the
    lesson package; `generation_progress` passes none.

    Must only be cancelled from outside (lifespan shutdown). Any other
    exception triggers an exponential back-off reconnect cycle.
    """
    from app.config import get_settings  # lazy — avoids circular at import time

    settings = get_settings()
    attempt: int = 0

    while True:
        _sub_conn: Redis | None = None
        try:
            # DECISION 1: dedicated connection, separate from the shared pool
            # AND from the other listener's own connection.
            _sub_conn = Redis.from_url(settings.redis_url, decode_responses=True)
            pubsub = _sub_conn.pubsub()
            await pubsub.psubscribe(f"{channel_prefix}:*")
            logger.info("%s subscriber: psubscribed to %s:*", channel_prefix, channel_prefix)
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

                logger.info("%s subscriber: pmessage channel=%s", channel_prefix, channel)

                # D34 — this is a LESSON id, never call it session_id. The channel
                # is lesson-keyed by design (D23): the publisher (ARQ worker for
                # lesson_ready, a pipeline node for generation_progress) knows no
                # session at publish time. `ConnectionManager` keys `_connections`
                # by the `/ws/{session_id}` path param, so passing a lesson id to
                # `manager.send()` would match nothing and fail silently — a
                # variable whose name lies is how this survived review once
                # already.
                lesson_id: str = channel.removeprefix(f"{channel_prefix}:")

                try:
                    message: dict[str, Any] = json.loads(data)
                except json.JSONDecodeError:
                    logger.error(
                        "%s subscriber: malformed JSON on channel=%s data=%r",
                        channel_prefix,
                        channel,
                        data,
                    )
                    continue

                session_ids = await _sessions_awaiting(lesson_id)

                if not session_ids:
                    # NORMAL, not an error: e.g. a student who closed the tab
                    # before generation finished has no session row. Logged
                    # distinctly from a delivery failure — the old lesson_ready
                    # code could not tell those apart, which is precisely why a
                    # 100%-failure path looked healthy for weeks.
                    logger.info(
                        "%s: lesson_id=%s ready, 0 sessions waiting — nothing to push",
                        channel_prefix,
                        lesson_id,
                    )
                else:
                    for session_id in session_ids:
                        await manager.send(session_id, message)
                    logger.info(
                        "%s: lesson_id=%s delivered to %d session(s): %s",
                        channel_prefix,
                        lesson_id,
                        len(session_ids),
                        ",".join(session_ids),
                    )

                if on_message is not None:
                    try:
                        await on_message(message, session_ids, _sub_conn, lesson_id)
                    except Exception:
                        logger.warning(
                            "%s: on_message hook failed for lesson_id=%s", channel_prefix, lesson_id
                        )

        except asyncio.CancelledError:
            raise  # DECISION 3: shutdown signal — do not restart
        except Exception:
            wait: float = min(2**attempt, 30)
            logger.exception("%s subscriber crashed; reconnect in %.1fs", channel_prefix, wait)
            if _sub_conn is not None:
                with contextlib.suppress(Exception):
                    await _sub_conn.aclose()
            await asyncio.sleep(wait)
            attempt += 1


async def _cache_lesson_package(
    message: dict[str, Any], session_ids: list[str], sub_conn: Redis, lesson_id: str
) -> None:
    """`lesson_ready`'s on_message hook — caches payload.lesson per waiting session.

    Caches payload.lesson — the REAL, schema-validated LessonPackage produced
    by package_builder_node (Story 2-11, landed 2026-07-16), not the old flat
    stub shape. Cache the lesson package so the in-process intervention path
    can read the segment's pre-generated messages with a single Redis GET (no
    DB at intervention time). Best-effort — a cache failure must never break
    message forwarding, which has already happened by the time this runs.
    One entry PER WAITING SESSION. `_seed_learner_tier` (`core/websocket.py`)
    and `_segment_intervention_messages` (`modules/tutor/service.py`) both
    read `lesson_package:{session_id}`, and their key shape is correct — it
    was this writer that used a lesson id, so both consumers missed on every
    lesson ever generated. Fix the writer, not the readers (D34; they are Dev
    3 / Dev 4 files).

    KNOWN LIMITATION (D55): written at publish time only, so a session
    STARTED AFTER the lesson is already `ready` gets no entry and
    `_seed_learner_tier` silently returns.
    """
    lesson = (message.get("payload") or {}).get("lesson")
    if lesson is not None and session_ids:
        blob = json.dumps(lesson)
        for session_id in session_ids:
            await sub_conn.set(f"lesson_package:{session_id}", blob, ex=86_400)


async def _run_lesson_subscriber(manager: ConnectionManager) -> None:
    """Inner supervision loop for `lesson_ready:*` — thin wrapper over the
    generic forwarder (Story BR-1 extraction), with the package-cache hook."""
    await _run_pubsub_forwarder(
        manager, channel_prefix="lesson_ready", on_message=_cache_lesson_package
    )


async def _run_generation_progress_subscriber(manager: ConnectionManager) -> None:
    """Inner supervision loop for `generation_progress:*` (Story BR-1).

    No caching side effect — `GenerationProgressMessage` is a transient
    status update, not a durable artifact like a lesson package. Nothing in
    `apps/api` publishes to this channel yet (Dev 1's future story); this
    listener exists so a publisher can be added without any WS-layer change.
    """
    await _run_pubsub_forwarder(manager, channel_prefix="generation_progress")


async def start_lesson_ready_listener(manager: ConnectionManager) -> asyncio.Task[Any]:
    """Start the ``lesson_ready:*`` pub/sub listener as a background asyncio.Task.

    Called once during FastAPI lifespan startup (DECISION 2). The returned
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


async def start_generation_progress_listener(manager: ConnectionManager) -> asyncio.Task[Any]:
    """Start the ``generation_progress:*`` pub/sub listener (Story BR-1).

    Mirrors `start_lesson_ready_listener` exactly. Called once during FastAPI
    lifespan startup; the returned task must be cancelled by the caller on
    shutdown.

    Args:
        manager: The ``ConnectionManager`` singleton to forward messages to.

    Returns:
        The running ``asyncio.Task`` — caller must ``task.cancel()`` on shutdown.
    """
    task: asyncio.Task[Any] = asyncio.create_task(
        _run_generation_progress_subscriber(manager),
        name="generation_progress_subscriber",
    )
    logger.info("generation_progress subscriber task started")
    return task
