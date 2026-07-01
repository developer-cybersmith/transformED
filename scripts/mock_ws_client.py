#!/usr/bin/env python3
"""Mock WebSocket client for local smoke-testing the Dev 4 WebSocket endpoint.

Usage:
    python scripts/mock_ws_client.py
    python scripts/mock_ws_client.py --session-id <uuid>
    python scripts/mock_ws_client.py --host ws://localhost:8001

Dependency note: requires `websockets` (pip install websockets).
This package is NOT listed in apps/api/pyproject.toml — install it manually
in your dev environment before running this script.
"""
import argparse
import asyncio
import json
import sys
import uuid

import websockets
import websockets.exceptions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mock WebSocket smoke-test client")
    parser.add_argument(
        "--session-id",
        default=str(uuid.uuid4()),
        help="Session UUID (default: random uuid4)",
    )
    parser.add_argument(
        "--host",
        default="ws://localhost:8000",
        help="WebSocket host base URL (default: ws://localhost:8000)",
    )
    return parser.parse_args()


async def run(session_id: str, host: str) -> None:
    uri = f"{host}/ws/{session_id}"
    print(f"Connecting to {uri} ...")

    try:
        async with websockets.connect(uri) as ws:
            # ── session_start ─────────────────────────────────────────────────
            await ws.send(json.dumps({"type": "session_start"}))
            print("[SENT] session_start")

            await asyncio.sleep(0.5)

            # ── attention_signal (shape from packages/shared/types/ws.ts) ─────
            await ws.send(json.dumps({
                "type": "attention_signal",
                "payload": {
                    "session_id": session_id,
                    "quiz_accuracy": 0.85,
                    "teachback_score": None,
                    "behavioral_score": 0.9,
                    "head_pose_score": 0.75,
                    "blink_rate": 0.3,
                },
            }))
            print("[SENT] attention_signal")

            # ── ping ──────────────────────────────────────────────────────────
            await ws.send(json.dumps({"type": "ping"}))
            print("[SENT] ping")

            # ── collect responses for 2 s ─────────────────────────────────────
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    print(f"[RECV] {json.dumps(json.loads(raw), indent=2)}")
            except asyncio.TimeoutError:
                print("[INFO] No more messages in 2s window")

    except ConnectionRefusedError:
        print(f"[ERROR] Could not connect to {uri}. Is the server running?")
        sys.exit(1)
    except websockets.exceptions.WebSocketException as exc:
        print(f"[ERROR] WebSocket error: {exc}")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.session_id, args.host))
