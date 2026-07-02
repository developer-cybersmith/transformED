import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { LessonSocket } from '@/lib/ws/lessonSocket';
import { FakeWebSocket } from '../../testUtils/fakeWebSocket';

beforeEach(() => {
  FakeWebSocket.instances = [];
  global.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
});

afterEach(() => {
  vi.useRealTimers();
});

function latestFake(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

describe('LessonSocket — session_start on first open only', () => {
  it('sends exactly one session_start control frame on open', () => {
    const socket = new LessonSocket({ onServerMessage: vi.fn() });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();

    expect(latestFake().sentMessages).toHaveLength(1);
    expect(JSON.parse(latestFake().sentMessages[0])).toEqual({ type: 'session_start' });
  });

  it('does NOT resend session_start on a reconnect open (AC11)', () => {
    vi.useFakeTimers();
    const socket = new LessonSocket({ onServerMessage: vi.fn() });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen(); // first open — sends session_start
    latestFake().simulateClose(); // unexpected drop — schedules reconnect
    vi.runOnlyPendingTimers(); // reconnect fires -> open() -> new fake instance

    latestFake().simulateOpen(); // second (reconnect) open

    const allSent = FakeWebSocket.instances.flatMap((f) => f.sentMessages.map((m) => JSON.parse(m)));
    const sessionStartCount = allSent.filter((m) => m.type === 'session_start').length;
    expect(sessionStartCount).toBe(1);
  });
});

describe('LessonSocket — incoming frame normalization', () => {
  it('normalizes a flat error frame into a typed ServerMessage (AC2)', () => {
    const onServerMessage = vi.fn();
    const socket = new LessonSocket({ onServerMessage });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();
    onServerMessage.mockClear(); // drop the session_start-adjacent noise, if any (there is none, but keep intent clear)

    latestFake().simulateMessage({ error: 'boom' });

    expect(onServerMessage).toHaveBeenCalledTimes(1);
    expect(onServerMessage).toHaveBeenCalledWith({
      type: 'error',
      payload: { code: 'SERVER_ERROR', message: 'boom' },
    });
  });

  it('swallows a flat pong frame without forwarding it', () => {
    const onServerMessage = vi.fn();
    const socket = new LessonSocket({ onServerMessage });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();

    latestFake().simulateMessage({ type: 'pong' });

    expect(onServerMessage).not.toHaveBeenCalled();
  });

  it('forwards a state_change sync (from_state === to_state) unconditionally (AC3)', () => {
    const onServerMessage = vi.fn();
    const socket = new LessonSocket({ onServerMessage });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();

    const syncMsg = {
      type: 'state_change',
      payload: { session_id: 'sess_1', from_state: 'QUIZZING', to_state: 'QUIZZING' },
    };
    latestFake().simulateMessage(syncMsg);

    expect(onServerMessage).toHaveBeenCalledWith(syncMsg);
  });

  it('drops malformed (non-JSON) frames without throwing', () => {
    const onServerMessage = vi.fn();
    const socket = new LessonSocket({ onServerMessage });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();

    expect(() => latestFake().onmessage?.({ data: 'not json{' })).not.toThrow();
    expect(onServerMessage).not.toHaveBeenCalled();
  });
});

describe('LessonSocket — reconnect backoff (AC7)', () => {
  it('reconnects with exponential backoff for 5 attempts, then stops', () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    const socket = new LessonSocket({ onServerMessage: vi.fn() });
    socket.connect('sess_1', 'token');

    // 6 successive unexpected closes: the 6th must NOT schedule a further reconnect.
    for (let i = 0; i < 6; i++) {
      latestFake().simulateClose();
      vi.runOnlyPendingTimers();
    }

    const scheduledDelays = setTimeoutSpy.mock.calls
      .map((call) => call[1])
      .filter((delay): delay is number => typeof delay === 'number');

    expect(scheduledDelays).toEqual([1000, 2000, 4000, 8000, 16000]);
  });

  it('does not reconnect after a manual disconnect() (AC7)', () => {
    vi.useFakeTimers();
    const socket = new LessonSocket({ onServerMessage: vi.fn() });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();

    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    socket.disconnect();

    expect(setTimeoutSpy).not.toHaveBeenCalled();
  });
});

describe('LessonSocket — send / sendControl', () => {
  it('send() and sendControl() no-op without throwing when the socket is not open (AC5/AC6/2h)', () => {
    const socket = new LessonSocket({ onServerMessage: vi.fn() });
    socket.connect('sess_1', 'token');
    // Never opened — readyState stays CONNECTING, not OPEN.

    expect(() =>
      socket.send({
        type: 'attention_signal',
        payload: {
          session_id: 'sess_1',
          quiz_accuracy: null,
          teachback_score: null,
          behavioral_score: 0.5,
          head_pose_score: 0.5,
          blink_rate: 0.2,
        },
      }),
    ).not.toThrow();
    expect(() => socket.sendControl({ type: 'ping' })).not.toThrow();

    expect(latestFake().sentMessages).toHaveLength(0);
  });

  it('send() delivers the nested envelope once the socket is open', () => {
    const socket = new LessonSocket({ onServerMessage: vi.fn() });
    socket.connect('sess_1', 'token');
    latestFake().simulateOpen();
    latestFake().sentMessages = []; // clear the session_start frame sent on open

    socket.send({
      type: 'attention_signal',
      payload: {
        session_id: 'sess_1',
        quiz_accuracy: null,
        teachback_score: null,
        behavioral_score: 0.5,
        head_pose_score: 0.5,
        blink_rate: 0.2,
      },
    });

    expect(latestFake().sentMessages).toHaveLength(1);
    expect(JSON.parse(latestFake().sentMessages[0]).type).toBe('attention_signal');
  });
});
