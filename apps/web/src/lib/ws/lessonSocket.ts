import type {
  ClientMessage,
  ServerMessage,
  TutorInterveneMessage,
  CesUpdateMessage,
  StateChangeMessage,
} from '@hie/shared/types/ws';

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline';

export interface LessonSocketCallbacks {
  onTutorIntervene: (payload: TutorInterveneMessage['payload']) => void;
  onCesUpdate: (payload: CesUpdateMessage['payload']) => void;
  onStateChange: (payload: StateChangeMessage['payload']) => void;
}

export class LessonSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private readonly maxAttempts = 5;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionId = '';
  private token = '';
  private callbacks: LessonSocketCallbacks | null = null;
  connectionStatus: ConnectionStatus = 'connecting';

  connect(sessionId: string, token: string, callbacks: LessonSocketCallbacks): void {
    this.sessionId = sessionId;
    this.token = token;
    this.callbacks = callbacks;

    const base = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000';
    const url = `${base}/ws/${sessionId}`;

    this.ws = new WebSocket(url, ['Bearer', token]);
    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.connectionStatus = 'connected';
    };
    this.ws.onmessage = (e) => this.handleMessage(e);
    this.ws.onclose = () => this.handleClose();
  }

  private handleMessage(e: MessageEvent): void {
    try {
      const msg = JSON.parse(e.data as string) as ServerMessage;
      if (msg.type === 'tutor_intervene') {
        this.callbacks?.onTutorIntervene((msg as TutorInterveneMessage).payload);
      } else if (msg.type === 'ces_update') {
        this.callbacks?.onCesUpdate((msg as CesUpdateMessage).payload);
      } else if (msg.type === 'state_change') {
        this.callbacks?.onStateChange((msg as StateChangeMessage).payload);
      }
    } catch {
      // Malformed JSON from server — ignore silently
    }
  }

  private handleClose(): void {
    if (this.reconnectAttempts < this.maxAttempts) {
      const delay = Math.pow(2, this.reconnectAttempts) * 1000;
      this.connectionStatus = 'reconnecting';
      this.reconnectTimer = setTimeout(() => {
        this.reconnectAttempts++;
        this.connect(this.sessionId, this.token, this.callbacks!);
      }, delay);
    } else {
      this.connectionStatus = 'offline';
    }
  }

  send(msg: ClientMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(msg));
  }

  disconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.onclose = null; // prevent handleClose re-entry on explicit disconnect
      this.ws.close();
      this.ws = null;
    }
    this.reconnectAttempts = 0;
  }
}

export const lessonSocket = new LessonSocket();
