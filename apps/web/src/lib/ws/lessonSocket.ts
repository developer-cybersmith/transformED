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
  onStatusChange?: (status: ConnectionStatus) => void; // P2: optional — hook wires this for reactive UI
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
    // P3: Tear down any live socket before replacing — prevents ghost onclose/onerror callbacks
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }

    this.sessionId = sessionId;
    this.token = token;
    this.callbacks = callbacks;

    // P9: Strip trailing slash — some reverse proxies reject //ws/ double-slash paths
    const base = (process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000').replace(/\/$/, '');
    const url = `${base}/ws/${sessionId}`;

    this.ws = new WebSocket(url, ['Bearer', token]);
    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus('connected');
    };
    this.ws.onmessage = (e) => this.handleMessage(e);
    this.ws.onclose = () => this.handleClose();
    this.ws.onerror = () => this.handleClose(); // P5: network errors also enter the reconnect path
  }

  private setStatus(s: ConnectionStatus): void {
    this.connectionStatus = s;
    this.callbacks?.onStatusChange?.(s);
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
    if (this.reconnectTimer !== null) return; // P5: prevent double-schedule from onerror+onclose
    if (this.reconnectAttempts < this.maxAttempts) {
      const delay = Math.pow(2, this.reconnectAttempts) * 1000;
      this.setStatus('reconnecting');
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null; // P5: clear before reconnecting so next close can schedule
        this.reconnectAttempts++;
        this.connect(this.sessionId, this.token, this.callbacks!);
      }, delay);
    } else {
      this.setStatus('offline');
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
      this.ws.onerror = null;
      this.ws.close();
      this.ws = null;
    }
    this.reconnectAttempts = 0;
    this.connectionStatus = 'connecting'; // P6: reset for next session (no callback — component is unmounting)
  }
}

export const lessonSocket = new LessonSocket();
