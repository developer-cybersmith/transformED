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


class ConnectionManager:
    """Thread-safe (asyncio) multi-connection WebSocket manager."""

    def __init__(self) -> None:
        # session_id → list of active WebSocket connections
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept a new WebSocket and register it under *session_id*."""
        await websocket.accept()
        self._connections[session_id].append(websocket)
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


# ── Dispatch helpers ───────────────────────────────────────────────────────────


async def _handle_attention_signal(session_id: str, payload: dict[str, Any]) -> None:
    """Forward an attention signal to the tutor state machine.

    Imported lazily to avoid circular imports between core and modules.
    """
    try:
        # Lazy import — tutor module depends on core, not the other way round
        from app.modules.tutor.service import process_attention_signal  # type: ignore[import]

        await process_attention_signal(session_id=session_id, signal=payload)
    except ImportError:
        # Tutor service not yet implemented — log and skip gracefully
        logger.debug("Tutor service not available yet — attention signal dropped for session %s", session_id)
    except Exception:
        logger.exception("Error processing attention signal for session %s", session_id)
