import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { TutorInterveneMessage, CesUpdateMessage, StateChangeMessage } from '@hie/shared/types/ws';

// ---------------------------------------------------------------------------
// MockWebSocket — replaces global WebSocket in jsdom
// Auto-onopen is deliberately NOT included; tests that need it call triggerOpen().
// This prevents spurious reconnectAttempts resets during multi-close sequences.
// ---------------------------------------------------------------------------

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState: number = MockWebSocket.OPEN;
  url: string;
  protocols: string[];
  sentMessages: string[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = Array.isArray(protocols)
      ? protocols
      : protocols
      ? [protocols]
      : [];
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  // Test helper: explicitly trigger open
  triggerOpen() {
    this.onopen?.();
  }

  // Test helper: simulate incoming server message
  simulateMessage(msg: object) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

let lastSocket: MockWebSocket | null = null;

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  lastSocket = null;
  // @ts-expect-error — mocking global
  global.WebSocket = class extends MockWebSocket {
    constructor(url: string, protocols?: string | string[]) {
      super(url, protocols);
      lastSocket = this;
    }
  };
  // @ts-expect-error — expose constants on mock class
  global.WebSocket.OPEN = MockWebSocket.OPEN;
  // @ts-expect-error
  global.WebSocket.CLOSED = MockWebSocket.CLOSED;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.resetModules();
});

// ---------------------------------------------------------------------------
// Helper: fresh LessonSocket instance per test (avoid singleton state bleed)
// ---------------------------------------------------------------------------
async function makeFreshSocket() {
  const mod = await import('@/lib/ws/lessonSocket');
  return new mod.LessonSocket();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LessonSocket', () => {

  it('2c: connect() constructs WebSocket with correct URL', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok123', cb);

    expect(lastSocket).not.toBeNull();
    expect(lastSocket!.url).toBe('ws://test-server:8000/ws/sess-abc');
  });

  it('2d: connect() passes [\'Bearer\', token] as subprotocol array', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'my-jwt-token', cb);

    expect(lastSocket!.protocols).toEqual(['Bearer', 'my-jwt-token']);
  });

  it('2e: handleClose schedules reconnect with delay=1000ms for attempt 0', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    const firstSocket = lastSocket!;
    firstSocket.close(); // → handleClose → delay 1000ms (2^0 × 1000)

    expect(lastSocket).toBe(firstSocket); // not reconnected yet
    vi.advanceTimersByTime(1000);
    expect(lastSocket).not.toBe(firstSocket); // new socket created
  });

  it('2f: handleClose schedules reconnect with delay=4000ms after 2 consecutive failures', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    // Connect — do NOT trigger onopen so reconnectAttempts don't reset
    socket.connect('sess-abc', 'tok', cb);

    // Failure 0: delay = 2^0 × 1000 = 1000ms
    lastSocket!.close();
    vi.advanceTimersByTime(1000); // timer fires → reconnectAttempts=1 → connect → socket1

    // Failure 1: delay = 2^1 × 1000 = 2000ms
    lastSocket!.close();
    vi.advanceTimersByTime(2000); // timer fires → reconnectAttempts=2 → connect → socket2

    // Failure 2: delay should be 2^2 × 1000 = 4000ms
    lastSocket!.close();
    const socketBeforeDelay = lastSocket;
    vi.advanceTimersByTime(3999);
    expect(lastSocket).toBe(socketBeforeDelay); // not yet reconnected
    vi.advanceTimersByTime(1);
    expect(lastSocket).not.toBe(socketBeforeDelay); // reconnected at exactly 4000ms
  });

  it('2g: after 5 failed attempts, connectionStatus becomes \'offline\' with no further reconnect', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    // Run 5 closes + timer fires (each timer fires → reconnectAttempts++ → connect → new socket)
    // After 5 timer fires, reconnectAttempts = 5 and the 6th close hits the else branch
    for (let i = 0; i < 5; i++) {
      lastSocket!.close();
      vi.advanceTimersByTime(Math.pow(2, i) * 1000);
    }
    // reconnectAttempts = 5, socket 5 just created — one more close triggers the offline branch
    lastSocket!.close();

    expect(socket.connectionStatus).toBe('offline');

    // Confirm no further reconnect timers fire
    const socketAtOffline = lastSocket;
    vi.advanceTimersByTime(60_000);
    expect(lastSocket).toBe(socketAtOffline);
  });

  it('2h: send() calls ws.send with JSON-stringified message', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    const msg = {
      type: 'attention_signal' as const,
      payload: {
        session_id: 'sess-abc',
        quiz_accuracy: null,
        teachback_score: null,
        behavioral_score: 1,
        head_pose_score: 1,
        blink_rate: 0.2,
      },
    };
    socket.send(msg);

    expect(lastSocket!.sentMessages).toHaveLength(1);
    expect(JSON.parse(lastSocket!.sentMessages[0])).toEqual(msg);
  });

  it('2i: send() is a no-op when ws.readyState is CLOSED', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);
    lastSocket!.readyState = MockWebSocket.CLOSED;

    const msg = {
      type: 'attention_signal' as const,
      payload: {
        session_id: 'sess-abc',
        quiz_accuracy: null,
        teachback_score: null,
        behavioral_score: 1,
        head_pose_score: 1,
        blink_rate: 0.2,
      },
    };
    socket.send(msg);

    expect(lastSocket!.sentMessages).toHaveLength(0);
  });

  it('2j: tutor_intervene message triggers onTutorIntervene callback', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    const serverMsg: TutorInterveneMessage = {
      type: 'tutor_intervene',
      payload: { session_id: 'sess-abc', type: 'distraction', message: 'Stay focused!' },
    };
    lastSocket!.simulateMessage(serverMsg);

    expect(cb.onTutorIntervene).toHaveBeenCalledWith(serverMsg.payload);
    expect(cb.onCesUpdate).not.toHaveBeenCalled();
  });

  it('2k: ces_update message triggers onCesUpdate with correct ces value', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    const serverMsg: CesUpdateMessage = {
      type: 'ces_update',
      payload: { session_id: 'sess-abc', ces: 73.5, window_index: 4 },
    };
    lastSocket!.simulateMessage(serverMsg);

    expect(cb.onCesUpdate).toHaveBeenCalledWith(serverMsg.payload);
    expect(cb.onCesUpdate.mock.calls[0][0].ces).toBe(73.5);
  });

  it('2l: state_change message triggers onStateChange with to_state', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    const serverMsg: StateChangeMessage = {
      type: 'state_change',
      payload: { session_id: 'sess-abc', from_state: 'TEACHING', to_state: 'QUIZZING' },
    };
    lastSocket!.simulateMessage(serverMsg);

    expect(cb.onStateChange).toHaveBeenCalledWith(serverMsg.payload);
    expect(cb.onStateChange.mock.calls[0][0].to_state).toBe('QUIZZING');
  });

  it('2m: disconnect() clears pending reconnect timer — no new socket created', async () => {
    process.env.NEXT_PUBLIC_WS_URL = 'ws://test-server:8000';
    const socket = await makeFreshSocket();
    const cb = { onTutorIntervene: vi.fn(), onCesUpdate: vi.fn(), onStateChange: vi.fn() };

    socket.connect('sess-abc', 'tok', cb);

    // Close to start a reconnect timer
    const s1 = lastSocket!;
    s1.close(); // → handleClose → timer at 1000ms

    // Disconnect before timer fires — should clear the timer
    socket.disconnect();

    // Advance well past the backoff — no new socket should appear
    vi.advanceTimersByTime(10_000);
    expect(lastSocket).toBe(s1);
  });

});
