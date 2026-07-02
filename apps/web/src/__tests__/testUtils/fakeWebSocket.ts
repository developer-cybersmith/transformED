// Minimal fake WebSocket for tests — jsdom does not implement the WebSocket API.
// Assign to global.WebSocket in a beforeEach; clear FakeWebSocket.instances alongside it.

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly url: string;
  readyState: number = FakeWebSocket.CONNECTING;
  sentMessages: string[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  /** Mirrors a real browser socket: throws (rather than silently no-op-ing) when
   *  called outside OPEN, so a regression in LessonSocket's own readyState guard
   *  would surface as a thrown error in tests instead of passing vacuously. */
  send(data: string): void {
    if (this.readyState !== FakeWebSocket.OPEN) {
      throw new Error(`FakeWebSocket: cannot send while not OPEN (readyState=${this.readyState})`);
    }
    this.sentMessages.push(data);
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  /** Test helper: simulate the server accepting the connection. */
  simulateOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** Test helper: simulate an incoming frame (JSON-serializes `data` for you). */
  simulateMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  /** Test helper: simulate an incoming frame using a raw, already-serialized string —
   *  for cases (like malformed JSON) that `simulateMessage` can't produce since it
   *  always JSON.stringifies its input. */
  simulateRawMessage(raw: string): void {
    this.onmessage?.({ data: raw });
  }

  /** Test helper: simulate an unexpected server-initiated close. */
  simulateClose(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  /** Test helper: simulate a connection error event (always followed by close, per spec). */
  simulateError(): void {
    this.onerror?.();
  }
}
