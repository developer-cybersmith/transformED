"""
WebSocket connection manager and router.

Architecture
------------
- One ``ConnectionManager`` singleton handles all live sessions.
- Sessions are keyed by ``session_id`` (UUID string).
- Each session can have multiple concurrent connections (e.g. mobile + desktop).
- Incoming messages are dispatched to the appropriate domain service.

Message types (inbound from client)
-------------------------------------
``attention_signal``   Computer-vision attention data → forwarded to tutor service.

Message types (outbound from server)
--------------------------------------
``lesson_ready``       Content pipeline finished — lesson is ready to play.
``intervention``       Tutor engine triggers an intervention overlay.
``ping``               Keepalive.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

# Session IDs must be standard UUIDs (lowercase hex + hyphens). Validated at the route
# boundary to prevent Redis key-namespace traversal via crafted session_id values.
_SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# Client-drivable tutor lifecycle events accepted as inbound WS control messages (same category as
# "ping" / "session_start" — flat control messages, not the ws.ts payload union). Server/engine-only
# events (distraction_detected, fatigue_detected) and admin events (session_reset) are NOT here, so a
# client cannot drive them. Mirrors service._CLIENT_DRIVABLE_EVENTS.
_TUTOR_CLIENT_EVENTS = frozenset(
    {
        "segment_complete",
        "checkin_complete",
        "low_checkin_score",
        "quiz_trigger",
        "quiz_complete",
        "quiz_failed",
        "teachback_complete",
        "teachback_failed",
        "lesson_complete",
    }
)


class ConnectionManager:
    """Thread-safe (asyncio) multi-connection WebSocket manager."""

    def __init__(self) -> None:
        # session_id → list of active WebSocket connections
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept a new WebSocket and register it under *session_id*.

        Reconnect-aware: if a live tutor_state exists, restore it (push ``state_sync`` to the
        reconnecting client, no reset); otherwise initialise a fresh session.
        """
        await websocket.accept()
        self._connections[session_id].append(websocket)
        restored = await _restore_or_init_session(session_id)
        if restored is not None:
            # Sync the reconnecting client to the live state. Reuse the FROZEN ws.ts `state_change`
            # message (no transition → from == to); ws.ts has no `state_sync`, and inventing an
            # outbound type the client can't narrow would violate the §16 contract freeze.
            # Guarded: a dead socket must never break the handshake or leak a registry entry.
            try:
                await websocket.send_json(
                    {
                        "type": "state_change",
                        "payload": {
                            "session_id": session_id,
                            "from_state": restored,
                            "to_state": restored,
                        },
                    }
                )
            except Exception:
                logger.warning("reconnect state sync send failed for %s — dropping socket", session_id)
                self.disconnect(websocket, session_id)
        logger.info("WS connected: session=%s  total_sessions=%d", session_id, len(self._connections))

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Remove *websocket* from the session registry."""
        connections = self._connections.get(session_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self._connections.pop(session_id, None)
        logger.info("WS disconnected: session=%s  remaining=%d", session_id, len(connections))

    async def send(self, session_id: str, message: dict[str, Any]) -> None:
        """Send *message* to **all** connections for *session_id*."""
        connections = self._connections.get(session_id, [])
        dead: list[WebSocket] = []

        for ws in connections:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to send to ws in session %s — marking dead", session_id)
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, session_id)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast *message* to every connected session (admin / debug use)."""
        for session_id in list(self._connections.keys()):
            await self.send(session_id, message)


# Module-level singleton
manager = ConnectionManager()

# ── Router ─────────────────────────────────────────────────────────────────────
ws_router = APIRouter()


@ws_router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Main WebSocket endpoint for real-time session communication.

    Clients connect here for:
    - Sending attention / computer-vision signals to the tutor engine.
    - Receiving lesson_ready, intervention, and ping events from the server.
    """
    if not _SESSION_ID_RE.match(session_id):
        await websocket.close(code=4003)
        return
    await manager.connect(websocket, session_id)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "invalid JSON"})
                continue

            msg_type: str = payload.get("type", "")

            if msg_type == "attention_signal":
                await _handle_attention_signal(session_id, payload)

            elif msg_type == "session_start":
                # payload is the already-decoded json.loads(raw) dict — no re-parse needed.
                await _handle_session_start(session_id, payload=payload)

            elif msg_type in _TUTOR_CLIENT_EVENTS:
                await _handle_tutor_event(session_id, msg_type)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                logger.debug("Unknown WS message type '%s' from session %s", msg_type, session_id)
                await websocket.send_json({"error": f"unknown message type '{msg_type}'"})

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception:
        logger.exception("Unhandled error in WS endpoint for session %s", session_id)
        manager.disconnect(websocket, session_id)


# ── Session lifecycle ────────────────────────────────────────────────────────


async def _restore_or_init_session(session_id: str) -> str | None:
    """Reconnect-aware session bootstrap.

    If a ``tutor_state:{session_id}`` already exists, this is a reconnect — return the stored state so
    the caller can push ``state_sync`` to the client; the session is NOT reset. Otherwise initialise a
    fresh session and return ``None``.

    Tier seeding runs on BOTH paths so that a session which connected before the lesson package was
    cached can pick up its learner tier on the first reconnect after generation completes.

    Never raises — the WebSocket handshake must not fail on a Redis blip (degrade to fresh init).
    """
    try:
        from app.core.redis import get_redis  # type: ignore[import]

        existing = await get_redis().get(f"tutor_state:{session_id}")
        if existing:
            state = existing.decode() if isinstance(existing, (bytes, bytearray)) else str(existing)
            logger.info("WS reconnect: session=%s restoring state=%s", session_id, state)
            await _seed_learner_tier(session_id)
            return state
    except Exception:
        logger.warning("reconnect-state read failed for %s — initialising fresh", session_id)

    await _init_session_state(session_id)
    return None


async def _init_session_state(session_id: str) -> None:
    """Initialise per-session tutor Redis keys when a new WebSocket connects.

    Sets the starting tutor state to ``IDLE``, resets the distraction counter,
    and clears any stale cooldown / fatigue flags left over from a previous
    session that reused this ``session_id``.  State/counter carry a 24 h TTL.

    ``get_redis`` is imported lazily inside the function — no module-level
    imports in this file (avoids the core ↔ tutor circular import).

    Error contract: a Redis failure must never crash the WebSocket
    ``accept()`` handshake, so every block is best-effort and never re-raises.
    """
    try:
        from app.core.redis import get_redis  # type: ignore[import]

        redis = get_redis()
        await redis.set(f"tutor_state:{session_id}", "IDLE", ex=86400)
        await redis.set(f"tutor_distraction_count:{session_id}", "0", ex=86400)
        await redis.delete(f"tutor_cooldown:{session_id}")
        await redis.delete(f"tutor_fatigue_fired:{session_id}")
        await redis.delete(f"session:{session_id}:segment_index")  # reset segment pointer for a reused id
        logger.info("WS session initialised: session=%s", session_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to init session state for %s: %s", session_id, e)

    await _seed_learner_tier(session_id)


_VALID_TIERS: frozenset[str] = frozenset({"T1", "T2", "T3"})


async def _seed_learner_tier(session_id: str) -> None:
    """Best-effort learner tier seeding from the cached lesson package.

    Reads ``lesson_package:{session_id}`` from Redis.  If present and
    ``metadata.learner_tier`` is a valid tier string (T1/T2/T3), atomically
    writes ``session:{session_id}:learner_tier`` and
    ``session:{session_id}:qa_phase_seconds`` (both 24 h TTL).

    Security guards:
    - ``session_id`` is validated at the route boundary before this is called.
    - ``tier`` is validated against the allowlist before any Redis write.
    - ``metadata`` is type-checked to prevent AttributeError on non-dict payloads.
    - Both keys are written via a pipeline to avoid a half-seeded state on
      partial failure.

    Called from both ``_init_session_state`` (fresh connect) and the reconnect
    branch of ``_restore_or_init_session`` so that a session which connected
    before lesson generation completed can pick up its tier on reconnect.

    Never raises — a failure must not affect the WebSocket handshake.
    """
    try:
        import json as _json  # noqa: PLC0415

        from app.core.redis import get_redis  # type: ignore[import]
        from app.modules.tutor.service import qa_phase_seconds as _qa  # type: ignore[import]

        _redis = get_redis()
        raw_pkg = await _redis.get(f"lesson_package:{session_id}")
        if not raw_pkg:
            return
        pkg = _json.loads(raw_pkg)
        metadata = pkg.get("metadata")
        if not isinstance(metadata, dict):
            return
        tier = metadata.get("learner_tier")
        if tier not in _VALID_TIERS:
            return
        qa_secs = _qa(tier)
        pipe = _redis.pipeline(transaction=False)
        pipe.set(f"session:{session_id}:learner_tier", tier, ex=86400)
        pipe.set(f"session:{session_id}:qa_phase_seconds", str(qa_secs), ex=86400)
        await pipe.execute()
        logger.info("WS session learner tier=%s qa_phase=%ss for %s", tier, qa_secs, session_id)
    except Exception:  # noqa: BLE001
        logger.warning("learner tier seeding failed for %s — continuing without tier", session_id)


# ── Dispatch helpers ───────────────────────────────────────────────────────────


async def _handle_session_start(session_id: str, payload: dict[str, Any] | None = None) -> None:
    """Dispatch a ``session_start`` event → IDLE → TEACHING transition, optionally
    seeding the learner tier from the WebSocket payload first.

    Learner tier (Story 4-21 — WS override path)
    --------------------------------------------
    If the client sends a valid ``learner_tier`` (``T1``/``T2``/``T3``) in the
    ``session_start`` payload, it is written to ``session:{sid}:learner_tier`` and
    ``session:{sid}:qa_phase_seconds`` (24 h TTL — same keys as Story 4-19).

    Precedence: Story 4-19 seeds the tier from the cached lesson package during
    ``connect()``; this handler runs later (``session_start`` arrives *after* the
    connection is established), so a WS-payload tier overwrites the lesson-package
    value — the client holds the fresher student profile. An absent / ``None`` /
    unrecognised tier makes **no** write, so 4-19's value (if any) is preserved.

    Caveat (multi-connection, last-writer-wins): the "WS tier wins" ordering is
    guaranteed only *per connection*. ``ConnectionManager`` allows multiple
    connections per ``session_id`` (desktop + mobile), and 4-19 re-seeds on every
    connect / reconnect — so a second connection's 4-19 seed can land *after* this
    override and revert it to the lesson-package tier. This is accepted as
    last-writer-wins: the tier only tunes the Q&A-phase duration (no data/access
    impact) and any drift self-heals on the next ``session_start``. Coordinating
    the two writers is tracked as deferred work (code review 2026-07-23).

    Imported lazily to avoid circular imports between core and modules.
    Mirrors the error contract of ``_handle_attention_signal``: never re-raises.
    """
    # Tier override from the WS payload (best-effort; failure must not block dispatch).
    tier = (payload or {}).get("learner_tier")
    if isinstance(tier, str) and tier in _VALID_TIERS:
        try:
            from app.core.redis import get_redis  # type: ignore[import]  # noqa: PLC0415
            from app.modules.tutor.service import qa_phase_seconds as _qa  # type: ignore[import]  # noqa: PLC0415

            redis = get_redis()
            qa_secs = _qa(tier)
            # Write both keys atomically via a pipeline so a partial failure can never leave a
            # half-seeded (fresh tier + stale duration) pair — mirrors Story 4-19's
            # _seed_learner_tier invariant for these same keys.
            pipe = redis.pipeline(transaction=False)
            pipe.set(f"session:{session_id}:learner_tier", tier, ex=86400)
            pipe.set(f"session:{session_id}:qa_phase_seconds", str(qa_secs), ex=86400)
            await pipe.execute()
            logger.info(
                "[tutor:%s] learner_tier=%s qa_phase=%ss set from session_start WS payload",
                session_id,
                tier,
                qa_secs,
            )
        except Exception:  # noqa: BLE001
            logger.warning("learner tier WS seeding failed for %s — continuing", session_id)

    try:
        # Lazy import — tutor module depends on core, not the other way round.
        # Go through the service layer (mirrors _handle_attention_signal); start_session
        # calls dispatch_event(session_id, "session_start") → IDLE → TEACHING.
        from app.modules.tutor.service import start_session  # type: ignore[import]

        await start_session(session_id)
        logger.info("[tutor:%s] session_start dispatched → TEACHING", session_id)
    except Exception:
        logger.exception("session_start dispatch failed for %s", session_id)


async def _handle_tutor_event(session_id: str, event: str) -> None:
    """Dispatch a client-driven lifecycle event into the tutor FSM via the service layer.

    Imported lazily to avoid circular imports between core and modules. Errors are swallowed so a
    bad client message never crashes the WS receive loop (mirrors ``_handle_session_start``).
    """
    try:
        from app.modules.tutor.service import advance_tutor_state  # type: ignore[import]

        await advance_tutor_state(session_id, event)
        logger.info("[tutor:%s] client event dispatched: %s", session_id, event)
    except Exception:
        logger.exception("tutor event %s failed for %s", event, session_id)


async def _handle_attention_signal(session_id: str, payload: dict[str, Any]) -> None:
    """Forward an attention signal to the tutor state machine and ack the result.

    Imported lazily to avoid circular imports between core and modules.
    """
    try:
        # Lazy import — tutor module depends on core, not the other way round
        from app.modules.tutor.service import process_attention_signal  # type: ignore[import]

        result = await process_attention_signal(session_id=session_id, signal=payload)
        await manager.send(
            session_id,
            {"type": "attention_ack", "payload": {"session_id": session_id, "ces": result.ces}},
        )
    except ImportError:
        # Tutor service not yet implemented — log and skip gracefully
        logger.debug("Tutor service not available yet — attention signal dropped for session %s", session_id)
    except Exception:
        logger.exception("Error processing attention signal for session %s", session_id)
