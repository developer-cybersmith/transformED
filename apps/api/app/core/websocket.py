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
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

# Client-drivable tutor lifecycle events accepted as inbound WS control messages (same category as
# "ping" / "session_start" — flat control messages, not the ws.ts payload union). Server/engine-only
# events (distraction_detected, fatigue_detected) and admin events (session_reset) are NOT
# here, so a client cannot drive them. Mirrors service._CLIENT_DRIVABLE_EVENTS.
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
                logger.warning(
                    "reconnect state sync send failed for %s — dropping socket", session_id
                )
                self.disconnect(websocket, session_id)
        logger.info(
            "WS connected: session=%s  total_sessions=%d", session_id, len(self._connections)
        )

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
                await _handle_session_start(session_id)

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

    If a ``tutor_state:{session_id}`` already exists, this is a reconnect — return the stored
    state so the caller can push ``state_sync`` to the client; the session is NOT reset.
    Otherwise initialise a fresh session and return ``None``.

    Never raises — the WebSocket handshake must not fail on a Redis blip (degrade to fresh init).
    """
    try:
        from app.core.redis import get_redis

        existing = await get_redis().get(f"tutor_state:{session_id}")
        if existing:
            state = existing.decode() if isinstance(existing, (bytes, bytearray)) else str(existing)
            logger.info("WS reconnect: session=%s restoring state=%s", session_id, state)
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
    ``accept()`` handshake, so the whole body is best-effort and never
    re-raises.
    """
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        await redis.set(f"tutor_state:{session_id}", "IDLE", ex=86400)
        await redis.set(f"tutor_distraction_count:{session_id}", "0", ex=86400)
        await redis.delete(f"tutor_cooldown:{session_id}")
        await redis.delete(f"tutor_fatigue_fired:{session_id}")
        await redis.delete(
            f"session:{session_id}:segment_index"
        )  # reset segment pointer for a reused id
        logger.info("WS session initialised: session=%s", session_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to init session state for %s: %s", session_id, e)


# ── Dispatch helpers ───────────────────────────────────────────────────────────


async def _handle_session_start(session_id: str) -> None:
    """Dispatch a ``session_start`` event → IDLE → TEACHING transition.

    Imported lazily to avoid circular imports between core and modules.
    Mirrors the error contract of ``_handle_attention_signal``: never re-raises.
    """
    try:
        # Lazy import — tutor module depends on core, not the other way round.
        # Go through the service layer (mirrors _handle_attention_signal); start_session
        # calls dispatch_event(session_id, "session_start") → IDLE → TEACHING.
        from app.modules.tutor.service import start_session

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
        from app.modules.tutor.service import advance_tutor_state

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
        from app.modules.tutor.service import process_attention_signal

        result = await process_attention_signal(session_id=session_id, signal=payload)
        await manager.send(
            session_id,
            # PRD §18: never expose raw clinical/CES scores to the student client — ack only.
            {"type": "attention_ack", "payload": {"session_id": session_id, "status": "ok"}},
        )
    except ImportError:
        # Tutor service not yet implemented — log and skip gracefully
        logger.debug(
            "Tutor service not available yet — attention signal dropped for session %s", session_id
        )
    except Exception:
        logger.exception("Error processing attention signal for session %s", session_id)
