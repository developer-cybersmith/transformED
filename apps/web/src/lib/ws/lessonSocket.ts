import type { ClientMessage, ErrorMessage, ServerMessage } from '@hie/shared/types/ws';
import type { LocalControlOut } from './wireTypes';

export type LessonSocketStatus = 'connecting' | 'open' | 'closed';

export interface LessonSocketHandlers {
  onServerMessage: (msg: ServerMessage) => void;
  onStatusChange?: (status: LessonSocketStatus) => void;
}

const MAX_RECONNECT_ATTEMPTS = 5;

/**
 * Real WebSocket client for /ws/{session_id} (Dev 4's FastAPI tutor server).
 *
 * The onmessage handler is the ONLY place in the app that sees a wire frame that
 * doesn't conform to the frozen @hie/shared/types/ws contract (flat error, flat
 * pong) — everything it forwards to handlers.onServerMessage is a real ServerMessage.
 * See docs/ws-message-contract.md for the live wire protocol this normalizes against.
 */
export class LessonSocket {
  private ws: WebSocket | null = null;
  private sessionId = '';
  /** Forward-compatibility only — the backend endpoint takes no auth param today. */
  private token = '';
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private manuallyClosed = false;
  /** Set once session_start has been sent for this connect() call; never reset by
   *  internal reconnects — resending it mid CHECKING_IN/QUIZZING forces the backend
   *  back to TEACHING (see graph.py route_from_checking_in / route_from_quizzing). */
  private sessionStarted = false;

  constructor(private handlers: LessonSocketHandlers) {}

  connect(sessionId: string, token: string): void {
    this.sessionId = sessionId;
    this.token = token;
    this.manuallyClosed = false;
    this.sessionStarted = false;
    this.reconnectAttempts = 0;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.open();
  }

  private open(): void {
    const base = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
    const url = `${base}/ws/${this.sessionId}`;
    this.handlers.onStatusChange?.('connecting');
    const socket = new WebSocket(url);
    socket.onopen = this.handleOpen;
    socket.onmessage = this.handleMessage;
    socket.onclose = this.handleClose;
    this.ws = socket;
  }

  private handleOpen = (): void => {
    this.reconnectAttempts = 0;
    this.handlers.onStatusChange?.('open');
    if (!this.sessionStarted) {
      this.rawSend({ type: 'session_start' });
      this.sessionStarted = true;
    }
  };

  private handleMessage = (event: MessageEvent): void => {
    let data: unknown;
    try {
      data = JSON.parse(event.data);
    } catch {
      return; // malformed frame — drop silently, never crash the player
    }
    if (typeof data !== 'object' || data === null) return;

    // Flat error frame: {"error": "<msg>"}, no `type` field (docs/ws-message-contract.md).
    if ('error' in data && !('type' in data)) {
      const errorMessage: ErrorMessage = {
        type: 'error',
        payload: { code: 'SERVER_ERROR', message: String((data as { error: unknown }).error) },
      };
      this.handlers.onServerMessage(errorMessage);
      return;
    }

    const frame = data as { type?: string };
    if (frame.type === 'pong') return; // keepalive ack — no-op, never forwarded

    // Everything else is expected to conform to the frozen ServerMessage union.
    this.handlers.onServerMessage(data as ServerMessage);
  };

  private handleClose = (): void => {
    this.ws = null;
    this.handlers.onStatusChange?.('closed');
    if (this.manuallyClosed) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;
    const delay = 2 ** this.reconnectAttempts * 1000;
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  };

  /** Send a message from the frozen ClientMessage contract (currently AttentionSignalMessage). */
  send(msg: ClientMessage): void {
    this.rawSend(msg);
  }

  /** Send a flat local control frame (session_start, ping, flow events) — see wireTypes.ts. */
  sendControl(msg: LocalControlOut): void {
    this.rawSend(msg);
  }

  private rawSend(msg: ClientMessage | LocalControlOut): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  disconnect(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }
}
